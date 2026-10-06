import os
import re
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Set

SOURCE_JSONL = Path(r"C:\Users\lclap\work\extracted_nc_libraries\processed_code_snippets.jsonl")
OUTPUT_KB_JSON = Path(r"C:\Users\lclap\work\extracted_nc_libraries\nc_knowledge_base.json")

# Matches class and interface methods (with or without access modifiers)
METHOD_HEADER_PATTERN = re.compile(
    r'^\s*(?:(?:public|protected|private|static|final|abstract|synchronized|default|native)\s+)*'
    r'([a-zA-Z0-9_<>, ?\[\]\.]+)\s+([a-zA-Z0-9_]+)\s*\(([^)]*)\)\s*(?:throws\s+[^{;]+)?(?:\s*\{|;)',
    re.MULTILINE
)

FIELD_PATTERN = re.compile(
    r'(?:public|protected|private)\s+(?:static\s+)?(?:final\s+)?([a-zA-Z0-9_<>, ?\[\]\.]+)\s+([a-zA-Z0-9_]+)\s*(?:=\s*[^;]+)?\s*;'
)

KEYWORDS_EXCLUDED = {"if", "while", "for", "switch", "catch", "synchronized", "class", "interface", "enum", "record", "return", "new", "throw"}

def clean_type(t: str) -> str:
    return " ".join(t.strip().split())

def extract_methods(code: str) -> List[Dict[str, Any]]:
    methods = []
    # Strip comments
    clean_code = re.sub(r'//.*', '', code)
    clean_code = re.sub(r'/\*.*?\*/', '', clean_code, flags=re.DOTALL)
    
    for match in METHOD_HEADER_PATTERN.finditer(clean_code):
        ret_type = clean_type(match.group(1))
        name = match.group(2)
        params_str = match.group(3).strip()
        
        if name in KEYWORDS_EXCLUDED or ret_type in KEYWORDS_EXCLUDED:
            continue
            
        param_tokens = [p.strip() for p in params_str.split(',') if p.strip()] if params_str else []
        params = []
        for pt in param_tokens:
            pt_clean = re.sub(r'@\w+(?:\([^)]*\))?\s+', '', pt).strip()
            parts = pt_clean.rsplit(None, 1)
            if len(parts) == 2:
                p_type, p_name = parts[0], parts[1]
            elif len(parts) == 1:
                p_type, p_name = parts[0], ""
            else:
                p_type, p_name = "Object", ""
            params.append({"type": clean_type(p_type), "name": p_name})
            
        is_static = "static" in match.group(0)
        methods.append({
            "name": name,
            "return_type": ret_type,
            "param_count": len(params),
            "params": params,
            "is_static": is_static
        })
    return methods

def extract_fields_and_constants(code: str, class_type: str) -> List[str]:
    fields = []
    clean_code = re.sub(r'//.*', '', code)
    clean_code = re.sub(r'/\*.*?\*/', '', clean_code, flags=re.DOTALL)
    
    for match in FIELD_PATTERN.finditer(clean_code):
        fname = match.group(2)
        fields.append(fname)
        
    return list(set(fields))

def build_knowledge_base():
    start_time = time.time()
    print(f"Reading {SOURCE_JSONL}...")
    if not SOURCE_JSONL.exists():
        print(f"Error: {SOURCE_JSONL} does not exist!")
        return

    kb = {
        "metadata": {
            "total_classes": 0,
            "total_methods": 0,
            "total_packages": 0,
            "frameworks": ["nc.foundation", "nc.amplio"]
        },
        "packages": {},
        "classes": {},
        "fqn_map": {},
        "all_methods": {},
        "all_classes_set": []
    }

    all_packages: Set[str] = set()
    total_methods_count = 0
    count = 0

    with open(SOURCE_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            pkg = item.get("package", "")
            class_name = item.get("class_name", "")
            class_type = item.get("class_type", "class")
            archetype = item.get("archetype", "CORE_LOGIC")
            code = item.get("code", "")
            group = item.get("group", "")
            module = item.get("module", "")

            if not class_name or not pkg:
                continue

            fqn = f"{pkg}.{class_name}"
            all_packages.add(pkg)

            methods = extract_methods(code)
            fields = extract_fields_and_constants(code, class_type)
            total_methods_count += len(methods)

            class_info = {
                "fqn": fqn,
                "simple_name": class_name,
                "package": pkg,
                "class_type": class_type,
                "archetype": archetype,
                "group": group,
                "module": module,
                "methods": methods,
                "fields": fields
            }

            if pkg not in kb["packages"]:
                kb["packages"][pkg] = []
            if class_name not in kb["packages"][pkg]:
                kb["packages"][pkg].append(class_name)

            if class_name not in kb["classes"]:
                kb["classes"][class_name] = []
            kb["classes"][class_name].append(class_info)

            kb["fqn_map"][fqn] = class_info

            for m in methods:
                mname = m["name"]
                if mname not in kb["all_methods"]:
                    kb["all_methods"][mname] = []
                if fqn not in kb["all_methods"][mname]:
                    kb["all_methods"][mname].append(fqn)
            
            count += 1

    kb["metadata"]["total_classes"] = len(kb["fqn_map"])
    kb["metadata"]["total_methods"] = total_methods_count
    kb["metadata"]["total_packages"] = len(all_packages)
    kb["all_classes_set"] = list(kb["classes"].keys())

    elapsed = time.time() - start_time
    print(f"Extraction Completed in {elapsed:.2f} seconds ({count} classes parsed)!")
    print(f"Total Packages: {kb['metadata']['total_packages']}")
    print(f"Total Classes (FQN): {kb['metadata']['total_classes']}")
    print(f"Total Unique Simple Class Names: {len(kb['classes'])}")
    print(f"Total Methods Indexed: {kb['metadata']['total_methods']}")

    print(f"Writing Knowledge Base to {OUTPUT_KB_JSON}...")
    with open(OUTPUT_KB_JSON, "w", encoding="utf-8") as out_f:
        json.dump(kb, out_f, indent=2, ensure_ascii=False)
    print(f"Knowledge Base JSON written successfully ({OUTPUT_KB_JSON.stat().st_size / (1024*1024):.2f} MB)!")

if __name__ == "__main__":
    build_knowledge_base()
