import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uuid
from flask import Flask, request, jsonify

from shared.session import load_session, save_session
from shared.config import get_repo_config
import agents.ba.agent as ba
import agents.sa.agent as sa
import agents.pm.agent as pm
import agents.dev.agent as dev
import agents.review.agent as review
import agents.qa.agent as qa

app = Flask(__name__)

# Fallback repo path if no repos.json entry found
DEFAULT_REPO_PATH = os.environ.get(
    "REPO_PATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _sid(data):
    """Build session_id from owner/repo/issue_number when available, else use explicit session_id."""
    if data.get("session_id"):
        return data["session_id"]
    owner = data.get("owner", "")
    repo = data.get("repo", "")
    issue = data.get("issue_number", "")
    if owner and repo and issue:
        return f"{owner}-{repo}-{issue}"
    return str(uuid.uuid4())


def _repo_config(data, session):
    """Resolve repo_path and test_command from repos.json or session fallback."""
    owner = data.get("owner") or session.get("owner", "")
    repo = data.get("repo") or session.get("repo", "")
    if owner and repo:
        cfg = get_repo_config(owner, repo)
        if cfg:
            return cfg.get("repo_path", DEFAULT_REPO_PATH), cfg.get("test_command"), cfg.get("main_branch", "main")
    repo_path = data.get("repo_path") or session.get("repo_path") or DEFAULT_REPO_PATH
    return repo_path, session.get("test_command"), "main"


@app.route("/repos", methods=["GET"])
def list_repos():
    """List all registered repos."""
    from shared.config import all_repos
    return jsonify({"status": "success", "repos": all_repos()})


@app.route("/repos", methods=["POST"])
def register_repo():
    """Register a new repo. Body: {owner, repo, repo_path, test_command, main_branch}"""
    import json
    data = request.json or {}
    owner = data.get("owner", "")
    repo = data.get("repo", "")
    if not owner or not repo:
        return jsonify({"status": "error", "message": "owner and repo are required"}), 400

    repos_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "repos.json")
    try:
        with open(repos_path) as f:
            repos = json.load(f)
    except FileNotFoundError:
        repos = {}

    key = f"{owner}/{repo}"
    repos[key] = {
        "repo_path": data.get("repo_path", ""),
        "test_command": data.get("test_command", ["npm", "test"]),
        "main_branch": data.get("main_branch", "main"),
    }
    with open(repos_path, "w") as f:
        json.dump(repos, f, indent=2)

    return jsonify({"status": "success", "registered": key, "config": repos[key]})


