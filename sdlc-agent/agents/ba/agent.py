import os
from shared.claude import ask_claude
from shared.utils import get_file_tree, read_file, grep_repo, run_git
from shared.session import save_session, load_session
from shared.config import get_code_repos, is_requirements_repo
from agents.ba.prompts import (
    analysis_and_brd_prompt,
    followup_prompt,
    revision_prompt,
    bug_analysis_prompt,
)

MAX_FILES_TO_READ = 15


def _build_repo_context(session_id, repo_path):
    """Return (file_tree_str, file_lookup) for either the single repo or all code repos.

    file_lookup is {file_path_as_seen_by_model: (real_repo_path, real_relative_path)}
    so when Claude asks for a file by its slug-prefixed path we know where to read it from.
    """
    parts = session_id.rsplit("-", 1)
    current_owner_repo = parts[0].replace("-", "/", 1) if "-" in session_id else ""
    current_owner, current_repo_name = (current_owner_repo.split("/", 1) + [""])[:2]
    on_requirements_repo = is_requirements_repo(current_owner, current_repo_name)

    tree_lines = []
    lookup = {}

    if on_requirements_repo:
        for slug, cfg in get_code_repos().items():
            rp = cfg.get("repo_path", "")
            if rp and os.path.isdir(rp):
                for f in get_file_tree(rp):
                    seen = f"{slug}/{f}"
                    tree_lines.append(seen)
                    lookup[seen] = (rp, f)
    else:
        if repo_path and os.path.isdir(repo_path):
            for f in get_file_tree(repo_path):
                tree_lines.append(f)
                lookup[f] = (repo_path, f)

    return "\n".join(tree_lines) if tree_lines else "(no code visible)", lookup


def _load_relevant_files(requirement, file_tree_str, file_lookup):
    """Ask Claude which files are most relevant, then read them. Works across multiple repos
    because file_lookup maps the path-as-seen-by-Claude to the real (repo_path, rel_path)."""
    import json
    import re

    prompt = f"""You are a Business Analyst trying to understand the current system before writing a requirements document.

REQUIREMENT: {requirement}

FILE TREE:
{file_tree_str}

Which files should you read to understand the current system's capabilities and limitations relevant to this requirement?
Return ONLY a JSON array of relative file paths exactly as shown in the tree above. No explanation, no markdown.
"""
    response = ask_claude(prompt)
    try:
        picked = json.loads(response)
        picked = [f for f in picked if isinstance(f, str) and f in file_lookup]
    except Exception:
        picked = []

    # Also grep across each repo for any key terms in the requirement.
    seen_repos = set(rp for rp, _ in file_lookup.values())
    keywords = re.findall(r'\b\w{5,}\b', requirement)[:5]
    for rp in seen_repos:
        slug_prefix = ""
        # Recover the slug prefix used in the tree for this repo, if any.
        for k, (vrp, _) in file_lookup.items():
            if vrp == rp and "/" in k:
                slug_prefix = k.split("/")[0] + "/"
                break
        rp_files = [rel for (vrp, rel) in file_lookup.values() if vrp == rp]
        for keyword in keywords:
            for rel in grep_repo(rp, rf'\b{keyword}\b', rp_files):
                seen = f"{slug_prefix}{rel}"
                if seen not in picked and seen in file_lookup:
                    picked.append(seen)

    contents = {}
    for seen in picked[:MAX_FILES_TO_READ]:
        rp, rel = file_lookup[seen]
        content = read_file(rp, rel)
        if content:
            contents[seen] = content
    return contents


def _split_analysis_and_brd(combined_text):
    """Split the combined analysis+BRD output into the two sections.

    The prompt asks the model to emit '## System Analysis' then '## Business Requirements Document'.
    """
    marker = "## Business Requirements Document"
    idx = combined_text.find(marker)
    if idx == -1:
        # Couldn't find the BRD section — treat entire response as BRD, leave analysis empty.
        return "", combined_text.strip()
    analysis = combined_text[:idx].strip()
    brd = combined_text[idx:].strip()
    return analysis, brd


def _has_open_questions(brd):
    section = brd.lower().split("## 14.")
    if len(section) < 2:
        section = brd.lower().split("## clarification questions")
    if len(section) < 2:
        section = brd.lower().split("## open questions")
    if len(section) < 2:
        return False
    tail = section[-1][:200]
    return "none" not in tail and "fully specified" not in tail


