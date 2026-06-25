import os
from shared.claude import ask_claude
from shared.utils import get_file_tree, read_file, grep_repo, grep_repo_fast, run_git
from shared.session import save_session, load_session
from shared.config import get_code_repos, is_requirements_repo, all_repos
from agents.ba.prompts import (
    analysis_and_brd_prompt,
    minimal_brd_prompt,
    minimal_code_brd_prompt,
    complexity_classify_prompt,
    followup_prompt,
    revision_prompt,
    bug_analysis_prompt,
)

MAX_FILES_TO_READ = 15
# A code repo with more source files than this is not dumped wholesale into the
# prompt (Moodle/IOMAD core alone is ~21k files). Instead we surface only the
# files matching the requirement's keywords, found via a fast system grep.
_BIG_REPO_FILES = 400
_BIG_REPO_MATCHES = 40


def _keywords(requirement):
    """Distinctive words from the requirement to grep large repos for."""
    import re
    stop = {"this", "that", "with", "from", "have", "should", "would", "will",
            "when", "what", "which", "their", "there", "page", "site", "user",
            "users", "account", "accounts", "able", "only", "create", "created",
            "form", "system", "feature", "into", "they", "them", "your"}
    words, seen = [], set()
    for w in re.findall(r"[A-Za-z]{4,}", requirement or ""):
        lw = w.lower()
        if lw in stop or lw in seen:
            continue
        seen.add(lw)
        words.append(lw)
    return words[:8]


def _build_repo_context(session_id, repo_path, requirement=""):
    """Return (file_tree_str, file_lookup) for either the single repo or all code repos.

    file_lookup is {file_path_as_seen_by_model: (real_repo_path, real_relative_path)}
    so when Claude asks for a file by its slug-prefixed path we know where to read it from.

    For requirements repos we span all registered code repos. Repos under
    _BIG_REPO_FILES are listed in full; larger ones (e.g. core) are represented
    only by their keyword-matching files so the prompt stays bounded while still
    grounding the BRD in real code.
    """
    # Decide requirements-vs-code by matching the repo_path we were handed against
    # repos.json. Recovering owner/repo from the session_id by string surgery is
    # unreliable when the owner itself contains hyphens (e.g.
    # "Health-and-Safety-Solution"), which would leave grounding silently off.
    on_requirements_repo = False
    if repo_path:
        target = os.path.realpath(repo_path)
        for _, c in all_repos().items():
            cp = c.get("repo_path")
            if cp and os.path.realpath(cp) == target:
                on_requirements_repo = bool(c.get("requirements_repo"))
                break

    tree_lines = []
    lookup = {}
    keywords = _keywords(requirement)

    if on_requirements_repo:
        for slug, cfg in get_code_repos().items():
            rp = cfg.get("repo_path", "")
            if not (rp and os.path.isdir(rp)):
                continue
            files = get_file_tree(rp)
            if len(files) <= _BIG_REPO_FILES:
                for f in files:
                    seen = f"{slug}/{f}"
                    tree_lines.append(seen)
                    lookup[seen] = (rp, f)
            else:
                # Large repo: don't dump its tree — surface only keyword matches.
                matched = grep_repo_fast(rp, keywords, max_results=_BIG_REPO_MATCHES) if keywords else []
                tree_lines.append(
                    f"# {slug}: large repo ({len(files)} files) — showing only files "
                    f"matching the requirement; grep for more if needed")
                for f in matched:
                    seen = f"{slug}/{f}"
                    tree_lines.append(seen)
                    lookup[seen] = (rp, f)
    else:
        if repo_path and os.path.isdir(repo_path):
            files = get_file_tree(repo_path)
            if len(files) <= _BIG_REPO_FILES:
                for f in files:
                    tree_lines.append(f)
                    lookup[f] = (repo_path, f)
            else:
                # Large repo (e.g. core Dolibarr ~21k files): don't dump the whole
                # tree (the prompt would overflow) — surface only keyword matches.
                matched = grep_repo_fast(repo_path, keywords, max_results=_BIG_REPO_MATCHES) if keywords else []
                tree_lines.append(
                    f"# large repo ({len(files)} files) — showing only files matching "
                    f"the issue keywords; grep for more if needed")
                for f in matched:
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


def _repo_target(slug, cfg):
    return {
        "slug": slug,
        "repo_path": cfg.get("repo_path", ""),
        "test_command": cfg.get("test_command"),
        "main_branch": cfg.get("main_branch", "main"),
        "dev_mode": cfg.get("dev_mode"),
        "skill": cfg.get("skill"),
        "dol_htdocs": cfg.get("dol_htdocs"),
        "mcp_config": cfg.get("mcp_config"),
    }


