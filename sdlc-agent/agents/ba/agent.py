from shared.claude import ask_claude
from shared.utils import get_file_tree, read_file, grep_repo, identify_relevant_files, run_git
from shared.session import save_session, load_session
from agents.ba.prompts import system_analysis_prompt, brd_prompt, followup_prompt, revision_prompt


def _load_relevant_files(requirement, repo_path, file_tree):
    """Read files relevant to the requirement so the BA understands the current system."""
    # Ask Claude which files are relevant for understanding the current system
    file_tree_str = "\n".join(file_tree)
    prompt = f"""You are a Business Analyst trying to understand the current system before writing a requirements document.

REQUIREMENT: {requirement}

FILE TREE:
{file_tree_str}

Which files should you read to understand the current system's capabilities and limitations relevant to this requirement?
Return ONLY a JSON array of relative file paths. No explanation, no markdown.
"""
    import json
    response = ask_claude(prompt)
    try:
        files = json.loads(response)
        files = [f for f in files if isinstance(f, str) and f in file_tree]
    except Exception:
        files = []

    # Also grep for any key terms in the requirement
    import re
    keywords = re.findall(r'\b\w{5,}\b', requirement)[:5]
    for keyword in keywords:
        for f in grep_repo(repo_path, rf'\b{keyword}\b', file_tree):
            if f not in files:
                files.append(f)

    contents = {}
    for f in files[:15]:  # cap at 15 files to avoid overwhelming the prompt
        content = read_file(repo_path, f)
        if content:
            contents[f] = content
    return contents


def _has_open_questions(brd):
    section = brd.lower().split("## 14.")
    if len(section) < 2:
        section = brd.lower().split("## clarification questions")
    if len(section) < 2:
        return False
    tail = section[-1][:200]
    return "none" not in tail and "fully specified" not in tail


def run(session_id, requirement, repo_path, clarification_answers=None, human_feedback=None):
    session = load_session(session_id) or {}
    requirement = requirement or session.get("requirement", "")

    if not requirement:
        raise ValueError("requirement is required")

    # Always pull latest before analysing so we read current code
    try:
        run_git(["pull"], cwd=repo_path)
    except Exception:
        pass  # non-fatal — continue with whatever is on disk

    file_tree = get_file_tree(repo_path)
    file_tree_str = "\n".join(file_tree)

    # Step 1: Analyse the current system (always fresh, or load from session)
    system_analysis = session.get("system_analysis")
    if not system_analysis:
        file_contents = _load_relevant_files(requirement, repo_path, file_tree)
        system_analysis = ask_claude(system_analysis_prompt(requirement, file_tree_str, file_contents))

    # Step 2: Generate or refine the BRD
    if human_feedback and session.get("brd_draft"):
        brd = ask_claude(revision_prompt(
            requirement, system_analysis, session["brd_draft"], human_feedback, file_tree_str
        ))
    elif clarification_answers and session.get("brd_draft"):
        brd = ask_claude(followup_prompt(
            requirement, system_analysis, session["brd_draft"], clarification_answers, file_tree_str
        ))
    else:
        brd = ask_claude(brd_prompt(requirement, system_analysis, file_tree_str))

    needs_clarification = _has_open_questions(brd)

    save_session(session_id, {
        "requirement": requirement,
        "issue_title": requirement.split("\n")[0].strip(),
        "repo_path": repo_path,
        "system_analysis": system_analysis,
        "brd_draft": brd,
        "needs_clarification": needs_clarification,
        "stage": "ba",
    })

    return {
        "system_analysis": system_analysis,
        "brd": brd,
        "needs_clarification": needs_clarification,
        "next_stage": "ba (answer questions)" if needs_clarification else "pm",
    }