def _parse_resolution_tier(text):
    """Parse RESOLUTION_TIER: config|workaround|code_change from the end of a BRD response."""
    import re
    m = re.search(r'RESOLUTION_TIER:\s*(config|workaround|code_change)', text, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    # Backward-compat: older BRDs used CONFIG_ONLY: true/false
    m = re.search(r'CONFIG_ONLY:\s*(true|false)', text, re.IGNORECASE)
    if m:
        return "config" if m.group(1).lower() == "true" else "code_change"
    return "code_change"


def _detect_ui_needed(requirement):
    """Detect the 'UI mockup needed?' answer from the issue body.

    GitHub issue-form dropdowns render as a header line followed by the chosen
    value, e.g.  '### UI mockup needed?\\n\\nYes'. Defaults to False so the UI
    mockup (extra tokens) is only produced when explicitly requested.
    """
    import re
    m = re.search(r'ui mockup needed.*?\n+\s*(yes|no)\b', requirement or "", re.IGNORECASE | re.DOTALL)
    return bool(m and m.group(1).lower() == "yes")


def run(session_id, requirement, repo_path, clarification_answers=None, human_feedback=None, issue_type=None):
    session = load_session(session_id) or {}
    requirement = requirement or session.get("requirement", "")
    issue_type = issue_type or session.get("issue_type", "Feature")

    if not requirement:
        raise ValueError("requirement is required")

    ui_needed = _detect_ui_needed(requirement)

    # Pull latest before analysing so we read current code.
    try:
        run_git(["pull"], cwd=repo_path)
    except Exception:
        pass

    file_tree_str, file_lookup = _build_repo_context(session_id, repo_path)

    if issue_type == "Bug":
        file_contents = _load_relevant_files(requirement, file_tree_str, file_lookup)
        issue_title = requirement.split("\n")[0].strip()
        brd = ask_claude(bug_analysis_prompt(issue_title, requirement, file_contents, file_tree_str))
        system_analysis = ""

        save_session(session_id, {
            "requirement": requirement,
            "issue_title": issue_title,
            "repo_path": repo_path,
            "system_analysis": system_analysis,
            "brd_draft": brd,
            "needs_clarification": False,
            "issue_type": issue_type,
            "resolution_tier": "code_change",
            "config_only": False,
            "stage": "ba",
        })

        return {
            "system_analysis": system_analysis,
            "brd": brd,
            "needs_clarification": False,
            "resolution_tier": "code_change",
            "config_only": False,
            "issue_type": issue_type,
            "next_stage": "dev",
        }

    # Feature / default flow — one combined Claude call produces both analysis and BRD.
    if human_feedback and session.get("brd_draft"):
        # Revision: keep the existing analysis, just re-run BRD with feedback.
        system_analysis = session.get("system_analysis", "")
        brd = ask_claude(revision_prompt(
            requirement, system_analysis, session["brd_draft"], human_feedback, file_tree_str
        ))
    elif clarification_answers and session.get("brd_draft"):
        system_analysis = session.get("system_analysis", "")
        brd = ask_claude(followup_prompt(
            requirement, system_analysis, session["brd_draft"], clarification_answers, file_tree_str
        ))
    else:
        # First pass: load files, then one combined call.
        file_contents = _load_relevant_files(requirement, file_tree_str, file_lookup)
        combined = ask_claude(analysis_and_brd_prompt(requirement, file_tree_str, file_contents, ui_needed=ui_needed))
        system_analysis, brd = _split_analysis_and_brd(combined)

    needs_clarification = _has_open_questions(brd)
    resolution_tier = _parse_resolution_tier(brd)
    config_only = resolution_tier in ("config", "workaround")

    save_session(session_id, {
        "requirement": requirement,
        "issue_title": requirement.split("\n")[0].strip(),
        "repo_path": repo_path,
        "system_analysis": system_analysis,
        "brd_draft": brd,
        "needs_clarification": needs_clarification,
        "issue_type": issue_type,
        "resolution_tier": resolution_tier,
        "config_only": config_only,
        "ui_needed": ui_needed,
        "stage": "ba",
    })

    return {
        "system_analysis": system_analysis,
        "brd": brd,
        "needs_clarification": needs_clarification,
        "resolution_tier": resolution_tier,
        "config_only": config_only,
        "ui_needed": ui_needed,
        "issue_type": issue_type,
        "next_stage": "ba (answer questions)" if needs_clarification else "sa",
    }
