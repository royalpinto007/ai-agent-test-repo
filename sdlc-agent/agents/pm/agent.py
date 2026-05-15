import re
import os
import json
import subprocess
from shared.claude import ask_claude
from shared.utils import get_file_tree, create_github_issue
from shared.session import save_session, load_session
from shared.config import all_repos, get_code_repos, is_requirements_repo
from agents.pm.prompts import brd_review_prompt, questions_followup_prompt, revision_prompt as pm_revision_prompt


def _has_blocking_questions(pm_output):
    """Check if any questions are marked as blocking: Yes in the questions section."""
    section = pm_output.lower().split("## 4.")
    if len(section) < 2:
        section = pm_output.lower().split("## questions for the ba")
    if len(section) < 2:
        return False
    tail = section[-1][:800]
    first_line = tail[:80]
    if "none" in first_line or "development-ready" in first_line:
        return False
    return bool(re.search(r'\*{0,2}blocking\*{0,2}[:\s*]+yes', tail))


def _is_ready_for_dev(pm_output):
    """Check PM recommendation."""
    section = pm_output.lower().split("## 10.")
    if len(section) < 2:
        section = pm_output.lower().split("## pm recommendation")
    if len(section) < 2:
        return False
    tail = section[-1][:200]
    return "yes" in tail[:50]


def _extract_json_block(text, after_marker=None):
    """Extract the first JSON array from a fenced code block in text, optionally after a marker."""
    search_text = text
    if after_marker:
        idx = text.lower().find(after_marker.lower())
        if idx != -1:
            search_text = text[idx:]
    m = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', search_text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return []


def _parse_tasks(pm_output):
    """Extract tasks from the JSON block in the task breakdown section."""
    return _extract_json_block(pm_output, after_marker="task breakdown")


def _priority_to_label(priority):
    p = priority.upper()
    if "P1" in p:
        return ["priority: critical"]
    if "P2" in p:
        return ["priority: high"]
    if "P3" in p:
        return ["priority: low"]
    return []


def _type_to_label(task_type):
    t = task_type.lower()
    if "bug" in t:
        return ["bug"]
    if "feature" in t:
        return ["enhancement"]
    if "test" in t:
        return ["testing"]
    if "refactor" in t:
        return ["refactor"]
    return []


def _create_issues_for_tasks(tasks, repo_path, parent_session_id):
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return [], "GITHUB_TOKEN not set — skipping issue creation"

    # Derive owner/repo from git remote
    import subprocess
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path, capture_output=True, text=True
    ).stdout.strip()
    remote = remote.replace("git@github.com:", "https://github.com/")
    parts = remote.rstrip(".git").rstrip("/").split("/")
    owner, repo = parts[-2], parts[-1]

    created = []
    for task in tasks:
        body = f"""## Description
{task.get('description', '')}

## Acceptance Criteria
{task.get('acceptance_criteria', '')}

## Details
- **Type:** {task.get('type', '')}
- **Effort:** {task.get('effort', '')}
- **Complexity:** {task.get('complexity', '')}
- **Risk:** {task.get('risk', '')}
- **Affected Files:** {task.get('affected_files', '')}
- **Depends On:** {task.get('depends_on', 'None')}

---
*Created by PM Agent from session `{parent_session_id}`*
"""
        labels = _priority_to_label(task['priority']) + _type_to_label(task['type'])
        try:
            issue = create_github_issue(owner, repo, token, task['title'], body, labels)
            created.append({**task, "issue_number": issue["number"], "issue_url": issue["url"]})
        except RuntimeError as e:
            created.append({**task, "issue_number": None, "error": str(e)})

    return created, None


def _parse_cross_repo_tasks(pm_output):
    """Extract cross-repo tasks from the JSON block in the cross-repo section."""
    items = _extract_json_block(pm_output, after_marker="cross-repo impact")
    # Filter out any items that aren't valid repo entries
    return [i for i in items if isinstance(i, dict) and "/" in i.get("repo", "")]


def _create_cross_repo_issues(cross_repo_tasks, token, parent_issue_url, parent_session_id):
    created = []
    for task in cross_repo_tasks:
        parts = task["repo"].split("/")
        if len(parts) != 2:
            created.append({**task, "error": f"invalid repo slug: {task['repo']}"})
            continue
        owner, repo = parts

        body = f"""{task['issue_body']}

---
*Cross-repo impact detected by PM Agent. Parent issue: {parent_issue_url} (session: `{parent_session_id}`)*
"""
        try:
            issue = create_github_issue(owner, repo, token, task["issue_title"], body, [])
            created.append({**task, "issue_number": issue["number"], "issue_url": issue["url"]})
        except RuntimeError as e:
            created.append({**task, "error": str(e)})

    return created


