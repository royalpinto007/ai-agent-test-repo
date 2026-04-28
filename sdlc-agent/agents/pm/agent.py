from shared.claude import ask_claude
from shared.utils import get_file_tree
from shared.session import save_session, load_session
from agents.pm.prompts import pm_prompt


def run(session_id, repo_path, brd=None):
    session = load_session(session_id) or {}
    brd = brd or session.get("brd_draft", "")
    repo_path = repo_path or session.get("repo_path")

    if not brd:
        raise ValueError("brd is required")

    file_tree_str = "\n".join(get_file_tree(repo_path))
    pm_output = ask_claude(pm_prompt(brd, file_tree_str))

    save_session(session_id, {
        "pm_output": pm_output,
        "repo_path": repo_path,
        "stage": "pm",
    })

    return {
        "pm_output": pm_output,
        "next_stage": "dev",
    }
