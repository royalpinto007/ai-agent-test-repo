from flask import Flask, request, jsonify
import subprocess
import os

app = Flask(__name__)

DEFAULT_REPO_PATH = os.environ.get("REPO_PATH", os.path.dirname(os.path.abspath(__file__)))
MAX_RETRIES = 3


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
    # Strip markdown code fences if Claude wrapped the output
    if output.startswith("```"):
        lines = output.splitlines()
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # remove closing fence
        output = "\n".join(lines)
    return output


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
- Return ONLY the corrected file content. No explanations, no markdown fences, no commentary, no preamble.
- Your entire response must be valid JavaScript that can be written directly to a .js file.
- Preserve all existing functions, exports, and code structure exactly.
"""
    return ask_claude(prompt)


def fix_with_feedback(issue_title, issue_body, file_path, current_content, previous_fix, test_output, human_feedback=None):
    feedback_section = f"HUMAN FEEDBACK:\n{human_feedback}\n" if human_feedback else ""
    prompt = f"""You are a senior software engineer fixing a bug in a JavaScript file.

ISSUE TITLE: {issue_title}
ISSUE BODY:
{issue_body}

YOUR PREVIOUS ATTEMPT FAILED.

PREVIOUS FIX (what you tried):
```javascript
{previous_fix}
```

TEST FAILURES:
{test_output}

{feedback_section}CURRENT FILE CONTENT:
```javascript
{current_content}
```

INSTRUCTIONS:
- Analyze why the previous fix failed based on the test output and feedback.
- Fix ONLY the bug described in the issue. Do not refactor, rename, or improve unrelated code.
- Think through all edge cases carefully before writing the fix.
- Do not add new functions, remove existing ones, or change function signatures.
- Return ONLY the corrected file content. No explanations, no markdown fences, no commentary, no preamble.
- Your entire response must be valid JavaScript that can be written directly to a .js file.
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

    attempts = []
    fixed = fix_issue(issue_title, issue_body, file_path, original)

    for attempt in range(1, MAX_RETRIES + 1):
        with open(abs_file, "w") as f:
            f.write(fixed)

        test_passed, test_output = run_tests(repo_path)
        attempts.append({
            "attempt": attempt,
            "fix": fixed,
            "test_passed": test_passed,
            "test_output": test_output,
        })

        if test_passed:
            break

        if attempt < MAX_RETRIES:
            fixed = fix_with_feedback(issue_title, issue_body, file_path, fixed, fixed, test_output)

    review_output = review_fix(issue_title, issue_body, original, fixed, file_path)

    run_git(["add", file_path], cwd=repo_path)
    run_git(["commit", "-m", f"Fix issue #{issue_number}: {issue_title} (attempts: {len(attempts)})"], cwd=repo_path)
    run_git(["push", "-u", "origin", branch_name], cwd=repo_path)

    final = attempts[-1]
    return {
        "repo": repo_name,
        "repo_path": repo_path,
        "branch": branch_name,
        "review": review_output,
        "test_passed": final["test_passed"],
        "test_output": final["test_output"],
        "attempts": len(attempts),
        "attempt_log": attempts,
    }


def revise_repo(repo_path, file_path, issue_number, issue_title, issue_body, human_feedback):
    branch_name = f"ai/fix-issue-{issue_number}"
    abs_file = os.path.join(repo_path, file_path)
    repo_name = os.path.basename(repo_path.rstrip("/"))

    run_git(["checkout", branch_name], cwd=repo_path)

    with open(abs_file, "r") as f:
        current_content = f.read()

    attempts = []
    fixed = fix_with_feedback(issue_title, issue_body, file_path, current_content, current_content, "", human_feedback)

    for attempt in range(1, MAX_RETRIES + 1):
        with open(abs_file, "w") as f:
            f.write(fixed)

        test_passed, test_output = run_tests(repo_path)
        attempts.append({
            "attempt": attempt,
            "fix": fixed,
            "test_passed": test_passed,
            "test_output": test_output,
        })

        if test_passed:
            break

        if attempt < MAX_RETRIES:
            fixed = fix_with_feedback(issue_title, issue_body, file_path, fixed, fixed, test_output, human_feedback)

    review_output = review_fix(issue_title, issue_body, current_content, fixed, file_path)

    run_git(["add", file_path], cwd=repo_path)
    run_git(["commit", "-m", f"Revise fix for issue #{issue_number} based on feedback"], cwd=repo_path)
    run_git(["push", "--force-with-lease", "origin", branch_name], cwd=repo_path)

    final = attempts[-1]
    return {
        "repo": repo_name,
        "repo_path": repo_path,
        "branch": branch_name,
        "review": review_output,
        "test_passed": final["test_passed"],
        "test_output": final["test_output"],
        "attempts": len(attempts),
    }


@app.route("/run-agent", methods=["POST"])
def run_agent():
    data = request.json or {}

    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title", "")
    issue_body = data.get("issue_body", "")
    file_path = data.get("file_path", "src/calculator.js")

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


@app.route("/revise-agent", methods=["POST"])
def revise_agent():
    data = request.json or {}

    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title", "")
    issue_body = data.get("issue_body", "")
    human_feedback = data.get("human_feedback", "")
    file_path = data.get("file_path", "src/calculator.js")

    repo_paths = data.get("repo_paths")
    if not repo_paths:
        single = data.get("repo_path", DEFAULT_REPO_PATH)
        repo_paths = [single]

    if not human_feedback:
        return jsonify({"status": "error", "message": "human_feedback is required"}), 400

    # If no issue_number provided, find it from the existing ai/fix-issue-* branch
    if not issue_number:
        repo_path = repo_paths[0]
        branches = run_git(["branch", "-r"], cwd=repo_path)
        for line in branches.splitlines():
            branch = line.strip().replace("origin/", "")
            if branch.startswith("ai/fix-issue-"):
                issue_number = branch.replace("ai/fix-issue-", "")
                break

    if not issue_number:
        return jsonify({"status": "error", "message": "Could not determine issue_number"}), 400

    results = []
    errors = []

    for repo_path in repo_paths:
        try:
            result = revise_repo(repo_path, file_path, issue_number, issue_title, issue_body, human_feedback)
            results.append(result)
        except Exception as e:
            errors.append({"repo_path": repo_path, "error": str(e)})

    return jsonify({
        "status": "success" if results else "error",
        "issue_number": issue_number,
        "issue_title": issue_title,
        "human_feedback": human_feedback,
        "results": results,
        "errors": errors,
    })


if __name__ == "__main__":
    app.run(port=5000)
