import re
import json
import difflib
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple, Optional

KB_PATH = Path(r"C:\Users\lclap\work\extracted_nc_libraries\nc_knowledge_base.json")

# Standard Java & Spring packages that are always whitelisted
STANDARD_WHITELIST_PACKAGES = {
    "java.lang", "java.util", "java.io", "java.nio", "java.time", "java.math", "java.net", "java.concurrent",
    "org.springframework.beans", "org.springframework.context", "org.springframework.stereotype",
    "org.springframework.web", "org.springframework.boot", "org.springframework.data",
    "org.springframework.http", "org.springframework.security", "org.springframework.transaction",
    "org.hibernate", "jakarta.persistence", "javax.persistence", "jakarta.validation", "javax.validation",
    "org.slf4j", "lombok"
}

STANDARD_JAVA_TYPES = {
    "String", "Integer", "Long", "Double", "Float", "Boolean", "Byte", "Short", "Character", "Object",
    "List", "ArrayList", "Map", "HashMap", "Set", "HashSet", "Optional", "Arrays", "Collections",
    "Date", "LocalDate", "LocalDateTime", "Instant", "UUID", "BigDecimal", "BigInteger",
    "ResponseEntity", "HttpStatus", "HttpHeaders", "Logger", "LoggerFactory",
    "StringUtils", "CollectionUtils", "ObjectUtils", "BeanUtils", "FileUtils", "IOUtils", "Objects",
    "int", "long", "double", "float", "boolean", "byte", "short", "char", "void"
}

STANDARD_METHODS = {
    "equals", "hashCode", "toString", "getClass", "clone", "notify", "notifyAll", "wait",
    "get", "set", "add", "remove", "size", "isEmpty", "contains", "containsKey", "containsValue",
    "put", "putAll", "clear", "keySet", "values", "entrySet", "stream", "collect", "map", "filter",
    "forEach", "findFirst", "orElse", "orElseGet", "orElseThrow", "isPresent", "ifPresent",
    "builder", "build", "of", "ok", "badRequest", "notFound", "status", "body", "info", "warn", "error", "debug"
}

def string_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