def run(session_id, repo_path=None, brd=None, ba_answers=None, human_feedback=None):
    session = load_session(session_id) or {}
    repo_path = repo_path or session.get("repo_path")
    brd = brd or session.get("brd_draft", "")
    system_analysis = session.get("system_analysis", "")

    if not brd:
        raise ValueError("brd is required — pass session_id or explicit brd")

    sdd = session.get("sdd", "")

    # Detect if this session is driven from a requirements repo (e.g. thrive-requirements)
    parts = session_id.rsplit("-", 1)
    current_owner_repo = parts[0].replace("-", "/", 1) if "-" in session_id else ""
    current_owner, current_repo_name = (current_owner_repo.split("/", 1) + [""])[:2]
    on_requirements_repo = is_requirements_repo(current_owner, current_repo_name)

    if on_requirements_repo:
        # Build a combined file tree from ALL registered code repos
        code_repos = get_code_repos()
        combined_tree_lines = []
        for slug, cfg in code_repos.items():
            rp = cfg.get("repo_path", "")
            if rp and os.path.isdir(rp):
                for f in get_file_tree(rp):
                    combined_tree_lines.append(f"{slug}/{f}")
        file_tree_str = "\n".join(combined_tree_lines) if combined_tree_lines else "(no code repos cloned yet)"
        other_repos = list(code_repos.keys())
    else:
        file_tree_str = "\n".join(get_file_tree(repo_path))
        try:
            registered = all_repos()
            other_repos = [slug for slug in registered if slug != current_owner_repo]
        except Exception:
            other_repos = []

    if human_feedback and session.get("pm_output"):
        pm_output = ask_claude(pm_revision_prompt(
            brd, session["pm_output"], human_feedback, file_tree_str
        ))
    elif ba_answers and session.get("pm_output"):
        pm_output = ask_claude(questions_followup_prompt(
            brd, session["pm_output"], ba_answers, file_tree_str
        ))
    else:
        pm_output = ask_claude(brd_review_prompt(brd, system_analysis, file_tree_str, sdd, other_repos=other_repos or None))

    has_blocking = _has_blocking_questions(pm_output)
    dev_ready = _is_ready_for_dev(pm_output)

    token = os.environ.get("GITHUB_TOKEN", "")

    # Derive parent issue URL
    parent_issue_url = session.get("issue_url", "")
    if not parent_issue_url:
        parts = session_id.rsplit("-", 1)
        if len(parts) == 2:
            owner_repo, issue_num = parts[0].replace("-", "/", 1), parts[1]
            parent_issue_url = f"https://github.com/{owner_repo}/issues/{issue_num}"

    # Create GitHub issues for each task when dev-ready.
    # Skip creation on revise/followup runs — issues were already created on the first approval.
    is_revision = bool(human_feedback or ba_answers)
    already_created = bool(session.get("pm_tasks"))

    created_issues = session.get("pm_tasks", []) if already_created else []
    issues_error = None
    cross_repo_issues = session.get("cross_repo_issues", []) if already_created else []

    if dev_ready and not has_blocking and not is_revision and not already_created:
        tasks = _parse_tasks(pm_output)
        if tasks:
            created_issues, issues_error = _create_issues_for_tasks(tasks, repo_path, session_id)

        if token and other_repos:
            cross_repo_tasks = _parse_cross_repo_tasks(pm_output)
            if cross_repo_tasks:
                cross_repo_issues = _create_cross_repo_issues(cross_repo_tasks, token, parent_issue_url, session_id)

    # When on a requirements repo, the primary target for Dev is the first affected code repo.
    # Cross-repo issues cover the rest.
    target_repo = session.get("target_repo")
    if not target_repo and on_requirements_repo and cross_repo_issues:
        first = cross_repo_issues[0]
        target_slug = first.get("repo", "")
        if target_slug:
            code_cfg = get_code_repos().get(target_slug, {})
            target_repo = {
                "slug": target_slug,
                "repo_path": code_cfg.get("repo_path", ""),
                "test_command": code_cfg.get("test_command"),
                "main_branch": code_cfg.get("main_branch", "main"),
            }

    config_only = session.get("config_only", False)

    save_session(session_id, {
        "pm_output": pm_output,
        "pm_has_blocking_questions": has_blocking,
        "pm_dev_ready": dev_ready,
        "pm_tasks": created_issues,
        "cross_repo_issues": cross_repo_issues,
        "repo_path": repo_path,
        "target_repo": target_repo,
        "stage": "pm",
    })

    # Config-only feature: PM posts config instructions and terminates the pipeline
    if config_only:
        token = os.environ.get("GITHUB_TOKEN", "")
        owner = session.get("owner", "")
        repo_name = session.get("repo", "")
        issue_number = session.get("issue_number")
        if owner and repo_name and issue_number and token:
            from shared.utils import post_github_comment
            post_github_comment(
                owner, repo_name, issue_number,
                "## Config Instructions Complete\n\nThis requirement can be satisfied through configuration only — no code changes required.\n\n" + pm_output,
                token
            )
        return {
            "pm_output": pm_output,
            "has_blocking_questions": False,
            "dev_ready": False,
            "created_issues": created_issues,
            "issues_error": issues_error,
            "cross_repo_issues": cross_repo_issues,
            "target_repo": target_repo,
            "terminal": True,
            "next_stage": "complete",
        }

    return {
        "pm_output": pm_output,
        "has_blocking_questions": has_blocking,
        "dev_ready": dev_ready,
        "created_issues": created_issues,
        "issues_error": issues_error,
        "cross_repo_issues": cross_repo_issues,
        "target_repo": target_repo,
        "terminal": False,
        "next_stage": "pm (answer questions)" if has_blocking else "dev",
    }
