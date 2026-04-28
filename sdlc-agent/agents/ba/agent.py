from shared.claude import ask_claude
from shared.utils import get_file_tree
from shared.session import save_session, load_session
from agents.ba.prompts import initial_prompt, followup_prompt


def run(session_id, requirement, repo_path, clarification_answers=None):
    session = load_session(session_id) or {}
    file_tree_str = "\n".join(get_file_tree(repo_path))

    if clarification_answers and session.get("brd_draft"):
        brd = ask_claude(followup_prompt(requirement, session["brd_draft"], clarification_answers))
    else:
        brd = ask_claude(initial_prompt(requirement, file_tree_str))

    # Check if clarification questions remain unanswered
    questions_section = brd.lower().split("## clarification questions")
    needs_clarification = len(questions_section) > 1 and "none" not in questions_section[-1][:60]

    save_session(session_id, {
        "requirement": requirement,
        "repo_path": repo_path,
        "brd_draft": brd,
        "stage": "ba",
    })

    return {
        "brd": brd,
        "needs_clarification": needs_clarification,
        "next_stage": "ba (answer questions)" if needs_clarification else "pm",
    }
