import argparse
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
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="AI agent: fix a GitHub issue and open a PR branch")
    parser.add_argument("--issue-number", required=True)
    parser.add_argument("--issue-title", required=True)
    parser.add_argument("--issue-body", default="")
    parser.add_argument("--repo-path", default=os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--file-path", default="src/calculator.js")
    args = parser.parse_args()

    repo_path = args.repo_path
    file_path = args.file_path
    abs_file = os.path.join(repo_path, file_path)
    branch_name = f"ai/fix-issue-{args.issue_number}"

    run_git(["checkout", "main"], cwd=repo_path)
    run_git(["pull"], cwd=repo_path)
    run_git(["checkout", "-b", branch_name], cwd=repo_path)

    with open(abs_file, "r") as f:
        original = f.read()

    prompt = f"""You are a senior software engineer fixing a bug in a JavaScript file.

ISSUE TITLE: {args.issue_title}
ISSUE BODY:
{args.issue_body}

FILE: {file_path}
CURRENT CONTENT:
```javascript
{original}
```

INSTRUCTIONS:
- Identify and fix the bug described in the issue.
- Return ONLY the corrected file content, no explanations, no markdown fences.
- Preserve all existing functions and exports.
"""

    fixed = ask_claude(prompt)

    with open(abs_file, "w") as f:
        f.write(fixed)

    run_git(["add", file_path], cwd=repo_path)
    run_git(["commit", "-m", f"Fix issue #{args.issue_number}: {args.issue_title}"], cwd=repo_path)
    run_git(["push", "-u", "origin", branch_name], cwd=repo_path)

    print(f"Done. Branch: {branch_name}")


if __name__ == "__main__":
    main()
