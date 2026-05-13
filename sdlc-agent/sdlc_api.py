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
import agents.security.agent as security
import agents.review.agent as review
import agents.qa.agent as qa
import agents.deploy.agent as deploy

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
    """Resolve repo_path and test_command from repos.json or session fallback.
    When a target_repo is set in the session (requirements-repo flow), use it
    for dev/security/review stages instead of the issue repo."""
    owner = data.get("owner") or session.get("owner", "")
    repo = data.get("repo") or session.get("repo", "")

    # If PM identified a specific code repo, use it for non-PM stages
    target = session.get("target_repo")
    if target and isinstance(target, dict) and target.get("repo_path"):
        slug = target.get("slug", "")
        if slug and "/" in slug:
            t_owner, t_repo = slug.split("/", 1)
            cfg = get_repo_config(t_owner, t_repo)
            if cfg:
                return cfg.get("repo_path", target["repo_path"]), cfg.get("test_command"), cfg.get("main_branch", "main")
        return target["repo_path"], target.get("test_command"), target.get("main_branch", "main")

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
        # Post BRD as a GitHub comment if we have owner/repo/issue_number
        owner = data.get("owner") or session.get("owner", "")
        repo = data.get("repo") or session.get("repo", "")
        issue_number = data.get("issue_number") or session.get("issue_number")
        token = os.environ.get("GITHUB_TOKEN", "")
        if owner and repo and issue_number and token:
            from shared.utils import post_github_comment
            brd = result.get("brd", "")
            needs_clarification = result.get("needs_clarification", False)
            comment = (
                f"## 🤖 BA Agent — Business Requirements Document\n\n"
                f"**Session:** `{sid}`\n"
                f"**Next step:** Review the BRD below, then comment `approve` to proceed to Solution Architect.\n\n"
                f"---\n\n{brd}\n\n---\n\n"
                f"*Needs clarification: {needs_clarification}*"
            )
            post_github_comment(owner, repo, issue_number, comment, token)
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
    # PM always runs against the issue repo (not target_repo) — it needs the requirements context
    owner = data.get("owner") or session.get("owner", "")
    repo_name = data.get("repo") or session.get("repo", "")
    cfg = get_repo_config(owner, repo_name) if owner and repo_name else {}
    repo_path = (cfg or {}).get("repo_path") or session.get("repo_path") or DEFAULT_REPO_PATH
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
    repo_path, test_command, main_branch = _repo_config(data, session)
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
            main_branch=main_branch,
        )
        return jsonify({"status": "success", "stage": "dev", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/security-agent", methods=["POST"])
def security_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    repo_path, _, main_branch = _repo_config(data, session)
    try:
        result = security.run(
            session_id=sid,
            repo_path=repo_path,
            branch_name=data.get("branch") or session.get("branch"),
            issue_title=data.get("issue_title"),
            main_branch=main_branch,
        )
        return jsonify({"status": "success", "stage": "security", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/review-agent", methods=["POST"])
def review_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    repo_path, _, main_branch = _repo_config(data, session)
    try:
        result = review.run(
            session_id=sid,
            repo_path=repo_path,
            branch_name=data.get("branch"),
            issue_title=data.get("issue_title"),
            impact_analysis=data.get("impact_analysis"),
            affected_files=data.get("affected_files"),
            human_feedback=data.get("human_feedback"),
            main_branch=main_branch,
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


@app.route("/deploy-agent", methods=["POST"])
def deploy_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    repo_path, _, _ = _repo_config(data, session)
    env = data.get("env", "stage")
    try:
        result = deploy.run(session_id=sid, env=env, repo_path=repo_path)
        return jsonify({"status": "success", "stage": f"deploy-{env}", "session_id": sid, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/metrics", methods=["GET"])
def metrics():
    import glob, time, json as _json
    sessions_dir = os.path.join(os.path.dirname(__file__), "sessions")
    by_stage = {}
    retry_counts = []
    review_verdicts = {"PASS": 0, "FAIL": 0}
    cycle_times = []

    for path in glob.glob(f"{sessions_dir}/*.json"):
        try:
            with open(path) as f:
                s = _json.load(f)
            stage = s.get("stage", "unknown")
            by_stage[stage] = by_stage.get(stage, 0) + 1
            if "attempts" in s:
                retry_counts.append(s["attempts"])
            if s.get("review_verdict") in review_verdicts:
                review_verdicts[s["review_verdict"]] += 1
        except Exception:
            pass

    total = sum(by_stage.values())
    avg_retries = round(sum(retry_counts) / len(retry_counts), 2) if retry_counts else 0

    return jsonify({
        "status": "success",
        "total_sessions": total,
        "by_stage": by_stage,
        "dev_avg_retries": avg_retries,
        "review_pass_rate": round(review_verdicts["PASS"] / max(sum(review_verdicts.values()), 1) * 100),
        "review_verdicts": review_verdicts,
    })


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


@app.route("/status", methods=["POST"])
def pipeline_status():
    """Return a human-readable status summary for a session (used by the /status comment command)."""
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid)
    if not session:
        return jsonify({"status": "error", "message": "Session not found"}), 404

    stage = session.get("stage", "unknown")
    stage_emoji = {
        "ba": "📋", "sa": "🏗️", "pm": "📊", "dev": "💻", "review": "🔍", "qa": "✅"
    }.get(stage, "❓")

    lines = [f"**Pipeline Status — `{sid}`**", "", f"**Stage:** {stage_emoji} {stage.upper()}"]

    if stage == "ba":
        lines.append(f"**BRD ready:** {'Yes' if session.get('brd_draft') else 'No'}")
    elif stage == "sa":
        lines.append(f"**SDD ready:** {'Yes' if session.get('sdd') else 'No'}")
    elif stage == "pm":
        lines.append(f"**Dev ready:** {'Yes' if session.get('pm_dev_ready') else 'No'}")
        tasks = session.get("pm_tasks", [])
        lines.append(f"**Issues created:** {len(tasks)}")
        cross = session.get("cross_repo_issues", [])
        if cross:
            lines.append(f"**Cross-repo issues:** {len(cross)}")
    elif stage == "dev":
        lines.append(f"**Branch:** `{session.get('branch', 'n/a')}`")
        lines.append(f"**Tests:** {'✅ Passing' if session.get('test_passed') else '❌ Failing'}")
        lines.append(f"**Attempts:** {session.get('attempts', '?')}")
        pr_url = session.get("pr_url")
        pr_error = session.get("pr_error")
        if pr_url:
            lines.append(f"**PR:** {pr_url}")
        elif pr_error:
            lines.append(f"**PR:** ❌ Failed — {pr_error}")
    elif stage == "review":
        verdict = session.get("review_verdict", "?")
        lines.append(f"**Verdict:** {'✅ PASS' if verdict == 'PASS' else '❌ FAIL'}")
        blocking = session.get("review_blocking_issues", [])
        if blocking:
            lines.append(f"**Blocking issues:** {len(blocking)}")
    elif stage == "qa":
        lines.append(f"**Approved:** {'Yes' if session.get('approved') else 'No'}")
        lines.append(f"**Stage gate:** {session.get('stage_gate', '?')}")
        lines.append(f"**Prod gate:** {session.get('prod_gate', '?')}")

    lines += ["", f"**Next step:** `approve` to advance, `revise: <feedback>` to update, or `reopen: <reason>` to restart."]

    return jsonify({"status": "success", "session_id": sid, "stage": stage, "summary": "\n".join(lines)})


@app.route("/set-milestone", methods=["POST"])
def set_milestone_endpoint():
    data = request.json or {}
    owner = data.get("owner", "")
    repo = data.get("repo", "")
    issue_number = data.get("issue_number")
    milestone_title = data.get("milestone_title", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not all([owner, repo, issue_number, milestone_title, token]):
        return jsonify({"status": "error", "message": "missing required fields"}), 400
    from shared.utils import set_issue_milestone
    ok = set_issue_milestone(owner, repo, issue_number, milestone_title, token)
    return jsonify({"status": "success" if ok else "error", "milestone": milestone_title})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