class JavaASTVisitor:
    """Lightweight deterministic AST / syntax visitor for Java code."""
    
    def __init__(self, code: str):
        self.raw_code = code
        self.clean_code = self._strip_comments(code)
        
    def _strip_comments(self, code: str) -> str:
        # Strip single-line comments
        c = re.sub(r'//.*', '', code)
        # Strip multi-line comments
        c = re.sub(r'/\*.*?\*/', '', c, flags=re.DOTALL)
        return c

    def extract_package(self) -> str:
        m = re.search(r'package\s+([a-zA-Z0-9_.]+)\s*;', self.clean_code)
        return m.group(1) if m else ""

    def extract_imports(self) -> List[Dict[str, str]]:
        imports = []
        for m in re.finditer(r'import\s+(?:static\s+)?([a-zA-Z0-9_.]+)(?:\.\*)?\s*;', self.clean_code):
            fqn = m.group(1)
            is_wildcard = ".*" in m.group(0)
            simple_name = fqn.split('.')[-1]
            imports.append({
                "fqn": fqn,
                "simple_name": simple_name,
                "is_wildcard": is_wildcard,
                "raw": m.group(0)
            })
        return imports

    def extract_class_declarations(self) -> List[Dict[str, Any]]:
        classes = []
        for m in re.finditer(r'(?:public|protected|private)?\s*(?:abstract|final)?\s*(class|interface|enum|record)\s+([a-zA-Z0-9_]+)(?:\s+extends\s+([a-zA-Z0-9_<>, ]+))?(?:\s+implements\s+([a-zA-Z0-9_<>, ]+))?', self.clean_code):
            c_type = m.group(1)
            name = m.group(2)
            extends_clause = m.group(3) or ""
            implements_clause = m.group(4) or ""
            classes.append({
                "name": name,
                "type": c_type,
                "extends": [e.strip() for e in extends_clause.split(',') if e.strip()],
                "implements": [i.strip() for i in implements_clause.split(',') if i.strip()]
            })
        return classes

    def extract_field_and_var_types(self) -> Dict[str, str]:
        """Maps variable/field names to their declared types."""
        var_types = {}
        # Pattern: Type varName = ... or Type varName;
        for m in re.finditer(r'\b([A-Z][a-zA-Z0-9_<>?,\s]*)\s+([a-zA-Z0-9_]+)\s*(?:[=;,\)])', self.clean_code):
            raw_type = m.group(1).strip()
            var_name = m.group(2).strip()
            # Clean generic type e.g. List<MyType> -> MyType or List
            base_type = raw_type.split('<')[0].strip()
            if base_type not in {"return", "public", "private", "protected", "static", "final", "new", "throw", "case", "class", "interface", "enum"}:
                var_types[var_name] = base_type
        return var_types

    def extract_type_references(self) -> Set[str]:
        """Finds all uppercase type identifiers used across annotations, new expressions, field types, casts."""
        types = set()
        # Annotations: @MyAnnotation
        for m in re.finditer(r'@([A-Z][a-zA-Z0-9_]*)', self.clean_code):
            types.add(m.group(1))
        # New expressions: new MyClass(...)
        for m in re.finditer(r'new\s+([A-Z][a-zA-Z0-9_]*)\s*\(', self.clean_code):
            types.add(m.group(1))
        # Type casts: (MyClass) var
        for m in re.finditer(r'\(\s*([A-Z][a-zA-Z0-9_]*)\s*\)', self.clean_code):
            types.add(m.group(1))
        # Static member access: MyClass.MY_CONST or MyClass.method()
        for m in re.finditer(r'\b([A-Z][a-zA-Z0-9_]*)\.[a-zA-Z0-9_]+', self.clean_code):
            types.add(m.group(1))
        # Variable declarations: MyClass varName
        for m in re.finditer(r'\b([A-Z][a-zA-Z0-9_]*)\s+[a-z][a-zA-Z0-9_]*\b', self.clean_code):
            types.add(m.group(1))
        return types

    def extract_method_calls(self) -> List[Dict[str, Any]]:
        """Extracts call sites: receiver.methodName(args...) or methodName(args...)."""
        calls = []
        call_pattern = re.compile(r'(?:([a-zA-Z0-9_]+)\.)?([a-zA-Z0-9_]+)\s*\(([^)]*)\)')
        for m in call_pattern.finditer(self.clean_code):
            receiver = m.group(1) or ""
            method_name = m.group(2)
            args_str = m.group(3).strip()
            
            if method_name in {"if", "while", "for", "switch", "catch", "synchronized", "super", "this"}:
                continue
                
            # Count args
            if not args_str:
                arg_count = 0
            else:
                arg_count = len([a for a in args_str.split(',') if a.strip()])
                
            calls.append({
                "receiver": receiver,
                "method": method_name,
                "arg_count": arg_count,
                "args_raw": args_str,
                "raw": m.group(0)
            })
        return calls


