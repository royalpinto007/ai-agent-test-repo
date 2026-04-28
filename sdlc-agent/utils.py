import subprocess
import os
import re
import json


def run_git(args, cwd):
    result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def ask_claude(prompt):
    result = subprocess.run(
        ["claude", "-p", "--tools", ""],
        input=prompt,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr.strip()}")
    output = result.stdout.strip()
    if output.startswith("```"):
        lines = output.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        output = "\n".join(lines)
    return output


def get_file_tree(repo_path, ignore_dirs=None):
    if ignore_dirs is None:
        ignore_dirs = {".git", "node_modules", "venv", "__pycache__", ".env", "sessions"}
    tree = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, repo_path)
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


def run_tests(cwd):
    result = subprocess.run(
        ["npm", "test"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    passed = result.returncode == 0
    output = (result.stdout + result.stderr).strip()
    return passed, output


# ---------------------------------------------------------------------------
# Dependency analysis
# ---------------------------------------------------------------------------

def parse_js_imports(content):
    """Extract imported file paths from a JS file."""
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
    """Resolve a relative import to an actual file in the tree."""
    base_dir = os.path.dirname(base_file)
    resolved = os.path.normpath(os.path.join(base_dir, import_path))
    candidates = [
        resolved,
        resolved + ".js",
        resolved + ".ts",
        resolved + "/index.js",
        resolved + "/index.ts",
    ]
    for c in candidates:
        if c in file_tree:
            return c
    return None


def build_dependency_graph(repo_path, file_tree):
    """Build a map of file -> files that import it (reverse deps)."""
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
    """
    Given seed files (directly changed), return all files that import them
    (i.e. could be broken by the change).
    """
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
    """Search for a pattern across all files in the repo."""
    matches = []
    for f in file_tree:
        content = read_file(repo_path, f)
        if content and re.search(pattern, content):
            matches.append(f)
    return matches


def identify_relevant_files(issue_title, issue_description, repo_path, file_tree):
    """
    Use Claude to identify relevant files, then expand with real import analysis.
    """
    file_tree_str = "\n".join(file_tree)
    prompt = f"""You are a senior developer. Given the task below and the file tree, list the files most likely to need changes.

TASK: {issue_title}
DESCRIPTION: {issue_description}

FILE TREE:
{file_tree_str}

Return ONLY a JSON array of relative file paths. Example: ["src/calculator.js", "test/calculator.test.js"]
No explanation, no markdown, just the JSON array.
"""
    response = ask_claude(prompt)
    try:
        seed_files = json.loads(response)
        seed_files = [f for f in seed_files if isinstance(f, str) and f in file_tree]
    except Exception:
        seed_files = []

    # Expand with real dependency analysis
    affected = find_affected_files(repo_path, seed_files, file_tree)

    # Also grep for any symbol names mentioned in the issue title
    words = re.findall(r'\b\w{4,}\b', issue_title)
    for word in words:
        for f in grep_repo(repo_path, rf'\b{word}\b', file_tree):
            if f not in affected:
                affected.append(f)

    return seed_files, sorted(set(affected))


# ---------------------------------------------------------------------------
# Session / state persistence
# ---------------------------------------------------------------------------

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions")


def save_session(session_id, data):
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    existing = load_session(session_id) or {}
    existing.update(data)
    with open(path, "w") as f:
        json.dump(existing, f, indent=2)
    return existing


def load_session(session_id):
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Output parsers
# ---------------------------------------------------------------------------

def parse_dev_output(output):
    changes = {}
    tests = {}

    for path, content in re.findall(r'FILE:\s*(.+?)\n```(?:\w+)?\n(.*?)```', output, re.DOTALL):
        path = path.strip()
        content = content.strip()
        if "test" in path.lower() or "spec" in path.lower():
            tests[path] = content
        else:
            changes[path] = content

    impact = ""
    m = re.search(r'## Impact Analysis\n(.*?)(?=##|\Z)', output, re.DOTALL)
    if m:
        impact = m.group(1).strip()

    summary = ""
    m = re.search(r'## Summary\n(.*?)(?=##|\Z)', output, re.DOTALL)
    if m:
        summary = m.group(1).strip()

    return changes, tests, impact, summary


def parse_review_output(output):
    verdict = "FAIL"
    m = re.search(r'## Verdict\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if m and "PASS" in m.group(1).upper():
        verdict = "PASS"

    dimensions = {}
    for dim in ["Correctness", "Security", "Performance", "Error Handling", "Test Coverage"]:
        m = re.search(rf'### {dim}\s*\n(.*?)(?=###|##|\Z)', output, re.DOTALL)
        if m:
            text = m.group(1).strip()
            status = "PASS" if "PASS" in text[:20].upper() else "FAIL" if "FAIL" in text[:20].upper() else "N/A"
            dimensions[dim] = {"status": status, "notes": text}

    return verdict, dimensions


def parse_qa_output(output):
    approved = False
    m = re.search(r'## QA Verdict\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if m and "APPROVED" in m.group(1).upper():
        approved = True

    risk = "UNKNOWN"
    m = re.search(r'## Risk Assessment\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if m:
        text = m.group(1).upper()
        if "HIGH" in text:
            risk = "HIGH"
        elif "MEDIUM" in text:
            risk = "MEDIUM"
        elif "LOW" in text:
            risk = "LOW"

    return approved, risk
