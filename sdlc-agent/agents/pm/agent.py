from shared.claude import ask_claude
from shared.utils import get_file_tree
from shared.session import save_session, load_session
from agents.pm.prompts import brd_review_prompt, questions_followup_prompt


def _has_blocking_questions(pm_output):
    """Check if any questions are marked as blocking."""
    section = pm_output.lower().split("## 4.")
    if len(section) < 2:
        section = pm_output.lower().split("## questions for the ba")
    if len(section) < 2:
        return False
    tail = section[-1][:500]
    return "none" not in tail[:60] and "development-ready" not in tail[:60]


def _is_ready_for_dev(pm_output):
    """Check PM recommendation."""
    section = pm_output.lower().split("## 10.")
    if len(section) < 2:
        section = pm_output.lower().split("## pm recommendation")
    if len(section) < 2:
        return False
    tail = section[-1][:200]
    return "yes" in tail[:50]


def run(session_id, repo_path=None, brd=None, ba_answers=None):
    session = load_session(session_id) or {}
    repo_path = repo_path or session.get("repo_path")
    brd = brd or session.get("brd_draft", "")
    system_analysis = session.get("system_analysis", "")

    if not brd:
        raise ValueError("brd is required — pass session_id or explicit brd")

    file_tree_str = "\n".join(get_file_tree(repo_path))

    if ba_answers and session.get("pm_output"):
        # Refine PM review with answers
        pm_output = ask_claude(questions_followup_prompt(
            brd, session["pm_output"], ba_answers, file_tree_str
        ))
    else:
        # First PM review
        pm_output = ask_claude(brd_review_prompt(brd, system_analysis, file_tree_str))

    has_blocking = _has_blocking_questions(pm_output)
    dev_ready = _is_ready_for_dev(pm_output)

    save_session(session_id, {
        "pm_output": pm_output,
        "pm_has_blocking_questions": has_blocking,
        "pm_dev_ready": dev_ready,
        "repo_path": repo_path,
        "stage": "pm",
    })

    return {
        "pm_output": pm_output,
        "has_blocking_questions": has_blocking,
        "dev_ready": dev_ready,
        "next_stage": "pm (answer questions)" if has_blocking else "dev",
    }