@app.route("/ba-agent", methods=["POST"])
def ba_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    repo_path, test_command, main_branch = _repo_config(data, session)
    try:
        result = ba.run(
            session_id=sid,
            requirement=data.get("requirement") or session.get("requirement", ""),
            repo_path=repo_path,
            clarification_answers=data.get("clarification_answers"),
            human_feedback=data.get("human_feedback"),
        )
        # Persist repo metadata so downstream agents can find it
        save_session(sid, {
            "owner": data.get("owner") or session.get("owner", ""),
            "repo": data.get("repo") or session.get("repo", ""),
            "test_command": test_command,
            "main_branch": main_branch,
        })
        return jsonify({"status": "success", "stage": "ba", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/sa-agent", methods=["POST"])
def sa_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    repo_path, _, _ = _repo_config(data, session)
    try:
        result = sa.run(
            session_id=sid,
            repo_path=repo_path,
            human_feedback=data.get("human_feedback"),
        )
        return jsonify({"status": "success", "stage": "sa", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/pm-agent", methods=["POST"])
def pm_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    repo_path, _, _ = _repo_config(data, session)
    try:
        result = pm.run(
            session_id=sid,
            repo_path=repo_path,
            brd=data.get("brd"),
            ba_answers=data.get("ba_answers"),
            human_feedback=data.get("human_feedback"),
        )
        return jsonify({"status": "success", "stage": "pm", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/dev-agent", methods=["POST"])
def dev_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    repo_path, test_command, _ = _repo_config(data, session)
    requirement = session.get("requirement", "")
    try:
        result = dev.run(
            session_id=sid,
            issue_title=data.get("issue_title") or session.get("issue_title") or requirement.split("\n")[0].strip(),
            issue_description=data.get("issue_description") or requirement,
            repo_path=repo_path,
            branch_name=data.get("branch_name"),
            redo_instructions=data.get("redo_instructions"),
            test_command=test_command,
        )
        return jsonify({"status": "success", "stage": "dev", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/review-agent", methods=["POST"])
def review_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    repo_path, _, _ = _repo_config(data, session)
    try:
        result = review.run(
            session_id=sid,
            repo_path=repo_path,
            branch_name=data.get("branch"),
            issue_title=data.get("issue_title"),
            impact_analysis=data.get("impact_analysis"),
            affected_files=data.get("affected_files"),
            human_feedback=data.get("human_feedback"),
        )
        return jsonify({"status": "success", "stage": "review", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/qa-agent", methods=["POST"])
def qa_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    try:
        result = qa.run(
            session_id=sid,
            issue_title=data.get("issue_title"),
            test_output=data.get("test_output"),
            review_verdict=data.get("verdict"),
            review_dimensions=data.get("dimensions"),
            impact_analysis=data.get("impact_analysis"),
            human_feedback=data.get("human_feedback"),
        )
        return jsonify({"status": "success", "stage": "qa", "session_id": sid, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/create-pr", methods=["POST"])
def create_pr():
    """Create a PR for an existing branch using session data."""
    from shared.utils import create_pull_request
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    repo_path, _, _ = _repo_config(data, session)
    branch_name = session.get("branch", f"ai/feature-{sid[:8]}")
    issue_title = session.get("issue_title") or session.get("requirement", "").split("\n")[0].strip()
    # Extract issue number from session_id — works for both sdlc-N and owner-repo-N formats
    issue_number = sid.split("-")[-1] if "-" in sid else None
    try:
        pr_url = create_pull_request(repo_path, branch_name, issue_title, issue_number,
                                     session.get("pr_description", ""), session.get("summary", ""))
        save_session(sid, {"pr_url": pr_url})
        return jsonify({"status": "success", "pr_url": pr_url, "branch": branch_name})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/reopen", methods=["POST"])
def reopen():
    """Reset pipeline back to BA stage."""
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    repo_path, _, _ = _repo_config(data, session)
    reason = data.get("reason", "")
    try:
        result = ba.run(
            session_id=sid,
            requirement=data.get("requirement") or session.get("requirement", ""),
            repo_path=repo_path,
            human_feedback=f"Pipeline reopened. Reason: {reason}" if reason else None,
        )
        return jsonify({"status": "success", "stage": "ba", "session_id": sid, "reopened": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/skip-qa", methods=["POST"])
def skip_qa():
    """Mark QA as approved without running the QA agent."""
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    reason = data.get("reason", "Manually approved by reviewer")
    result = {
        "qa_output": f"QA skipped by human reviewer. Reason: {reason}",
        "approved": True,
        "risk": "UNKNOWN",
        "stage_gate": "OPEN",
        "prod_gate": "BLOCKED",
        "unresolved_review_issues": [],
        "issue_title": session.get("issue_title", ""),
        "pipeline_complete": True,
        "next_stage": "stage deployment",
    }
    save_session(sid, {**result, "stage": "qa"})
    return jsonify({"status": "success", "stage": "qa", "session_id": sid, **result})


@app.route("/assign", methods=["POST"])
def assign_issues():
    """Assign all PM-created GitHub issues for this session to a GitHub username."""
    import subprocess, json as json_lib, urllib.request, urllib.error
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    assignee = data.get("assignee", "").lstrip("@")
    if not assignee:
        return jsonify({"status": "error", "message": "assignee is required"}), 400

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return jsonify({"status": "error", "message": "GITHUB_TOKEN not set"}), 500

    repo_path, _, _ = _repo_config(data, session)
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path, capture_output=True, text=True
    ).stdout.strip().replace("git@github.com:", "https://github.com/")
    parts = remote.rstrip(".git").rstrip("/").split("/")
    owner, repo = parts[-2], parts[-1]

    tasks = session.get("pm_tasks", [])
    results = []
    for task in tasks:
        issue_number = task.get("issue_number")
        if not issue_number:
            continue
        payload = json_lib.dumps({"assignees": [assignee]}).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/assignees",
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
                resp_data = json_lib.loads(resp.read())
                results.append({"issue": issue_number, "assigned": True, "url": resp_data.get("html_url", "")})
        except urllib.error.HTTPError as e:
            results.append({"issue": issue_number, "assigned": False, "error": e.read().decode()})

    return jsonify({"status": "success", "session_id": sid, "assignee": assignee, "results": results})


@app.route("/session/<path:session_id>", methods=["GET"])
def get_session(session_id):
    session = load_session(session_id)
    if not session:
        return jsonify({"status": "error", "message": "Session not found"}), 404
    return jsonify({"status": "success", "session": session})


if __name__ == "__main__":
    app.run(port=5001)
