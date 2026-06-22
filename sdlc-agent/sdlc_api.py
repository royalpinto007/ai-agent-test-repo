import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uuid
from flask import Flask, request, jsonify

from shared.session import load_session, save_session
from shared.config import get_repo_config
from shared.claude import ClaudeUsageLimitError
import agents.ba.agent as ba
import agents.sa.agent as sa
import agents.pm.agent as pm
import agents.dev.agent as dev
import agents.security.agent as security
import agents.review.agent as review
import agents.qa.agent as qa
import agents.deploy.agent as deploy

app = Flask(__name__)


@app.before_request
def _simulate_usage_limit():
    """Test hook for the auto-resume loop — OFF unless explicitly enabled.

    Set SDLC_SIMULATE_LIMIT_STAGE to a stage name (e.g. "dev", "review", or
    "any") and the matching agent endpoint raises a usage-limit error *once per
    session+stage*, exactly as a real exhausted limit would: the endpoint returns
    200 rate_limited, the issue gets the "will resume automatically" comment, and
    n8n Waits then re-calls the step. The second call (after the Wait) sails
    through, so the pipeline continues — letting you watch the whole loop without
    burning a real Claude limit. SDLC_SIMULATE_LIMIT_SECONDS controls the wait
    (default 120s so the test resumes in ~2 min instead of hours).
    """
    want = os.environ.get("SDLC_SIMULATE_LIMIT_STAGE", "").strip().lower()
    if not want:
        return
    path = (request.path or "").lstrip("/")
    if not path.endswith("-agent"):
        return
    stage = path.replace("-agent", "")
    if want not in ("any", "all", stage):
        return
    data = request.get_json(silent=True) or {}
    marker = os.path.join(
        "/tmp", "sdlc-sim-limit-" + (str(_sid(data)) or "nosid").replace("/", "_") + "-" + stage
    )
    if os.path.exists(marker):
        return  # already fired once for this session+stage — let it through now
    try:
        open(marker, "w").close()
    except OSError:
        pass
    secs = int(os.environ.get("SDLC_SIMULATE_LIMIT_SECONDS", "120") or "120")
    raise ClaudeUsageLimitError(secs, raw_stderr="[simulated usage limit]")


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


def _agent_failure(e):
    """Standard error response for an agent endpoint.

    Claude usage-limit errors are re-raised so the app-level errorhandler can post
    a clear "resuming after the reset" comment and return a 200 rate_limited body
    (which n8n's Wait/retry path keys off of); everything else becomes a generic 500.
    """
    if isinstance(e, ClaudeUsageLimitError):
        raise e
    # Post the failure to the issue so a crashed stage is visible, instead of the
    # milestone silently sitting at "… Working" with no comment (which reads as a
    # hang). Best-effort: never let comment-posting mask the original error.
    try:
        data = request.get_json(silent=True) or {}
        session = load_session(_sid(data)) or {}
        owner = data.get("owner") or session.get("owner", "")
        repo = data.get("repo") or session.get("repo", "")
        issue_number = data.get("issue_number") or session.get("issue_number")
        token = os.environ.get("GITHUB_TOKEN", "")
        stage = (request.path or "").lstrip("/").replace("-agent", "").replace("-", " ").upper() or "A"
        if owner and repo and issue_number and token:
            from shared.utils import post_github_comment
            body = (f"❌ **{stage} stage failed.**\n\n"
                    f"The pipeline hit an error and stopped here:\n\n```\n{str(e)[:1500]}\n```\n\n"
                    f"_Fix the cause, then re-trigger this stage (`approve`/`redo-dev:`/`reopen:`)._")
            post_github_comment(owner, repo, issue_number, body, token)
    except Exception:
        app.logger.exception("failed to post failure comment")
    return jsonify({"status": "error", "message": str(e)}), 500


