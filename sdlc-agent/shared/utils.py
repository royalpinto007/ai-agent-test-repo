import subprocess
import os
import re
import json

from shared.claude import ask_claude


def run_git(args, cwd):
    result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def run_tests(cwd):
    result = subprocess.run(["npm", "test"], cwd=cwd, capture_output=True, text=True)
    passed = result.returncode == 0
    output = (result.stdout + result.stderr).strip()
    return passed, output


def get_file_tree(repo_path, ignore_dirs=None):
    if ignore_dirs is None:
        ignore_dirs = {".git", "node_modules", "venv", "__pycache__", ".env", "sessions"}
    tree = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), repo_path)
            tree.append(rel)
    return sorted(tree)


def read_file(repo_path, file_path):
    abs_path = os.path.join(repo_path, file_path)
    if not os.path.exists(abs_path):
        return None
    with open(abs_path, "r") as f:
        return f.read()


def write_file(repo_path, file_path, content):
    abs_path = os.path.join(repo_path, file_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w") as f:
        f.write(content)


def parse_js_imports(content):
    patterns = [
        r'require\(["\']([^"\']+)["\']\)',
        r'import\s+.*?\s+from\s+["\']([^"\']+)["\']',
        r'import\s+["\']([^"\']+)["\']',
    ]
    imports = []
    for pattern in patterns:
        imports.extend(re.findall(pattern, content))
    return [i for i in imports if i.startswith(".")]


def resolve_import(base_file, import_path, file_tree):
    base_dir = os.path.dirname(base_file)
    resolved = os.path.normpath(os.path.join(base_dir, import_path))
    for candidate in [resolved, resolved + ".js", resolved + ".ts",
                      resolved + "/index.js", resolved + "/index.ts"]:
        if candidate in file_tree:
            return candidate
    return None


def build_dependency_graph(repo_path, file_tree):
    imports_map = {}
    for f in file_tree:
        if not (f.endswith(".js") or f.endswith(".ts")):
            continue
        content = read_file(repo_path, f)
        if not content:
            continue
        for imp in parse_js_imports(content):
            resolved = resolve_import(f, imp, file_tree)
            if resolved:
                imports_map.setdefault(resolved, []).append(f)
    return imports_map


def find_affected_files(repo_path, seed_files, file_tree):
    dep_graph = build_dependency_graph(repo_path, file_tree)
    affected = set(seed_files)
    queue = list(seed_files)
    while queue:
        f = queue.pop()
        for importer in dep_graph.get(f, []):
            if importer not in affected:
                affected.add(importer)
                queue.append(importer)
    return sorted(affected)


def grep_repo(repo_path, pattern, file_tree):
    matches = []
    for f in file_tree:
        content = read_file(repo_path, f)
        if content and re.search(pattern, content):
            matches.append(f)
    return matches


def identify_relevant_files(issue_title, issue_description, repo_path, file_tree):
    file_tree_str = "\n".join(file_tree)
    prompt = f"""You are a senior developer. Given the task below and the file tree, list the files most likely to need changes.

TASK: {issue_title}
DESCRIPTION: {issue_description}

FILE TREE:
{file_tree_str}

Return ONLY a JSON array of relative file paths. No explanation, no markdown, just the JSON array.
"""
    response = ask_claude(prompt)
    try:
        seed_files = [f for f in json.loads(response) if isinstance(f, str) and f in file_tree]
    except Exception:
        seed_files = []

    affected = find_affected_files(repo_path, seed_files, file_tree)

    for word in re.findall(r'\b\w{4,}\b', issue_title):
        for f in grep_repo(repo_path, rf'\b{word}\b', file_tree):
            if f not in affected:
                affected.append(f)

    return seed_files, sorted(set(affected))