class NcKnowledgeBase:
    """Manages the Netcompany Symbol Table and Lookup Index."""
    
    def __init__(self, kb_file: Path = KB_PATH):
        self.kb_file = kb_file
        self.data: Dict[str, Any] = {}
        self.classes_by_simple: Dict[str, List[Dict[str, Any]]] = {}
        self.classes_by_fqn: Dict[str, Dict[str, Any]] = {}
        self.all_classes: List[str] = []
        self.all_methods: Dict[str, List[str]] = {}
        self._load()

    def _load(self):
        if not self.kb_file.exists():
            print(f"[Warning] KB file not found at {self.kb_file}. Operating in basic mode.")
            return
        with open(self.kb_file, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        self.classes_by_simple = self.data.get("classes", {})
        self.classes_by_fqn = self.data.get("fqn_map", {})
        self.all_classes = self.data.get("all_classes_set", [])
        self.all_methods = self.data.get("all_methods", {})
        print(f"[KnowledgeBase] Loaded {len(self.all_classes)} unique classes, {len(self.all_methods)} unique methods from KB.")

    def is_known_type(self, type_name: str) -> bool:
        if type_name in STANDARD_JAVA_TYPES:
            return True
        if type_name in self.classes_by_simple:
            return True
        return False

    def get_classes_by_name(self, simple_name: str) -> List[Dict[str, Any]]:
        return self.classes_by_simple.get(simple_name, [])

    def find_best_class_match(self, hallucinated_name: str, threshold: float = 0.6) -> Optional[str]:
        """Finds closest valid Netcompany class name using string similarity."""
        best_match = None
        best_score = 0.0
        for cls_name in self.all_classes:
            score = string_similarity(hallucinated_name, cls_name)
            if score > best_score:
                best_score = score
                best_match = cls_name
        if best_score >= threshold:
            return best_match
        return None

    def find_best_method_match(self, class_name: str, hallucinated_method: str, arg_count: int) -> Optional[Dict[str, Any]]:
        """Finds closest valid method in the specified class matching arity."""
        classes = self.get_classes_by_name(class_name)
        candidates = []
        for c in classes:
            for m in c.get("methods", []):
                score = string_similarity(hallucinated_method, m["name"])
                # Bonus if parameter count matches
                if m["param_count"] == arg_count:
                    score += 0.2
                candidates.append((score, m))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            if candidates[0][0] >= 0.6:
                return candidates[0][1]
        return None


class NcAstDetector:
    """Deterministic Hallucination Detector for Netcompany Java Code."""

    def __init__(self, kb: NcKnowledgeBase):
        self.kb = kb

    def detect_hallucinations(self, code: str) -> List[Dict[str, Any]]:
        visitor = JavaASTVisitor(code)
        issues = []
        
        declared_classes = {c["name"] for c in visitor.extract_class_declarations()}
        imports = visitor.extract_imports()
        imported_classes = {imp["simple_name"]: imp["fqn"] for imp in imports}
        var_types = visitor.extract_field_and_var_types()
        type_refs = visitor.extract_type_references()
        method_calls = visitor.extract_method_calls()

        # 1. Detect Phantom Classes / Types
        for t in type_refs:
            if t in declared_classes or t in STANDARD_JAVA_TYPES:
                continue
            if t not in self.kb.classes_by_simple:
                # Check if it looks like a Netcompany type (starts with Amplio, Foundation, NC, etc.)
                if any(t.startswith(prefix) for prefix in ["Amplio", "Foundation", "Nc", "Core", "Audit", "Tenant", "Security", "Batch", "Doc"]):
                    match = self.kb.find_best_class_match(t)
                    issues.append({
                        "type": "PHANTOM_CLASS",
                        "symbol": t,
                        "suggestion": match,
                        "reason": f"Class '{t}' does not exist in Netcompany Knowledge Base."
                    })
            else:
                # Class exists in KB, check if it's imported
                if t not in imported_classes and not any(imp["is_wildcard"] for imp in imports):
                    curr_pkg = visitor.extract_package()
                    cand_fqns = [c["fqn"] for c in self.kb.get_classes_by_name(t)]
                    in_same_pkg = any(f"{curr_pkg}.{t}" == fqn for fqn in cand_fqns)
                    if not in_same_pkg:
                        issues.append({
                            "type": "MISSING_IMPORT",
                            "symbol": t,
                            "suggestion": self.kb.get_classes_by_name(t)[0]["fqn"] if self.kb.get_classes_by_name(t) else None,
                            "reason": f"Class '{t}' is used but not explicitly imported."
                        })

        # 2. Detect Phantom Methods & Signature Mismatches
        for call in method_calls:
            receiver = call["receiver"]
            method_name = call["method"]
            arg_count = call["arg_count"]

            if method_name in STANDARD_METHODS:
                continue

            target_class_name = None
            if receiver:
                if receiver[0].isupper():  # Static call e.g. AmplioContextHolder.get()
                    target_class_name = receiver
                elif receiver in var_types:  # Instance call e.g. service.get()
                    target_class_name = var_types[receiver]

            if target_class_name and target_class_name in self.kb.classes_by_simple:
                class_info_list = self.kb.get_classes_by_name(target_class_name)
                all_class_methods = []
                for ci in class_info_list:
                    all_class_methods.extend(ci.get("methods", []))

                method_names = {m["name"] for m in all_class_methods}
                if method_name not in method_names:
                    best_m = self.kb.find_best_method_match(target_class_name, method_name, arg_count)
                    issues.append({
                        "type": "PHANTOM_METHOD",
                        "symbol": f"{receiver}.{method_name}",
                        "receiver": receiver,
                        "class": target_class_name,
                        "method": method_name,
                        "suggestion": best_m["name"] if best_m else None,
                        "reason": f"Method '{method_name}' does not exist in class '{target_class_name}'."
                    })
                else:
                    # Method exists, verify arity
                    matching_arities = [m["param_count"] for m in all_class_methods if m["name"] == method_name]
                    if arg_count not in matching_arities:
                        issues.append({
                            "type": "SIGNATURE_MISMATCH",
                            "symbol": f"{receiver}.{method_name}",
                            "receiver": receiver,
                            "class": target_class_name,
                            "method": method_name,
                            "expected_arity": matching_arities,
                            "actual_arity": arg_count,
                            "reason": f"Method '{method_name}' called with {arg_count} args, but expected {matching_arities}."
                        })

        return issues


class NcAstCorrector:
    """Deterministic AST Mutator and Code Rewriter."""

    def __init__(self, kb: NcKnowledgeBase):
        self.kb = kb
        self.detector = NcAstDetector(kb)

    def correct_code(self, raw_code: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Analyzes and deterministically fixes hallucinations in Java source code."""
        issues = self.detector.detect_hallucinations(raw_code)
        if not issues:
            return raw_code, []

        corrected_code = raw_code
        applied_fixes = []
        imports_to_add = set()

        # Phase 1: Correct Phantom Classes & Method Names via String Mutation
        for issue in issues:
            itype = issue["type"]
            suggestion = issue.get("suggestion")

            if itype == "PHANTOM_CLASS" and suggestion:
                symbol = issue["symbol"]
                # Replace symbol word boundary
                pattern = r'\b' + re.escape(symbol) + r'\b'
                corrected_code = re.sub(pattern, suggestion, corrected_code)
                # Queue import for suggestion
                cand = self.kb.get_classes_by_name(suggestion)
                if cand:
                    imports_to_add.add(cand[0]["fqn"])
                applied_fixes.append({
                    "action": "REPLACE_CLASS",
                    "original": symbol,
                    "fixed": suggestion
                })

            elif itype == "PHANTOM_METHOD" and suggestion:
                receiver = issue.get("receiver") or issue.get("class")
                m_name = issue["method"]
                # Replace method invocation on receiver
                pattern = r'(\b' + re.escape(receiver) + r'\s*\.\s*)' + re.escape(m_name) + r'(\s*\()'
                corrected_code = re.sub(pattern, r'\g<1>' + suggestion + r'\g<2>', corrected_code)
                applied_fixes.append({
                    "action": "REPLACE_METHOD",
                    "original": f"{receiver}.{m_name}",
                    "fixed": f"{receiver}.{suggestion}"
                })

            elif itype == "MISSING_IMPORT" and suggestion:
                imports_to_add.add(suggestion)
                applied_fixes.append({
                    "action": "INJECT_IMPORT",
                    "import": suggestion
                })

        # Phase 2: Inject Missing Imports cleanly after package declaration
        if imports_to_add:
            lines = corrected_code.splitlines()
            pkg_idx = -1
            for i, line in enumerate(lines):
                if line.strip().startswith("package "):
                    pkg_idx = i
                    break
            
            import_statements = [f"import {imp};" for imp in sorted(imports_to_add)]
            if pkg_idx != -1:
                # Insert after package line
                new_lines = lines[:pkg_idx+1] + [""] + import_statements + lines[pkg_idx+1:]
                corrected_code = "\n".join(new_lines)
            else:
                # Prepend at start
                corrected_code = "\n".join(import_statements) + "\n\n" + corrected_code

        return corrected_code, applied_fixes
