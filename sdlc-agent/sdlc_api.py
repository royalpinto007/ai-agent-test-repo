from flask import Flask, request, jsonify
import os
import uuid

from utils import (
    ask_claude, get_file_tree, read_file, write_file, run_git, run_tests,
    identify_relevant_files, find_affected_files,
    save_session, load_session,
    parse_dev_output, parse_review_output, parse_qa_output,
)
from prompts import (
    ba_initial_prompt, ba_followup_prompt,
    pm_prompt,
    dev_prompt, dev_retry_prompt,
    review_prompt,
    qa_prompt,
)

app = Flask(__name__)

DEFAULT_REPO_PATH = os.environ.get(
    "REPO_PATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session_id(data):
    sid = data.get("session_id") or str(uuid.uuid4())
    return sid


def _repo_path(data):
    return data.get("repo_path", DEFAULT_REPO_PATH)


# ---------------------------------------------------------------------------
# Stage 1: Business Analyst
# ---------------------------------------------------------------------------

@app.route("/ba-agent", methods=["POST"])
def ba_agent():
    """
    First call:  { requirement, repo_path }
                 → returns BRD draft + clarification questions
                 → awaiting_approval: true if questions exist

    Follow-up:   { session_id, clarification_answers }
                 → refines BRD with answers, returns final BRD
    """
    data = request.json or {}
    session_id = _session_id(data)
    repo_path = _repo_path(data)

    session = load_session(session_id) or {}

    clarification_answers = data.get("clarification_answers", "")
    requirement = data.get("requirement") or session.get("requirement", "")

    if not requirement:
        return jsonify({"status": "error", "message": "requirement is required"}), 400

    file_tree_str = "\n".join(get_file_tree(repo_path))

    if clarification_answers and session.get("brd_draft"):
        # Refine BRD with answers
        brd = ask_claude(ba_followup_prompt(requirement, session["brd_draft"], clarification_answers))
        needs_clarification = "none" not in brd.lower().split("## clarification questions")[-1][:50].lower()
    else:
        # Initial BRD
        brd = ask_claude(ba_initial_prompt(requirement, file_tree_str))
        needs_clarification = "none" not in brd.lower().split("## clarification questions")[-1][:50].lower()

    session_data = save_session(session_id, {
        "requirement": requirement,
        "repo_path": repo_path,
        "brd_draft": brd,
        "stage": "ba",
    })

    return jsonify({
        "status": "success",
        "stage": "ba",
        "session_id": session_id,
        "brd": brd,
        "needs_clarification": needs_clarification,
        "awaiting_approval": True,
        "next_stage": "ba (answer questions)" if needs_clarification else "pm",
    })


# ---------------------------------------------------------------------------
# Stage 2: Project Manager
# ---------------------------------------------------------------------------

@app.route("/pm-agent", methods=["POST"])
def pm_agent():
    """
    { session_id }  — reads BRD from session
    OR
    { brd, repo_path }  — explicit BRD
    """
    data = request.json or {}
    session_id = _session_id(data)
    repo_path = _repo_path(data)

    session = load_session(session_id) or {}
    brd = data.get("brd") or session.get("brd_draft", "")
    repo_path = repo_path or session.get("repo_path", DEFAULT_REPO_PATH)

    if not brd:
        return jsonify({"status": "error", "message": "brd is required (pass session_id or brd)"}), 400

    file_tree_str = "\n".join(get_file_tree(repo_path))
    pm_output = ask_claude(pm_prompt(brd, file_tree_str))

    save_session(session_id, {
        "pm_output": pm_output,
        "stage": "pm",
        "repo_path": repo_path,
    })

    return jsonify({
        "status": "success",
        "stage": "pm",
        "session_id": session_id,
        "pm_output": pm_output,
        "awaiting_approval": True,
        "next_stage": "dev",
    })


# ---------------------------------------------------------------------------
# Stage 3: Developer
# ---------------------------------------------------------------------------

@app.route("/dev-agent", methods=["POST"])
def dev_agent():
    """
    { session_id, issue_title, issue_description }
    OR
    { issue_title, issue_description, repo_path }
    """
    data = request.json or {}
    session_id = _session_id(data)

    session = load_session(session_id) or {}
    repo_path = data.get("repo_path") or session.get("repo_path", DEFAULT_REPO_PATH)
    issue_title = data.get("issue_title", "")
    issue_description = data.get("issue_description", "")
    branch_name = data.get("branch_name") or f"ai/feature-{session_id[:8]}"

    if not issue_title or not issue_description:
        return jsonify({"status": "error", "message": "issue_title and issue_description are required"}), 400

    file_tree = get_file_tree(repo_path)
    file_tree_str = "\n".join(file_tree)

    seed_files, affected_files = identify_relevant_files(issue_title, issue_description, repo_path, file_tree)

    # Read contents of seed files (files to change) + affected (files to understand)
    file_contents = {}
    for f in set(seed_files + affected_files):
        content = read_file(repo_path, f)
        if content:
            file_contents[f] = content

    # Dev loop with retry on test failure
    attempts = []
    dev_output = ask_claude(dev_prompt(issue_title, issue_description, file_contents, affected_files, file_tree_str))

    for attempt in range(1, MAX_RETRIES + 1):
        changes, tests, impact, summary = parse_dev_output(dev_output)

        # Set up branch
        try:
            run_git(["checkout", "main"], cwd=repo_path)
            run_git(["pull"], cwd=repo_path)
            if attempt == 1:
                run_git(["checkout", "-b", branch_name], cwd=repo_path)
            else:
                run_git(["checkout", branch_name], cwd=repo_path)
        except RuntimeError:
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
            dev_output = ask_claude(dev_retry_prompt(issue_title, dev_output, test_output, attempt))

    # Commit everything
    all_changed = list({**changes, **tests}.keys())
    for path in all_changed:
        run_git(["add", path], cwd=repo_path)

    final = attempts[-1]
    commit_msg = f"feat: {issue_title} (attempts: {len(attempts)}, tests: {'pass' if final['test_passed'] else 'fail'})"
    run_git(["commit", "-m", commit_msg], cwd=repo_path)
    run_git(["push", "-u", "origin", branch_name], cwd=repo_path)

    save_session(session_id, {
        "branch": branch_name,
        "issue_title": issue_title,
        "issue_description": issue_description,
        "impact_analysis": impact,
        "dev_summary": summary,
        "files_changed": list(changes.keys()),
        "test_files": list(tests.keys()),
        "affected_files": affected_files,
        "test_passed": final["test_passed"],
        "test_output": final["test_output"],
        "dev_attempts": len(attempts),
        "stage": "dev",
    })

    return jsonify({
        "status": "success",
        "stage": "dev",
        "session_id": session_id,
        "branch": branch_name,
        "issue_title": issue_title,
        "impact_analysis": impact,
        "summary": summary,
        "files_changed": list(changes.keys()),
        "affected_files": affected_files,
        "test_passed": final["test_passed"],
        "test_output": final["test_output"],
        "attempts": len(attempts),
        "awaiting_approval": True,
        "next_stage": "review",
    })


# ---------------------------------------------------------------------------
# Stage 4: Peer Review
# ---------------------------------------------------------------------------

@app.route("/review-agent", methods=["POST"])
def review_agent():
    """
    { session_id }  — reads branch, impact, affected files from session
    OR explicit fields
    """
    data = request.json or {}
    session_id = _session_id(data)

    session = load_session(session_id) or {}
    repo_path = data.get("repo_path") or session.get("repo_path", DEFAULT_REPO_PATH)
    branch_name = data.get("branch") or session.get("branch", "")
    issue_title = data.get("issue_title") or session.get("issue_title", "")
    impact_analysis = data.get("impact_analysis") or session.get("impact_analysis", "")
    affected_files = data.get("affected_files") or session.get("affected_files", [])

    if not branch_name:
        return jsonify({"status": "error", "message": "branch is required (pass session_id or branch)"}), 400

    diff = run_git(["diff", f"main...{branch_name}"], cwd=repo_path)
    test_diff = run_git(["diff", f"main...{branch_name}", "--", "*test*", "*spec*"], cwd=repo_path)

    review = ask_claude(review_prompt(issue_title, diff, impact_analysis, test_diff, affected_files))
    verdict, dimensions = parse_review_output(review)

    save_session(session_id, {
        "review": review,
        "review_verdict": verdict,
        "review_dimensions": dimensions,
        "stage": "review",
    })

    return jsonify({
        "status": "success",
        "stage": "review",
        "session_id": session_id,
        "review": review,
        "verdict": verdict,
        "dimensions": dimensions,
        "branch": branch_name,
        "issue_title": issue_title,
        "awaiting_approval": True,
        "next_stage": "qa",
    })


# ---------------------------------------------------------------------------
# Stage 5: QA
# ---------------------------------------------------------------------------

@app.route("/qa-agent", methods=["POST"])
def qa_agent():
    """
    { session_id }  — reads all prior stage data from session
    OR explicit fields
    """
    data = request.json or {}
    session_id = _session_id(data)

    session = load_session(session_id) or {}
    repo_path = data.get("repo_path") or session.get("repo_path", DEFAULT_REPO_PATH)
    issue_title = data.get("issue_title") or session.get("issue_title", "")
    test_output = data.get("test_output") or session.get("test_output", "")
    review_verdict = data.get("verdict") or session.get("review_verdict", "")
    review_dimensions = data.get("dimensions") or session.get("review_dimensions", {})
    impact_analysis = data.get("impact_analysis") or session.get("impact_analysis", "")
    review_text = data.get("review") or session.get("review", "")

    if not issue_title:
        return jsonify({"status": "error", "message": "issue_title is required (pass session_id or issue_title)"}), 400

    qa = ask_claude(qa_prompt(issue_title, test_output, review_verdict, review_dimensions, impact_analysis))
    approved, risk = parse_qa_output(qa)

    save_session(session_id, {
        "qa_output": qa,
        "qa_approved": approved,
        "qa_risk": risk,
        "stage": "qa",
    })

    return jsonify({
        "status": "success",
        "stage": "qa",
        "session_id": session_id,
        "qa_output": qa,
        "approved": approved,
        "risk": risk,
        "issue_title": issue_title,
        "pipeline_complete": True,
    })


# ---------------------------------------------------------------------------
# Session status
# ---------------------------------------------------------------------------

@app.route("/session/<session_id>", methods=["GET"])
def get_session(session_id):
    session = load_session(session_id)
    if not session:
        return jsonify({"status": "error", "message": "Session not found"}), 404
    return jsonify({"status": "success", "session": session})


if __name__ == "__main__":
    app.run(port=5001)
