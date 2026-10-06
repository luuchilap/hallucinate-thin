# src/detector_corrector.py
import ast
import json
import difflib
from typing import Dict, Any, Tuple, List, Optional
from src.ast_parser import extract_features, _get_call_name

KB_PATH = "src/knowledge_base.json"


def load_kb(path: str = KB_PATH) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _module_for_alias(imports_map: Dict[str, str], alias: str) -> str:
    return imports_map.get(alias, alias)


def detect_and_correct(code: str, prompt: str = "", kb_path: str = KB_PATH) -> Dict[str, Any]:
    """
    Conservative post-processor that:
      - preserves your existing fuzzy API correction & semantic rules
      - prefixes bare calls when the prompt clearly implies a library (e.g., read_csv -> pd.read_csv)
      - converts wrong-library IO to the intended one (e.g., urllib.request.urlopen -> requests.get)
      - fixes common pandas/filetype & JSON load/loads patterns
      - cleans up imports (no duplicates or silly alias combos)
    """
    kb = load_kb(kb_path)
    features = extract_features(code)
    if features is None:
        return {"detected": True, "issues": ["Parsing failed"], "corrected_code": code, "status": "parse_error"}

    imports_map = features["imports_map"]  # alias -> module
    tree = features["raw_tree"]

    issues: List[str] = []
    detected = False
    prompt_lower = prompt.lower()

    # From KB: alias -> canonical module name (e.g., "pd" -> "pandas")
    kb_alias_to_module: Dict[str, str] = {}
    for module_name, info in kb.items():
        for alias in info.get("aliases", []):
            kb_alias_to_module[alias] = module_name

    # Canonical alias preference for each module we know
    canonical_alias: Dict[str, str] = {
        "pandas": "pd",
        "numpy": "np",
        "matplotlib.pyplot": "plt",
        "requests": "requests",
        "json": "json",
    }

    # Define semantic rules per library (unchanged from your version)
    semantic_rules = {
        "json": {"prefer": ["load", "loads"], "avoid": ["dump", "dumps"]},
        "requests": {"prefer": ["get"], "avoid": ["post", "put", "delete"]},
        "matplotlib.pyplot": {"prefer": ["plot"], "avoid": ["bar", "scatter", "hist"]},
        "pandas": {"prefer": ["read_csv", "read_table"], "avoid": ["read_excel"]},
        "numpy": {"prefer": ["mean", "average"], "avoid": ["sum"]},
    }

    # Prompt-driven target inference: returns (module, preferred_function or None)
    def infer_from_prompt(p: str) -> Tuple[Optional[str], Optional[str]]:
        # module hints
        mod = None
        if "pandas" in p:
            mod = "pandas"
        elif "numpy" in p:
            mod = "numpy"
        elif "requests" in p:
            mod = "requests"
        elif "json" in p:
            mod = "json"
        elif "matplotlib" in p or "pyplot" in p:
            mod = "matplotlib.pyplot"

        # function hints (use first match we find)
        func_hints = ["read_csv", "read_table", "read_excel", "plot", "bar", "scatter",
                      "get", "post", "put", "delete", "mean", "average", "sum", "load", "loads"]
        hinted = None
        for fh in func_hints:
            if fh in p:
                hinted = fh
                break

        return mod, hinted

    target_module_from_prompt, target_func_from_prompt = infer_from_prompt(prompt_lower)

    def resolve_module_for_call(call_fullname: str) -> Tuple[str, Optional[str]]:
        if "." in call_fullname:
            prefix, _ = call_fullname.split(".", 1)
            if prefix in imports_map:
                return prefix, _module_for_alias(imports_map, prefix)
            if prefix in kb_alias_to_module:
                return prefix, kb_alias_to_module[prefix]
            return prefix, None
        return call_fullname, None

    # Helper: ast nodes for Name/Attribute utility
    def make_attr(module_alias: str, func_name: str) -> ast.Attribute:
        return ast.Attribute(value=ast.Name(id=module_alias, ctx=ast.Load()),
                             attr=func_name, ctx=ast.Load())

    # Helper: replace a call entirely (func + args/keywords)
    def replace_call(node: ast.Call, new_func: ast.expr, new_args: List[ast.expr], new_keywords: List[ast.keyword]) -> ast.Call:
        node.func = new_func
        node.args = new_args
        node.keywords = new_keywords
        return node

    # Helper: determine canonical alias presence; if not imported, missing import pass will add it
    def ensure_alias_for_module(module: str) -> str:
        alias = canonical_alias.get(module, module.split(".")[-1])
        return alias

    # === 1) Primary call patcher (keeps your existing logic & adds safe new rules) ===
    class CallPatcher(ast.NodeTransformer):
        def visit_Call(self, node: ast.Call):
            nonlocal detected, issues
            self.generic_visit(node)  # visit children first to make nested replacements robust
            call_name = _get_call_name(node)
            prefix, module_candidate = resolve_module_for_call(call_name)
            func_simple = call_name.split(".")[-1]

            # --- Wrong-library I/O -> requests.get heuristic ---
            # e.g., urllib.request.urlopen(x) OR <randomlib>.request.<x>open(x) -> requests.get(x) if prompt implies requests or 'get'
            if isinstance(node.func, ast.Attribute):
                # Flatten dotted attribute path for pattern checks
                dotted = []
                cur = node.func
                while isinstance(cur, ast.Attribute):
                    dotted.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    dotted.append(cur.id)
                dotted_path = ".".join(reversed(dotted))

                if ("requests" in prompt_lower or " get(" in prompt_lower or " get" in prompt_lower) and (
                    dotted_path.startswith("urllib.request.urlopen") or
                    (".request." in dotted_path and dotted_path.endswith("open"))
                ):
                    alias = ensure_alias_for_module("requests")
                    replace_call(node, make_attr(alias, "get"), node.args[:1], [])  # requests.get(arg0)
                    detected = True
                    issues.append("Replaced urlopen/open-style call with requests.get() per prompt")
                    return node  # already fixed

            # --- Bare call prefixing based on prompt (e.g., read_csv -> pd.read_csv) ---
            if module_candidate is None and isinstance(node.func, ast.Name):
                bare_name = node.func.id

                # Pandas: read_csv / read_table should be pd.read_csv / pd.read_table
                if ("pandas" in prompt_lower) and bare_name in {"read_csv", "read_table", "read_excel"}:
                    alias = ensure_alias_for_module("pandas")
                    node.func = make_attr(alias, bare_name)
                    detected = True
                    issues.append(f"Prefixed bare '{bare_name}' with '{alias}.' based on prompt")
                    return node

                # Matplotlib: plot/bar/scatter -> plt.plot etc.
                if ("matplotlib" in prompt_lower or "pyplot" in prompt_lower) and bare_name in {"plot", "bar", "scatter", "hist"}:
                    alias = ensure_alias_for_module("matplotlib.pyplot")
                    node.func = make_attr(alias, bare_name)
                    detected = True
                    issues.append(f"Prefixed bare '{bare_name}' with '{alias}.' based on prompt")
                    return node

            # --- Pandas file path heuristic: open('*.csv').read() -> pd.read_csv('*.csv') ---
            if isinstance(node.func, ast.Attribute) and node.func.attr == "read":
                # pattern: <something>.read()
                val = node.func.value
                # common case: open('data.csv').read()
                if isinstance(val, ast.Call) and isinstance(val.func, ast.Name) and val.func.id == "open":
                    if len(val.args) >= 1 and isinstance(val.args[0], ast.Constant) and isinstance(val.args[0].value, str):
                        s = val.args[0].value
                        if s.endswith(".csv") and ("pandas" in prompt_lower or target_module_from_prompt == "pandas"):
                            alias = ensure_alias_for_module("pandas")
                            replace_call(node, make_attr(alias, "read_csv"), [ast.Constant(value=s)], [])
                            detected = True
                            issues.append("Converted open(...).read() with .csv to pd.read_csv()")
                            return node

            # --- JSON: x.read() -> json.load(x) or json.loads(x.read()) as guided by prompt ---
            if ("json" in prompt_lower or target_module_from_prompt == "json"):
                # Case: z.read()
                if isinstance(node.func, ast.Attribute) and node.func.attr == "read":
                    if isinstance(node.func.value, ast.Name):
                        stream_name = node.func.value.id
                        alias = ensure_alias_for_module("json")
                        if target_func_from_prompt == "loads":
                            # json.loads(z.read())
                            replace_call(node, make_attr(alias, "loads"), [node], [])
                            detected = True
                            issues.append("Wrapped <x>.read() with json.loads(...) as implied by prompt")
                            return node
                        else:
                            # default to json.load(z)
                            replace_call(node, make_attr(alias, "load"), [ast.Name(id=stream_name, ctx=ast.Load())], [])
                            detected = True
                            issues.append("Replaced <x>.read() with json.load(x) as implied by prompt")
                            return node

            # Skip if we still don't know the module
            if not module_candidate:
                # Try module inference for bare names when prompt is clear
                if isinstance(node.func, ast.Name) and target_module_from_prompt in kb:
                    known_funcs = kb[target_module_from_prompt].get("functions", [])
                    bare = node.func.id
                    if bare in known_funcs:
                        alias = ensure_alias_for_module(target_module_from_prompt)
                        node.func = make_attr(alias, bare)
                        detected = True
                        issues.append(f"Assigned bare call '{bare}' to '{alias}.' via prompt inference")
                        return node
                return node  # nothing else to do

            # If module_candidate isn't exactly a kb key, try to find closest top-level match (unchanged behavior)
            kb_module_key = None
            if module_candidate in kb:
                kb_module_key = module_candidate
            else:
                for key in kb.keys():
                    if module_candidate.split(".")[0] == key.split(".")[0]:
                        kb_module_key = key
                        break

            if not kb_module_key:
                return node

            known_funcs = kb[kb_module_key].get("functions", [])
            rules = semantic_rules.get(kb_module_key, None)

            # === Existing invalid/unknown function detection + close match suggestion ===
            if func_simple not in known_funcs:
                suggestion = difflib.get_close_matches(func_simple, known_funcs, n=1)
                detected = True
                issue_text = f"Unknown API '{func_simple}' for module '{kb_module_key}' (call: {call_name})"
                if suggestion:
                    issue_text += f"; suggestion: {suggestion[0]}"
                    if isinstance(node.func, ast.Attribute):
                        node.func.attr = suggestion[0]
                    elif isinstance(node.func, ast.Name):
                        node.func.id = suggestion[0]
                issues.append(issue_text)

            # === Contextual .csv fix before unparsing (preserved) ===
            if (
                isinstance(node.func, ast.Attribute)
                and getattr(node.func, "attr", "") == "read_excel"
            ):
                # Only rewrite if any argument string literal endswith .csv
                arg_text = ast.unparse(node)
                if ".csv" in arg_text:
                    node.func.attr = "read_csv"
                    detected = True
                    issues.append("Context fix: replaced 'read_excel' with 'read_csv' due to '.csv' usage")

            # === Semantic rule correction (preserved, but gated more explicitly by prompt & library) ===
            if rules and (kb_module_key in prompt_lower or (target_module_from_prompt == kb_module_key)):
                prefer, avoid = rules["prefer"], rules["avoid"]
                if any(p in prompt_lower for p in prefer) and func_simple in avoid and func_simple not in prefer:
                    detected = True
                    preferred = prefer[0]
                    issues.append(f"Semantic mismatch: '{func_simple}' used, but prompt implies '{preferred}'")
                    if isinstance(node.func, ast.Attribute):
                        node.func.attr = preferred
                    elif isinstance(node.func, ast.Name):
                        # Convert bare to aliased if needed
                        alias = ensure_alias_for_module(kb_module_key)
                        node.func = make_attr(alias, preferred)

            return node

    patcher = CallPatcher()
    patched_tree = patcher.visit(tree)
    ast.fix_missing_locations(patched_tree)
    corrected_code = ast.unparse(patched_tree)

    # === 2) Post-pass semantic tightening (string-level, conservative) ===
    # If prompt says "plot" and corrected code still returns bar/scatter, swap to plot.
    if ("matplotlib" in prompt_lower or "pyplot" in prompt_lower) and "plot" in prompt_lower:
        if ".bar(" in corrected_code or ".scatter(" in corrected_code:
            corrected_code = corrected_code.replace(".bar(", ".plot(").replace(".scatter(", ".plot(")
            detected = True
            issues.append("Post-pass: normalized pyplot call to 'plot' per prompt")

    # === 3) Missing imports (clean, non-duplicating) ===
    # We scan for canonical aliases used in corrected_code and add imports only if:
    #   - alias not already imported, and
    #   - we didn't already add the exact same import line
    def have_import_for(alias: str, module: str) -> bool:
        # If the alias is already present in the original imports_map (alias->module), we consider it present.
        return alias in imports_map and _module_for_alias(imports_map, alias) == module

    missing_imports: List[str] = []

    # Determine which canonical aliases appear and need imports
    for module, alias in canonical_alias.items():
        # Add import only if the alias token is used as a whole word in code
        # (naive but effective; avoids adding if alias appears only inside strings)
        token_used = (f"{alias}." in corrected_code) or (f"{alias}(" in corrected_code)
        if token_used and not have_import_for(alias, module):
            # Choose "import module as alias" unless alias equals the module's last token
            if alias != module.split(".")[-1]:
                imp = f"import {module} as {alias}"
            else:
                imp = f"import {module}"
            if imp not in missing_imports and imp not in corrected_code.splitlines():
                missing_imports.append(imp)

    if missing_imports:
        corrected_code = "\n".join(missing_imports) + "\n" + corrected_code
        detected = True
        issues.append(f"Added missing imports: {', '.join(missing_imports)}")

    # === 4) Final small cleanups ===
    # - avoid duplicated identical import lines
    seen_imports = set()
    final_lines = []
    for line in corrected_code.splitlines():
        if line.startswith("import "):
            if line in seen_imports:
                continue
            seen_imports.add(line)
        final_lines.append(line)
    corrected_code = "\n".join(final_lines)

    return {
        "detected": detected,
        "issues": issues,
        "corrected_code": corrected_code,
        "status": "ok",
    }