@app.errorhandler(ClaudeUsageLimitError)
def _handle_usage_limit(e):
    """When Claude's usage limit is exhausted, post a clear comment on the issue so
    it's obvious what happened and when to retry — instead of a cryptic 500."""
    data = request.get_json(silent=True) or {}
    session = load_session(_sid(data)) or {}
    owner = data.get("owner") or session.get("owner", "")
    repo = data.get("repo") or session.get("repo", "")
    issue_number = data.get("issue_number") or session.get("issue_number")
    token = os.environ.get("GITHUB_TOKEN", "")
    stage = (request.path or "").lstrip("/").replace("-agent", "").replace("-", " ") or None
    if owner and repo and issue_number and token:
        try:
            from shared.utils import post_github_comment
            post_github_comment(owner, repo, issue_number, e.comment_body(stage), token)
        except Exception:
            pass
    # Return 200 (not 503) so n8n treats it as a normal response: the orchestrator
    # gates on status == "rate_limited", Waits retry_after_seconds, then re-calls
    # this same step. A 503 would error the HTTP node and stop the whole chain.
    return jsonify({
        "status": "rate_limited",
        "stage": stage,
        "message": e.user_message,
        "retry_after_seconds": e.wait_seconds,
        "reset_at": e.reset_at_str,
    }), 200


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
        issue_type = data.get("issue_type") or session.get("issue_type", "Feature")
        result = ba.run(
            session_id=sid,
            requirement=data.get("requirement") or session.get("requirement", ""),
            repo_path=repo_path,
            clarification_answers=data.get("clarification_answers"),
            human_feedback=data.get("human_feedback"),
            issue_type=issue_type,
        )
        # Persist repo metadata so downstream agents can find it.
        # GitHub comment posting is handled by n8n (workflow 1's "Comment BRD on Issue" node),
        # not here — posting from both layers caused duplicate BRD comments on every run.
        save_session(sid, {
            "owner": data.get("owner") or session.get("owner", ""),
            "repo": data.get("repo") or session.get("repo", ""),
            "issue_number": data.get("issue_number") or session.get("issue_number"),
            "test_command": test_command,
            "main_branch": main_branch,
            "issue_type": issue_type,
        })
        return jsonify({"status": "success", "stage": "ba", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return _agent_failure(e)


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
        return _agent_failure(e)


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
        return _agent_failure(e)


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
        return _agent_failure(e)


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
        return _agent_failure(e)


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
        return _agent_failure(e)


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
        return _agent_failure(e)


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
        return _agent_failure(e)


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
        return _agent_failure(e)


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
        return _agent_failure(e)


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


def _behat_gen_prompt(title, brd):
    brd = brd or ""
    # Pull the Test Cases section out of the (often long) BRD so every case is
    # included regardless of where it sits — the old flat char-cap frequently
    # truncated the BRD before reaching the test cases.
    import re as _re
    m = _re.search(r'(?is)\n#+\s*test cases\b.*', brd)
    test_cases = m.group(0).strip()[:3500] if m else ""
    context = brd[:1200]
    if test_cases:
        context += "\n\n--- TEST CASES TO COVER ---\n" + test_cases

    return f"""Generate a Moodle Behat feature (Gherkin) that exercises EACH test case for this requirement on a FRESH IOMAD test site, capturing one screenshot PER TEST CASE as evidence.

REQUIREMENT: {title}

CONTEXT (BRD excerpt + the test cases to cover):
{context}

STRICT RULES:
- Output ONLY Gherkin, starting with `Feature:`. No prose, no code fences, no @tags (tags are added automatically).
- The test site is EMPTY — only the `admin` user exists; no courses, users, or companies. Do NOT reference data that wouldn't be there. If a test case needs data that cannot exist on an empty site, still navigate to the admin page most relevant to that case and capture a screenshot, so the case has evidence.
- Use ONLY these steps (exact wording):
  - Given I log in as "admin"
  - And I am on site homepage
  - And I navigate to "<Page> > <Subpage>" in site administration
  - And I capture the screen as "<short-name>"
  - Then I should see "<text>"
  - And I click on "<text>" "link"
  - And I press "<button>"
- Produce ONE Scenario PER TEST CASE listed above (both positive and negative). Title each Scenario after its test case.
- Begin every Scenario with `Given I log in as "admin"` and keep it short (3-6 steps).
- EACH Scenario MUST END with `And I capture the screen as "<short-name>"`, where <short-name> is a UNIQUE kebab-case slug of that test case (e.g. "tc1-footer-shows-full-name", "tc2-logged-out-no-footer"). This guarantees exactly one screenshot per test case.
- If there are more than 12 test cases, cover the first 12."""


def _ui_observable(title, brd):
    """Quick yes/no gate: does this change produce a USER-OBSERVABLE difference
    verifiable through the IOMAD web UI? Used to skip pointless live Behat runs
    for comment/refactor/backend-only changes. Defaults to True on uncertainty."""
    from shared.claude import ask_claude
    prompt = f"""A change was made to a Moodle/IOMAD codebase. Decide whether it produces a USER-OBSERVABLE difference that a tester could verify by navigating the IOMAD web UI (a visible page, element, or behaviour change).

TITLE: {title}
REQUIREMENT / BRD (excerpt):
{(brd or '')[:1500]}

Answer with exactly one word:
- yes — there is a visible UI/behaviour change someone could see and screenshot.
- no  — purely internal (code comment, refactor, logging, backend/data, build/config) with nothing visible in the UI.
If unsure, answer "yes". Output ONLY the one word."""
    try:
        ans = ask_claude(prompt).strip().lower()
    except Exception:
        return True
    return not ans.startswith("no")


@app.route("/test-evidence", methods=["POST"])
def test_evidence():
    """Run a Behat feature on the live IOMAD test instance, upload the
    screenshots to the repo, and comment them on the issue. Generates a
    constrained smoke feature from the BRD if none is supplied."""
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    owner = data.get("owner") or session.get("owner", "")
    repo = data.get("repo") or session.get("repo", "")
    issue_number = data.get("issue_number") or session.get("issue_number")
    token = os.environ.get("GITHUB_TOKEN", "")

    feature = data.get("feature") or session.get("test_feature")
    force = bool(data.get("force"))
    title = session.get("issue_title") or (session.get("requirement", "").split("\n")[0].strip()) or "the feature"

    # Scale evidence to the change: skip the live UI run when there's nothing
    # user-observable to screenshot (comments, refactors, backend-only). An
    # explicit feature or force=true overrides the gate.
    if not feature and not force and not _ui_observable(title, session.get("brd_draft", "")):
        body = ("## Test Evidence — skipped\n\n"
                "No live UI evidence applicable: this change has no user-observable behaviour "
                "(e.g. a code comment, refactor, or backend-only change), so there is nothing to "
                "screenshot on the IOMAD site. Correctness was checked by the unit tests at the Dev stage.\n\n"
                "_Add `force` to run live evidence anyway._")
        if token and owner and repo and issue_number:
            from shared.utils import post_github_comment
            post_github_comment(owner, repo, issue_number, body, token)
        save_session(sid, {"test_evidence": {"skipped": True, "reason": "no user-observable UI change"}})
        return jsonify({"status": "success", "skipped": True, "reason": "no user-observable UI change"})

    from shared.test_runner_client import run_behat_feature, runner_available
    if not runner_available():
        return jsonify({"status": "error", "message": "test runner unavailable (check TEST_RUNNER_URL / IOMAD-LIVE)"}), 503
    if not feature:
        from shared.claude import ask_claude
        feature = ask_claude(_behat_gen_prompt(title, session.get("brd_draft", "")))

    result = run_behat_feature(feature, name=f"issue-{issue_number or 'adhoc'}")
    if result.get("error"):
        return jsonify({"status": "error", "message": result["error"], "output_tail": result.get("output_tail", "")}), 502

    # Screenshots are self-hosted on the test instance (not uploaded to GitHub);
    # the runner returns a click-to-open URL per shot. Keeping them off GitHub
    # keeps the repo private — the links open from a browser that can reach the
    # test box (internal/VPN).
    from shared.utils import post_github_comment
    links = []
    for s in result.get("screenshots", []):
        url = s.get("url")
        if url:
            links.append((s.get("name", "screenshot"), url))

    status = "PASS" if result.get("passed") else "needs review"
    body = f"## Test Evidence — live IOMAD run\n\n**Result:** {status} — {result.get('summary', '')}\n\n"
    if links:
        body += (f"**Screenshots:** {len(links)} (one per test case, where reachable) — "
                 f"hosted on the IOMAD test instance; click to view (internal/VPN access).\n\n")
        for name_, url in links:
            body += f"- [{name_}]({url})\n"
        body += "\n"
    else:
        body += "_No screenshots captured (see run output)._\n"
    if token and owner and repo and issue_number:
        post_github_comment(owner, repo, issue_number, body, token)

    save_session(sid, {"test_evidence": {
        "passed": result.get("passed"),
        "summary": result.get("summary"),
        "screenshot_urls": [u for _, u in links],
    }})
    return jsonify({
        "status": "success",
        "passed": result.get("passed"),
        "summary": result.get("summary"),
        "screenshots": [u for _, u in links],
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