def _detect_new_module(requirement):
    """Detect an explicit 'new module' request and return a to-be-created
    target_repo (create=True) for it; else None.

    Deliberately requires an EXPLICIT, named signal so we never auto-create a repo
    from vague prose. Recognised forms (case-insensitive), the captured group is
    the module name:
      - 'New module: <Name>'  /  'New module - <Name>'
      - 'create a new [custom] module named|called <Name>'
    """
    import re
    req = requirement or ""
    # module names are single tokens (e.g. CamelCase) — capture one token, no spaces
    m = re.search(r'(?:^|\n)\s*new module\s*[:\-]\s*["`]?([A-Za-z][A-Za-z0-9_-]{1,40})', req, re.IGNORECASE)
    if not m:
        m = re.search(r'\bnew\s+(?:custom\s+)?module\s+(?:named|called)\s+["`]?([A-Za-z][A-Za-z0-9_-]{1,40})',
                      req, re.IGNORECASE)
    if not m:
        return None
    from shared.provision import module_target
    return module_target(m.group(1).strip())


def _detect_component(requirement):
    """Resolve which registered code repo a requirement targets, so Dev/Review run
    against — and open the PR in — that repo. Returns a target_repo dict or None
    (None => PM decides).

    Two signals, in order:
    1. An explicit 'Affected component' issue-form field, if the template has one.
    2. Fallback: a known code-repo slug named anywhere in the issue text. The
       simplified templates dropped the component dropdown, so a requirement that
       names its module/repo in prose (e.g. 'dolibarr_custom_advancetools') should
       still route. Prefer the LONGEST matching short-name so a specific module
       wins over a generic parent like 'dolibarr'.
    """
    import re
    req = requirement or ""
    repos = get_code_repos()

    m = re.search(r'affected component[^\n]*\n+\s*([^\n]+)', req, re.IGNORECASE)
    if m:
        val = m.group(1).strip().strip("`").lower()
        if val and not val.startswith(("not sure", "none", "n/a", "_no response_", "unsure")):
            for slug, cfg in repos.items():
                if slug.split("/")[-1].lower() == val:
                    return _repo_target(slug, cfg)

    rl = req.lower()
    best = None
    for slug, cfg in repos.items():
        short = slug.split("/")[-1].lower()
        if not short:
            continue
        # whole-token match: '-'/'_'/word chars on either side don't count as a boundary
        if re.search(r'(?<![\w-])' + re.escape(short) + r'(?![\w-])', rl):
            if best is None or len(short) > len(best[0].split("/")[-1]):
                best = (slug, cfg)
    if best:
        return _repo_target(*best)
    return None


def _repo_blurb(cfg):
    """A one-line description of a code repo, from its README heading or module
    descriptor, to help the model pick the right repo. Best-effort, cheap."""
    import os, glob, re
    p = cfg.get("repo_path", "")
    if not p:
        return ""
    rp = os.path.join(p, "README.md")
    if os.path.isfile(rp):
        try:
            with open(rp, errors="ignore") as f:
                for line in f:
                    s = line.strip().lstrip("#").strip()
                    if len(s) >= 12 and "license" not in s.lower():
                        return s[:160]
        except Exception:
            pass
    for desc in glob.glob(os.path.join(p, "core/modules/mod*.class.php")):
        try:
            with open(desc, errors="ignore") as f:
                m = re.search(r"this->description\s*=\s*['\"]([^'\"]{6,})", f.read())
                if m:
                    return m.group(1)[:160]
        except Exception:
            pass
    return ""


def _select_repo(requirement):
    """When no repo is explicitly named, let the model pick the single most
    relevant code repo from the (small) registered catalog. Returns a target_repo
    or None. This is what lets a bug like 'SO billed but shipment not billed' route
    to the right repo (e.g. core dolibarr) without a manual hint."""
    repos = get_code_repos()
    if not repos:
        return None
    listing = "\n".join(f"- {slug}: {(_repo_blurb(cfg) or '(no description)')}" for slug, cfg in repos.items())
    prompt = f"""You are routing a software issue to the ONE code repository whose source must be inspected to address it.

ISSUE:
{(requirement or '')[:2500]}

AVAILABLE REPOSITORIES (slug: what it is):
{listing}

Rules:
- Pick exactly ONE repository slug from the list above — the one whose code most likely contains the behaviour to fix.
- Core ERP behaviour (sales orders, shipments/expeditions, invoices, payments, stock, products, users) lives in the core Dolibarr repository unless a custom module clearly owns it.
- Answer with ONLY the slug on a single line, or the word NONE if it is genuinely impossible to tell."""
    try:
        ans = ask_claude(prompt).strip()
    except Exception:
        return None
    low = ans.lower()
    # exact slug or short-name match
    best = None
    for slug, cfg in repos.items():
        short = slug.split("/")[-1].lower()
        if slug.lower() in low or low == short or (short and short in low):
            if best is None or len(short) > len(best[0].split("/")[-1]):
                best = (slug, cfg)
    return _repo_target(*best) if best else None


