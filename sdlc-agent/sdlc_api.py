from flask import Flask, request, jsonify
import os
import re

from utils import ask_claude, get_file_tree, read_file, write_file, run_git, run_tests
from prompts import ba_prompt, pm_prompt, dev_prompt, review_prompt, qa_prompt

app = Flask(__name__)

DEFAULT_REPO_PATH = os.environ.get("REPO_PATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Stage 1: Business Analyst
# ---------------------------------------------------------------------------

@app.route("/ba-agent", methods=["POST"])
def ba_agent():
    data = request.json or {}
    requirement = data.get("requirement", "")
    repo_path = data.get("repo_path", DEFAULT_REPO_PATH)

    if not requirement:
        return jsonify({"status": "error", "message": "requirement is required"}), 400

    file_tree = "\n".join(get_file_tree(repo_path))
    brd = ask_claude(ba_prompt(requirement, file_tree))

    return jsonify({
        "status": "success",
        "stage": "ba",
        "brd": brd,
        "requirement": requirement,
        "repo_path": repo_path,
        "awaiting_approval": True,
    })


# ---------------------------------------------------------------------------
# Stage 2: Project Manager
# ---------------------------------------------------------------------------

@app.route("/pm-agent", methods=["POST"])
def pm_agent():
    data = request.json or {}
    brd = data.get("brd", "")
    repo_path = data.get("repo_path", DEFAULT_REPO_PATH)

    if not brd:
        return jsonify({"status": "error", "message": "brd is required"}), 400

    file_tree = "\n".join(get_file_tree(repo_path))
    pm_output = ask_claude(pm_prompt(brd, file_tree))

    return jsonify({
        "status": "success",
        "stage": "pm",
        "pm_output": pm_output,
        "brd": brd,
        "repo_path": repo_path,
        "awaiting_approval": True,
    })


# ---------------------------------------------------------------------------
# Stage 3: Developer
# ---------------------------------------------------------------------------

def identify_relevant_files(issue_title, issue_description, file_tree_str):
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
        import json
        files = json.loads(response)
        return [f for f in files if isinstance(f, str)]
    except Exception:
        return []


def parse_dev_output(output):
    changes = {}
    tests = {}

    file_blocks = re.findall(r'FILE:\s*(.+?)\n```(?:\w+)?\n(.*?)```', output, re.DOTALL)
    for path, content in file_blocks:
        path = path.strip()
        content = content.strip()
        if "test" in path.lower() or "spec" in path.lower():
            tests[path] = content
        else:
            changes[path] = content

    impact = ""
    impact_match = re.search(r'## Impact Analysis\n(.*?)(?=##|\Z)', output, re.DOTALL)
    if impact_match:
        impact = impact_match.group(1).strip()

    summary = ""
    summary_match = re.search(r'## Summary\n(.*?)(?=##|\Z)', output, re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()

    return changes, tests, impact, summary


@app.route("/dev-agent", methods=["POST"])
def dev_agent():
    data = request.json or {}
    issue_title = data.get("issue_title", "")
    issue_description = data.get("issue_description", "")
    repo_path = data.get("repo_path", DEFAULT_REPO_PATH)
    branch_name = data.get("branch_name", f"ai/feature-{issue_title[:30].lower().replace(' ', '-')}")

    if not issue_title or not issue_description:
        return jsonify({"status": "error", "message": "issue_title and issue_description are required"}), 400

    file_tree = get_file_tree(repo_path)
    file_tree_str = "\n".join(file_tree)

    relevant_files = identify_relevant_files(issue_title, issue_description, file_tree_str)
    file_contents = {}
    for f in relevant_files:
        content = read_file(repo_path, f)
        if content:
            file_contents[f] = content

    attempts = []
    dev_output = ask_claude(dev_prompt(issue_title, issue_description, file_contents, file_tree_str))

    for attempt in range(1, MAX_RETRIES + 1):
        changes, tests, impact, summary = parse_dev_output(dev_output)

        run_git(["checkout", "main"], cwd=repo_path)
        run_git(["pull"], cwd=repo_path)
        if attempt == 1:
            run_git(["checkout", "-b", branch_name], cwd=repo_path)
        else:
            run_git(["checkout", branch_name], cwd=repo_path)

        for path, content in {**changes, **tests}.items():
            write_file(repo_path, path, content)

        test_passed, test_output = run_tests(repo_path)
        attempts.append({
            "attempt": attempt,
            "test_passed": test_passed,
            "test_output": test_output,
        })

        if test_passed:
            break

        if attempt < MAX_RETRIES:
            retry_prompt = f"""Your previous implementation failed tests.

TASK: {issue_title}
TEST FAILURES:
{test_output}

Previous output:
{dev_output}

Fix the issues and return the corrected implementation in the same format.
"""
            dev_output = ask_claude(retry_prompt)

    for path in {**changes, **tests}.keys():
        run_git(["add", path], cwd=repo_path)

    run_git(["commit", "-m", f"feat: {issue_title}"], cwd=repo_path)
    run_git(["push", "-u", "origin", branch_name], cwd=repo_path)

    final = attempts[-1]
    return jsonify({
        "status": "success",
        "stage": "dev",
        "branch": branch_name,
        "issue_title": issue_title,
        "impact_analysis": impact,
        "summary": summary,
        "files_changed": list(changes.keys()),
        "test_files": list(tests.keys()),
        "test_passed": final["test_passed"],
        "test_output": final["test_output"],
        "attempts": len(attempts),
        "repo_path": repo_path,
        "awaiting_approval": True,
    })


# ---------------------------------------------------------------------------
# Stage 4: Peer Review
# ---------------------------------------------------------------------------

@app.route("/review-agent", methods=["POST"])
def review_agent():
    data = request.json or {}
    issue_title = data.get("issue_title", "")
    branch_name = data.get("branch", "")
    impact_analysis = data.get("impact_analysis", "")
    test_output = data.get("test_output", "")
    repo_path = data.get("repo_path", DEFAULT_REPO_PATH)

    if not branch_name:
        return jsonify({"status": "error", "message": "branch is required"}), 400

    diff = run_git(["diff", "main..." + branch_name], cwd=repo_path)
    test_files_diff = run_git(["diff", "main..." + branch_name, "--", "*test*", "*spec*"], cwd=repo_path)

    review = ask_claude(review_prompt(issue_title, diff, impact_analysis, test_files_diff))

    verdict = "PASS" if "PASS" in review.upper().split("## VERDICT")[-1][:20] else "FAIL"

    return jsonify({
        "status": "success",
        "stage": "review",
        "review": review,
        "verdict": verdict,
        "branch": branch_name,
        "issue_title": issue_title,
        "repo_path": repo_path,
        "awaiting_approval": True,
    })


# ---------------------------------------------------------------------------
# Stage 5: QA
# ---------------------------------------------------------------------------

@app.route("/qa-agent", methods=["POST"])
def qa_agent():
    data = request.json or {}
    issue_title = data.get("issue_title", "")
    test_output = data.get("test_output", "")
    review_verdict = data.get("verdict", "")
    review_summary = data.get("review", "")
    repo_path = data.get("repo_path", DEFAULT_REPO_PATH)

    if not issue_title:
        return jsonify({"status": "error", "message": "issue_title is required"}), 400

    qa = ask_claude(qa_prompt(issue_title, test_output, review_verdict, review_summary))

    approved = "APPROVED" in qa.upper().split("## QA VERDICT")[-1][:20]

    return jsonify({
        "status": "success",
        "stage": "qa",
        "qa_output": qa,
        "approved": approved,
        "issue_title": issue_title,
        "repo_path": repo_path,
    })


if __name__ == "__main__":
    app.run(port=5001)
