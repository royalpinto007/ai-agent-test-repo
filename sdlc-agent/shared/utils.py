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


def run_tests(cwd, command=None):
    cmd = command or ["npm", "test"]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    passed = result.returncode == 0
    output = (result.stdout + result.stderr).strip()
    return passed, output


_IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", ".env",
    "sessions", "dist", "build", ".next", ".nuxt", "coverage",
    ".pytest_cache", ".mypy_cache", "vendor", "bower_components",
}
_IGNORE_EXTS = {
    ".lock", ".log", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".zip", ".tar",
    ".gz", ".pdf", ".min.js", ".min.css", ".map",
}
_MAX_TREE_FILES = 500


def get_file_tree(repo_path, ignore_dirs=None):
    ignore = ignore_dirs or _IGNORE_DIRS
    tree = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in ignore and not d.startswith(".")]
        for f in files:
            # skip binary/generated files
            if any(f.endswith(ext) for ext in _IGNORE_EXTS):
                continue
            rel = os.path.relpath(os.path.join(root, f), repo_path)
            tree.append(rel)
    tree = sorted(tree)
    # For very large repos, keep source files and trim the rest
    if len(tree) > _MAX_TREE_FILES:
        source_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java",
                       ".rb", ".rs", ".cs", ".cpp", ".c", ".h", ".php", ".swift"}
        source = [f for f in tree if os.path.splitext(f)[1] in source_exts]
        other = [f for f in tree if os.path.splitext(f)[1] not in source_exts]
        # Keep all source files + truncated other files
        tree = source + other[:max(0, _MAX_TREE_FILES - len(source))]
        tree = sorted(tree)
    return tree


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


def create_pull_request(repo_path, branch_name, issue_title, issue_number, pr_description="", summary=""):
    import urllib.request
    import urllib.error

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN env var not set")

    # Derive owner/repo from git remote
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path, capture_output=True, text=True
    ).stdout.strip()
    # Handle both https://github.com/owner/repo.git and git@github.com:owner/repo.git
    remote = remote.replace("git@github.com:", "https://github.com/")
    parts = remote.rstrip(".git").rstrip("/").split("/")
    owner, repo = parts[-2], parts[-1]

    body = pr_description or summary or ""
    if issue_number:
        body += f"\n\nCloses #{issue_number}"

    payload = json.dumps({
        "title": issue_title,
        "body": body.strip(),
        "base": "main",
        "head": branch_name,
    }).encode()

    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        data=payload,
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            return data["html_url"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API error {e.code}: {e.read().decode()}")


def check_pr_file_overlap(repo_path, current_branch, token):
    """
    Fetch all open PRs for this repo and return any that touch the same files
    as current_branch. Returns a list of dicts: {number, title, url, overlap}.
    """
    import urllib.request
    import urllib.error

    if not token:
        return []

    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path, capture_output=True, text=True
    ).stdout.strip().replace("git@github.com:", "https://github.com/")
    parts = remote.rstrip(".git").rstrip("/").split("/")
    owner, repo = parts[-2], parts[-1]

    # Files changed in the current branch vs main
    try:
        diff_output = subprocess.run(
            ["git", "diff", "--name-only", f"main...{current_branch}"],
            cwd=repo_path, capture_output=True, text=True
        ).stdout.strip()
        current_files = set(f for f in diff_output.splitlines() if f)
    except Exception:
        return []

    if not current_files:
        return []

    # Fetch open PRs
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/pulls?state=open&per_page=50",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }
    )
    try:
        with urllib.request.urlopen(req) as resp:
            open_prs = json.loads(resp.read())
    except Exception:
        return []

    conflicts = []
    for pr in open_prs:
        if pr.get("head", {}).get("ref") == current_branch:
            continue  # skip self

        # Fetch files for this PR
        pr_number = pr["number"]
        files_req = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files?per_page=100",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
            }
        )
        try:
            with urllib.request.urlopen(files_req) as resp:
                pr_files = {f["filename"] for f in json.loads(resp.read())}
        except Exception:
            continue

        overlap = current_files & pr_files
        if overlap:
            conflicts.append({
                "number": pr_number,
                "title": pr.get("title", ""),
                "url": pr.get("html_url", ""),
                "overlap": sorted(overlap),
            })

    return conflicts


def create_github_issue(owner, repo, token, title, body, labels=None, assignees=None):
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "title": title,
        "body": body,
        "labels": labels or [],
        "assignees": assignees or [],
    }).encode()

    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/issues",
        data=payload,
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            return {"number": data["number"], "url": data["html_url"], "title": data["title"]}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API error {e.code}: {e.read().decode()}")


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