def run(session_id, requirement, repo_path, clarification_answers=None, human_feedback=None, issue_type=None):
    session = load_session(session_id) or {}
    requirement = requirement or session.get("requirement", "")
    issue_type = issue_type or session.get("issue_type", "Feature")

    if not requirement:
        raise ValueError("requirement is required")

    ui_needed = _detect_ui_needed(requirement)

    # Resolve which code repo this issue concerns BEFORE analysing, so BA reads the
    # real source (not the requirements repo). Order: explicit new-module signal ->
    # repo slug named in the text -> model picks the best match from the catalog.
    # For an existing repo, analyse against it; a to-be-created module (create=True)
    # has no code yet, so BA analyses from the requirement text and Dev provisions it.
    import os as _os
    target_repo = _detect_new_module(requirement) or _detect_component(requirement) or _select_repo(requirement)
    if (target_repo and not target_repo.get("create")
            and target_repo.get("repo_path") and _os.path.isdir(target_repo["repo_path"])):
        repo_path = target_repo["repo_path"]

    # Pull latest before analysing so we read current code.
    try:
        run_git(["pull"], cwd=repo_path)
    except Exception:
        pass

    file_tree_str, file_lookup = _build_repo_context(session_id, repo_path, requirement)

    if issue_type == "Bug":
        file_contents = _load_relevant_files(requirement, file_tree_str, file_lookup)
        issue_title = requirement.split("\n")[0].strip()
        # Check the upstream Dolibarr repo for a possibly-known bug, so the report
        # can cite it instead of (or alongside) analysing from scratch.
        upstream_issues = []
        try:
            import os as _osu, re as _reu
            from shared.utils import search_github_issues
            _terms = " ".join(dict.fromkeys(_reu.findall(r'[A-Za-z]{4,}', issue_title)))[:120]
            upstream_issues = search_github_issues(
                _osu.environ.get("UPSTREAM_DOLIBARR_REPO", "Dolibarr/dolibarr"),
                _terms, _osu.environ.get("GITHUB_TOKEN", ""), 6)
        except Exception:
            upstream_issues = []
        brd = ask_claude(bug_analysis_prompt(issue_title, requirement, file_contents, file_tree_str, upstream_issues=upstream_issues))
        system_analysis = ""

        bug_session = {
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
        }
        if target_repo:
            bug_session["target_repo"] = target_repo
        save_session(session_id, bug_session)

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
        # Ground the BRD in the live instance's actual config when available
        # (empty string if MOODLE_LIVE_SSH isn't configured or the box is unreachable).
        live_config = ""
        try:
            from shared import moodle_live
            live_config = moodle_live.live_state_for(requirement, ask_claude)
        except Exception:
            live_config = ""
        # Triage on two axes: config-vs-code and small-vs-large.
        #  - config  -> terse how-to, pipeline short-circuits (no PR).
        #  - small   -> terse BRD, but a real code change (full Dev->PR path).
        #  - large   -> full BRD. UI-mockup requests always take the full path.
        complexity = ""
        if not ui_needed:
            try:
                complexity = ask_claude(complexity_classify_prompt(requirement)).strip().lower()
            except Exception:
                complexity = ""
        if "config" in complexity:
            brd = ask_claude(minimal_brd_prompt(requirement, file_contents, live_config=live_config))
            system_analysis = ""
        elif "small" in complexity:
            brd = ask_claude(minimal_code_brd_prompt(requirement, file_contents, live_config=live_config))
            system_analysis = ""
        else:
            combined = ask_claude(analysis_and_brd_prompt(
                requirement, file_tree_str, file_contents, ui_needed=ui_needed, live_config=live_config))
            system_analysis, brd = _split_analysis_and_brd(combined)

    needs_clarification = _has_open_questions(brd)
    resolution_tier = _parse_resolution_tier(brd)
    config_only = resolution_tier in ("config", "workaround")

    # target_repo was resolved at the top (used to pick the source BA analysed and
    # to route downstream Dev/Review + the PR).
    session_update = {
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
    }
    if target_repo:
        session_update["target_repo"] = target_repo
    save_session(session_id, session_update)

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
