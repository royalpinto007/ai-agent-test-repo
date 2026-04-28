from flask import Flask, request, jsonify
import subprocess
import os

app = Flask(__name__)

DEFAULT_REPO_PATH = os.environ.get("REPO_PATH", os.path.dirname(os.path.abspath(__file__)))


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


def fix_issue(issue_title, issue_body, file_path, file_content):
    prompt = f"""You are a senior software engineer fixing a bug in a JavaScript file.

ISSUE TITLE: {issue_title}
ISSUE BODY:
{issue_body}

FILE: {file_path}
CURRENT CONTENT:
```javascript
{file_content}
```

INSTRUCTIONS:
- Identify and fix ONLY the bug described in the issue. Do not refactor, rename, or improve unrelated code.
- Think through edge cases before writing the fix (e.g. boundary values, zero, negative numbers, special inputs).
- Do not add new functions, remove existing ones, or change function signatures.
- Return ONLY the corrected file content, no explanations, no markdown fences.
- Preserve all existing functions, exports, and code structure exactly.
"""
    return ask_claude(prompt)


def review_fix(issue_title, issue_body, original, fixed, file_path):
    prompt = f"""You are a senior software engineer reviewing a bug fix.

ISSUE: {issue_title}
{issue_body}

ORIGINAL ({file_path}):
```javascript
{original}
```

FIXED:
```javascript
{fixed}
```

Review the fix. Reply in this exact format:
VERDICT: PASS or FAIL
SUMMARY: one sentence describing what was changed
NOTES: any concerns, edge cases, or improvements (or "None" if clean)
"""
    return ask_claude(prompt)


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


def process_repo(repo_path, file_path, issue_number, issue_title, issue_body):
    branch_name = f"ai/fix-issue-{issue_number}"
    abs_file = os.path.join(repo_path, file_path)
    repo_name = os.path.basename(repo_path.rstrip("/"))

    run_git(["checkout", "main"], cwd=repo_path)
    run_git(["pull"], cwd=repo_path)
    run_git(["checkout", "-b", branch_name], cwd=repo_path)

    with open(abs_file, "r") as f:
        original = f.read()

    fixed = fix_issue(issue_title, issue_body, file_path, original)

    with open(abs_file, "w") as f:
        f.write(fixed)

    review_output = review_fix(issue_title, issue_body, original, fixed, file_path)
    test_passed, test_output = run_tests(repo_path)

    run_git(["add", file_path], cwd=repo_path)
    run_git(["commit", "-m", f"Fix issue #{issue_number}: {issue_title}"], cwd=repo_path)
    run_git(["push", "-u", "origin", branch_name], cwd=repo_path)

    return {
        "repo": repo_name,
        "repo_path": repo_path,
        "branch": branch_name,
        "review": review_output,
        "test_passed": test_passed,
        "test_output": test_output,
    }


@app.route("/run-agent", methods=["POST"])
def run_agent():
    data = request.json or {}

    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title", "")
    issue_body = data.get("issue_body", "")
    file_path = data.get("file_path", "src/calculator.js")

    # Accept either a list of repo_paths or a single repo_path
    repo_paths = data.get("repo_paths")
    if not repo_paths:
        single = data.get("repo_path", DEFAULT_REPO_PATH)
        repo_paths = [single]

    if not issue_number:
        return jsonify({"status": "error", "message": "issue_number is required"}), 400

    results = []
    errors = []

    for repo_path in repo_paths:
        try:
            result = process_repo(repo_path, file_path, issue_number, issue_title, issue_body)
            results.append(result)
        except Exception as e:
            errors.append({"repo_path": repo_path, "error": str(e)})

    return jsonify({
        "status": "success" if results else "error",
        "issue_number": issue_number,
        "issue_title": issue_title,
        "results": results,
        "errors": errors,
    })


if __name__ == "__main__":
    app.run(port=5000)
