import subprocess
import os


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
        ignore_dirs = {".git", "node_modules", "venv", "__pycache__", ".env"}
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
