from flask import Flask, request, jsonify
import subprocess
import os

app = Flask(__name__)

REPO_PATH = os.environ.get("REPO_PATH", os.path.dirname(os.path.abspath(__file__)))


def run_git(args, cwd):
    result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def ask_claude(prompt):
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def build_prompt(issue_title, issue_body, file_path, file_content):
    return f"""You are a senior software engineer fixing a bug in a JavaScript file.

ISSUE TITLE: {issue_title}
ISSUE BODY:
{issue_body}

FILE: {file_path}
CURRENT CONTENT:
```javascript
{file_content}
```

INSTRUCTIONS:
- Identify and fix the bug described in the issue.
- Return ONLY the corrected file content, no explanations, no markdown fences.
- Preserve all existing functions and exports.
"""


@app.route("/run-agent", methods=["POST"])
def run_agent():
    data = request.json or {}

    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title", "")
    issue_body = data.get("issue_body", "")
    repo_path = data.get("repo_path", REPO_PATH)
    file_path = data.get("file_path", "src/calculator.js")

    if not issue_number:
        return jsonify({"status": "error", "message": "issue_number is required"}), 400

    branch_name = f"ai/fix-issue-{issue_number}"
    abs_file = os.path.join(repo_path, file_path)

    try:
        run_git(["checkout", "main"], cwd=repo_path)
        run_git(["pull"], cwd=repo_path)
        run_git(["checkout", "-b", branch_name], cwd=repo_path)

        with open(abs_file, "r") as f:
            original = f.read()

        prompt = build_prompt(issue_title, issue_body, file_path, original)
        fixed = ask_claude(prompt)

        with open(abs_file, "w") as f:
            f.write(fixed)

        run_git(["add", file_path], cwd=repo_path)
        run_git(["commit", "-m", f"Fix issue #{issue_number}: {issue_title}"], cwd=repo_path)
        run_git(["push", "-u", "origin", branch_name], cwd=repo_path)

        return jsonify({
            "status": "success",
            "branch": branch_name,
            "approved": True,
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "approved": False,
        }), 500


if __name__ == "__main__":
    app.run(port=5000)
