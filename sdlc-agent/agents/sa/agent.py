import re
from shared.claude import ask_claude
from shared.utils import get_file_tree
from shared.session import save_session, load_session
from agents.sa.prompts import solution_design_prompt, revision_prompt


def _has_open_questions(sdd):
    """Check if Section 11 has unanswered questions."""
    section = sdd.lower().split("## 11.")
    if len(section) < 2:
        section = sdd.lower().split("## open questions")
    if len(section) < 2:
        return False
    tail = section[-1][:200]
    return "none" not in tail and "implementation-ready" not in tail


def run(session_id, repo_path=None, human_feedback=None):
    session = load_session(session_id) or {}
    repo_path = repo_path or session.get("repo_path")
    brd = session.get("brd_draft", "")
    system_analysis = session.get("system_analysis", "")

    if not brd:
        raise ValueError("brd is required — run BA agent first (session must have brd_draft)")

    file_tree_str = "\n".join(get_file_tree(repo_path))

    previous_sdd = session.get("sdd", "")
    if human_feedback and previous_sdd:
        # Revision loop — update SDD based on human feedback
        sdd = ask_claude(revision_prompt(brd, previous_sdd, human_feedback, file_tree_str))
        revision_count = session.get("sdd_revision_count", 0) + 1
    else:
        # First pass — produce initial SDD
        sdd = ask_claude(solution_design_prompt(brd, system_analysis, file_tree_str))
        revision_count = 0

    has_open_questions = _has_open_questions(sdd)

    save_session(session_id, {
        "sdd": sdd,
        "sdd_revision_count": revision_count,
        "sdd_has_open_questions": has_open_questions,
        "repo_path": repo_path,
        "stage": "sa",
    })

    return {
        "sdd": sdd,
        "has_open_questions": has_open_questions,
        "revision_count": revision_count,
        "next_stage": "sa (revise)" if has_open_questions else "pm",
    }
