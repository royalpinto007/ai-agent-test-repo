import re
import os
from shared.claude import ask_claude
from shared.utils import get_file_tree, create_github_issue
from shared.session import save_session, load_session
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


def _parse_tasks(pm_output):
    """Extract tasks from PM output Section 5."""
    tasks = []
    # Find Section 5 task breakdown
    section = pm_output.split("## 5.")
    if len(section) < 2:
        section = pm_output.split("## Task Breakdown")
    if len(section) < 2:
        return tasks

    body = section[-1].split("## 6.")[0]  # stop at next section

    # Each task starts with ### Task [N]: <title>
    task_blocks = re.split(r'###\s+Task\s+\[?\d+\]?:\s*', body)
    for block in task_blocks[1:]:  # skip content before first task
        lines = block.strip().split("\n")
        title = lines[0].strip()
        if not title:
            continue

        # Extract key fields
        def _field(pattern, default=""):
            m = re.search(pattern, block, re.IGNORECASE)
            return m.group(1).strip() if m else default

        task_type   = _field(r'\*\*Type:\*\*\s*(.+)')
        description = _field(r'\*\*Description:\*\*\s*(.+)')
        effort      = _field(r'\*\*Effort Estimate:\*\*\s*(.+)')
        priority    = _field(r'\*\*Priority:\*\*\s*(.+)')
        complexity  = _field(r'\*\*Complexity:\*\*\s*(.+)')
        risk        = _field(r'\*\*Risk:\*\*\s*(.+)')
        affected    = _field(r'\*\*Affected Files:\*\*\s*(.+)')
        depends_on  = _field(r'\*\*Depends On:\*\*\s*(.+)')
        blocked_by  = _field(r'\*\*Blocked By:\*\*\s*(.+)')

        # Grab acceptance criteria block
        ac_match = re.search(r'\*\*Acceptance Criteria:\*\*(.+?)(?=\*\*\w|$)', block, re.DOTALL)
        acceptance_criteria = ac_match.group(1).strip() if ac_match else ""

        tasks.append({
            "title": title,
            "type": task_type,
            "description": description,
            "acceptance_criteria": acceptance_criteria,
            "effort": effort,
            "priority": priority,
            "complexity": complexity,
            "risk": risk,
            "affected_files": affected,
            "depends_on": depends_on,
            "blocked_by": blocked_by,
        })
    return tasks


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
{task['description']}

## Acceptance Criteria
{task['acceptance_criteria']}

## Details
- **Type:** {task['type']}
- **Effort:** {task['effort']}
- **Complexity:** {task['complexity']}
- **Risk:** {task['risk']}
- **Affected Files:** {task['affected_files']}
- **Depends On:** {task['depends_on']}
- **Blocked By:** {task['blocked_by']}

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


def run(session_id, repo_path=None, brd=None, ba_answers=None, human_feedback=None):
    session = load_session(session_id) or {}
    repo_path = repo_path or session.get("repo_path")
    brd = brd or session.get("brd_draft", "")
    system_analysis = session.get("system_analysis", "")

    if not brd:
        raise ValueError("brd is required — pass session_id or explicit brd")

    file_tree_str = "\n".join(get_file_tree(repo_path))
    sdd = session.get("sdd", "")

    if human_feedback and session.get("pm_output"):
        pm_output = ask_claude(pm_revision_prompt(
            brd, session["pm_output"], human_feedback, file_tree_str
        ))
    elif ba_answers and session.get("pm_output"):
        pm_output = ask_claude(questions_followup_prompt(
            brd, session["pm_output"], ba_answers, file_tree_str
        ))
    else:
        pm_output = ask_claude(brd_review_prompt(brd, system_analysis, file_tree_str, sdd))

    has_blocking = _has_blocking_questions(pm_output)
    dev_ready = _is_ready_for_dev(pm_output)

    # Create GitHub issues for each task when dev-ready
    created_issues = []
    issues_error = None
    if dev_ready and not has_blocking:
        tasks = _parse_tasks(pm_output)
        if tasks:
            created_issues, issues_error = _create_issues_for_tasks(tasks, repo_path, session_id)

    save_session(session_id, {
        "pm_output": pm_output,
        "pm_has_blocking_questions": has_blocking,
        "pm_dev_ready": dev_ready,
        "pm_tasks": created_issues,
        "repo_path": repo_path,
        "stage": "pm",
    })

    return {
        "pm_output": pm_output,
        "has_blocking_questions": has_blocking,
        "dev_ready": dev_ready,
        "created_issues": created_issues,
        "issues_error": issues_error,
        "next_stage": "pm (answer questions)" if has_blocking else "dev",
    }
