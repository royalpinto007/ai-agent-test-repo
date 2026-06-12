import re
import logging
from shared.claude import ask_claude
from shared.utils import get_file_tree, read_file, write_file, run_git, run_tests, identify_relevant_files, create_pull_request, check_pr_file_overlap, get_github_issue_state
from shared.session import save_session, load_session
from agents.dev.prompts import codebase_understanding_prompt, implementation_prompt, retry_prompt, redo_prompt

MAX_RETRIES = 3
log = logging.getLogger("dev")


def _clean_path(path):
    return path.strip().strip('`*\'" ').strip()


def parse_output(output):
    """Parse the model's response into a list of file operations:
    {type:'edit', path, search, replace} for in-place edits of existing files, and
    {type:'new', path, content} for brand-new files. Edits preserve everything
    they don't touch, eliminating the whole-file-rewrite content loss."""
    ops = []
    for path, search, replace in re.findall(
            r'EDIT:\s*(.+?)\n<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE', output, re.DOTALL):
        path = _clean_path(path)
        if path:
            ops.append({"type": "edit", "path": path, "search": search, "replace": replace})
    for path, content in re.findall(r'NEWFILE:\s*(.+?)\n```(?:\w+)?\n(.*?)```', output, re.DOTALL):
        path = _clean_path(path)
        if path:
            ops.append({"type": "new", "path": path, "content": content.strip()})

    impact = ""
    m = re.search(r'## Impact Analysis\n(.*?)(?=##|\Z)', output, re.DOTALL)
    if m:
        impact = m.group(1).strip()

    pr_description = ""
    m = re.search(r'## PR Description\n(.*?)(?=##|\Z)', output, re.DOTALL)
    if m:
        pr_description = m.group(1).strip()

    summary = ""
    m = re.search(r'## Summary\n(.*?)(?=##|\Z)', output, re.DOTALL)
    if m:
        summary = m.group(1).strip()

    return ops, impact, pr_description, summary


def _clean_title(title):
    """Trim a title that swallowed the body's first markdown heading
    (e.g. 'Show order reference ... ## What are we building?') to just the title."""
    t = (title or "").split("\n")[0]
    t = re.split(r'\s+#{1,6}\s', t)[0]
    return t.strip()


# Phrases that signal the model returned an explanation instead of file content.
_PROSE_MARKERS = (
    "no changes required", "no change required", "no changes needed",
    "no modifications needed", "the implementation is already",
    "already correct and complete", "here is the confirmed file",
    "here is the unchanged file",
)


def _apply_edit(existing, search, replace):
    """Apply a SEARCH/REPLACE edit. Tries exact match first, then a
    whitespace-normalized line match (tolerant of the indentation/trailing-space
    drift small models introduce) — but still requires the block to exist exactly
    once, so it never edits the wrong place. Returns (new_content, reason)."""
    if not search.strip():
        return None, "empty SEARCH"
    c = existing.count(search)
    if c == 1:
        return existing.replace(search, replace, 1), None
    if c > 1:
        return None, f"SEARCH not unique ({c} exact matches)"
    # Normalized fallback: compare lines with leading/trailing whitespace removed.
    ex_lines = existing.split("\n")
    s_lines = [ln.strip() for ln in search.split("\n")]
    while s_lines and s_lines[0] == "":
        s_lines.pop(0)
    while s_lines and s_lines[-1] == "":
        s_lines.pop()
    if not s_lines:
        return None, "empty SEARCH after normalize"
    hits = [i for i in range(len(ex_lines) - len(s_lines) + 1)
            if [ex_lines[i + j].strip() for j in range(len(s_lines))] == s_lines]
    if len(hits) == 1:
        i = hits[0]
        new_lines = ex_lines[:i] + replace.split("\n") + ex_lines[i + len(s_lines):]
        return "\n".join(new_lines), None
    if len(hits) > 1:
        return None, f"SEARCH not unique ({len(hits)} normalized matches)"
    return None, "SEARCH text not found"


def _safe_to_write(repo_path, path, new_content):
    """Guard against the two destructive failure modes seen in practice:
    (1) the model writes prose ('No changes required...') as if it were the file;
    (2) it regenerates an existing file but drops most of its content (e.g. a
    lang file losing strings). Returns (ok, reason)."""
    head = new_content.strip()[:300].lower()
    if any(m in head for m in _PROSE_MARKERS):
        return False, "content reads as an explanation, not file contents"
    existing = read_file(repo_path, path)
    if existing is not None and len(existing) > 500 and len(new_content) < 0.7 * len(existing):
        return False, (f"rewrite is {len(new_content)}B vs existing {len(existing)}B "
                       f"(<70%) — likely accidental content loss")
    return True, ""


def run(session_id, issue_title, issue_description, repo_path, branch_name=None, redo_instructions=None, test_command=None, main_branch="main"):
    session = load_session(session_id) or {}
    issue_title = _clean_title(issue_title)

    # If PM identified a specific code repo to work on (requirements-repo flow),
    # override repo_path, test_command, and main_branch from it.
    target_repo = session.get("target_repo")
    if target_repo and isinstance(target_repo, dict):
        repo_path = repo_path or target_repo.get("repo_path") or session.get("repo_path")
        test_command = test_command or target_repo.get("test_command")
        main_branch = target_repo.get("main_branch", main_branch)
    else:
        repo_path = repo_path or session.get("repo_path")

    # ── Dependency check ─────────────────────────────────────────────────────
    # If the PM created sub-issues and the current task declares dependencies,
    # block until those issues are closed on GitHub.
    import os as _os
    token = _os.environ.get("GITHUB_TOKEN", "")
    pm_tasks = session.get("pm_tasks", [])
    # Find this issue's task by matching issue number from session_id
    current_issue_num = session_id.split("-")[-1] if "-" in session_id else None
    current_task = next(
        (t for t in pm_tasks if str(t.get("issue_number")) == str(current_issue_num)), None
    )
    if current_task and token:
        depends_raw = current_task.get("depends_on", "None") or "None"
        if depends_raw.lower() not in ("none", ""):
            # Extract task numbers from "Task 1, Task 2" style strings
            import re as _re
            dep_nums = _re.findall(r'\d+', depends_raw)
            blocked_by = []
            for dep_num in dep_nums:
                dep_task = next((t for t in pm_tasks if str(t.get("issue_number", "")) == dep_num
                                  or t.get("title", "").startswith(f"Task {dep_num}")), None)
                if dep_task and dep_task.get("issue_number"):
                    import subprocess as _sp2
                    remote = _sp2.run(["git", "remote", "get-url", "origin"],
                                      cwd=repo_path, capture_output=True, text=True).stdout.strip()
                    remote = remote.replace("git@github.com:", "https://github.com/")
                    parts = remote.rstrip(".git").rstrip("/").split("/")
                    dep_owner, dep_repo = parts[-2], parts[-1]
                    state = get_github_issue_state(dep_owner, dep_repo, dep_task["issue_number"], token)
                    if state != "closed":
                        blocked_by.append({"issue": dep_task["issue_number"], "title": dep_task.get("title", ""), "state": state})
            if blocked_by:
                return {
                    "blocked": True,
                    "blocked_by": blocked_by,
                    "issue_title": issue_title,
                    "error": "This task has unresolved dependencies. Close the blocking issues first.",
                    "next_stage": "dev (blocked by dependencies)",
                }

    if not branch_name:
        issue_number = session_id.split("-")[-1] if "-" in session_id else session_id
        slug = re.sub(r'[^a-z0-9]+', '-', issue_title.lower()).strip('-')
        slug = '-'.join(slug.split('-')[:4])  # max 4 words
        branch_name = f"ai/{issue_number}-{slug}"
    test_command = test_command or session.get("test_command")
    pm_tasks = session.get("pm_output", "")

    file_tree = get_file_tree(repo_path)
    file_tree_str = "\n".join(file_tree)

    seed_files, affected_files = identify_relevant_files(issue_title, issue_description, repo_path, file_tree)

    # Bound the context we feed the model: real repos (e.g. IOMAD plugins) can
    # blow past the 200k-token limit if we paste every matched file in full.
    # Prioritise seed files (the model's own picks) over grep-matched ones,
    # truncate large files, and cap the total payload with headroom for the
    # prompt scaffolding, file tree, and the model's output.
    MAX_DEV_FILES = 25
    # Files the model edits must be shown in full (truncation below an anchor
    # would break exact SEARCH matching), so allow a larger per-file slice.
    PER_FILE_CHARS = 45000
    TOTAL_CHARS = 340000  # ~85k tokens, leaving headroom under the 200k limit
    ordered = seed_files + [f for f in affected_files if f not in seed_files]
    file_contents = {}
    total = 0
    for f in ordered:
        if len(file_contents) >= MAX_DEV_FILES or total >= TOTAL_CHARS:
            break
        content = read_file(repo_path, f)
        if not content:
            continue
        if len(content) > PER_FILE_CHARS:
            content = content[:PER_FILE_CHARS] + "\n\n... [truncated for length]"
        if total + len(content) > TOTAL_CHARS:
            continue  # skip this one, try smaller later files
        file_contents[f] = content
        total += len(content)

    # Phase 1: understand the codebase before writing any code
    codebase_analysis = session.get("codebase_analysis") or ask_claude(
        codebase_understanding_prompt(issue_title, issue_description, file_contents, file_tree_str)
    )

    # Phase 2: implement with full context (or redo with extra instructions)
    previous_output = session.get("dev_raw_output", "")
    if redo_instructions and previous_output:
        output = ask_claude(redo_prompt(issue_title, previous_output, redo_instructions, codebase_analysis))
    else:
        output = ask_claude(
            implementation_prompt(
                issue_title, issue_description, file_contents,
                affected_files, file_tree_str, codebase_analysis, pm_tasks
            )
        )

    attempts = []
    changed = []
    for attempt in range(1, MAX_RETRIES + 1):
        file_ops, impact, pr_description, summary = parse_output(output)

        try:
            run_git(["checkout", main_branch], cwd=repo_path)
            run_git(["pull"], cwd=repo_path)
            if attempt == 1:
                # Start clean: drop any stale local branch from a previous failed
                # run so retries don't stack a second commit on the same branch.
                try:
                    run_git(["branch", "-D", branch_name], cwd=repo_path)
                except RuntimeError:
                    pass
                run_git(["checkout", "-b", branch_name], cwd=repo_path)
            else:
                run_git(["checkout", branch_name], cwd=repo_path)
        except RuntimeError:
            run_git(["checkout", branch_name], cwd=repo_path)

        # Apply each op. Edits are surgical (exact SEARCH/REPLACE) so untouched
        # code is preserved by construction — no whole-file rewrites. New files
        # still pass the prose/empty guard.
        log.warning("dev: parsed %d op(s): %s", len(file_ops),
                    [(o["type"], o["path"]) for o in file_ops])
        applied, failed, skipped = [], [], []
        for op in file_ops:
            path = op["path"]
            if op["type"] == "new":
                ok, reason = _safe_to_write(repo_path, path, op["content"])
                if not ok:
                    skipped.append((path, reason)); log.warning("dev: skipped NEWFILE %s — %s", path, reason); continue
                write_file(repo_path, path, op["content"]); applied.append(path)
            else:  # edit
                existing = read_file(repo_path, path)
                if existing is None:
                    failed.append((path, "file not found for EDIT")); continue
                new_content, reason = _apply_edit(existing, op["search"], op["replace"])
                if new_content is None:
                    failed.append((path, reason)); continue
                write_file(repo_path, path, new_content); applied.append(path)
        changed = sorted(set(applied))
        if failed:
            log.warning("dev: %d edit(s) did not apply: %s", len(failed), failed)

        test_passed, test_output = run_tests(repo_path, test_command)
        attempts.append({"attempt": attempt, "test_passed": test_passed, "test_output": test_output})

        # Success only when something actually applied, every edit landed, and
        # tests pass. Otherwise retry with a pointed nudge.
        if test_passed and changed and not failed:
            break
        if attempt < MAX_RETRIES:
            if failed:
                nudge = ("These EDITs did not apply: "
                         + "; ".join(f"{p} ({why})" for p, why in failed)
                         + ". Re-copy each SEARCH block VERBATIM from the CURRENT FILE CONTENTS "
                           "(exact characters and indentation), with enough surrounding lines to be "
                           "unique in that file. Keep edits minimal.")
                output = ask_claude(retry_prompt(issue_title, output, nudge, attempt, codebase_analysis))
            elif not changed:
                nudge = ("Your response produced no applicable changes. Output minimal "
                         "EDIT (SEARCH/REPLACE) blocks for existing files — SEARCH copied verbatim "
                         "from the current file contents — and NEWFILE blocks for new files, using "
                         "the exact format. No whole-file rewrites.")
                output = ask_claude(retry_prompt(issue_title, output, nudge, attempt, codebase_analysis))
            else:
                output = ask_claude(retry_prompt(issue_title, output, test_output, attempt, codebase_analysis))

    final = attempts[-1]

    # If nothing applied, don't push an empty branch (which 422s on PR creation).
    # Surface it as a dev failure so the pipeline flags it for a redo.
    if not changed:
        save_session(session_id, {
            "stage": "dev",
            "repo_path": repo_path,
            "branch": branch_name,
            "issue_title": issue_title,
            "codebase_analysis": codebase_analysis,
            "dev_raw_output": output,
            "test_passed": False,
            "files_changed": [],
            "attempts": len(attempts),
        })
        return {
            "branch": branch_name,
            "issue_title": issue_title,
            "test_passed": False,
            "files_changed": [],
            "attempts": len(attempts),
            "error": "Dev produced no applicable changes after all attempts (no EDIT/NEWFILE blocks applied — likely SEARCH text didn't match). Re-run dev or use `redo-dev: <instructions>`.",
            "next_stage": "dev (no files generated)",
        }

    if not final["test_passed"]:
        save_session(session_id, {
            "stage": "dev",
            "repo_path": repo_path,
            "branch": branch_name,
            "issue_title": issue_title,
            "codebase_analysis": codebase_analysis,
            "dev_raw_output": output,
            "test_passed": False,
            "test_output": final["test_output"],
            "attempts": len(attempts),
        })
        return {
            "branch": branch_name,
            "issue_title": issue_title,
            "test_passed": False,
            "test_output": final["test_output"],
            "attempts": len(attempts),
            "error": f"Tests failed after {len(attempts)} attempt(s). Use `redo-dev: <instructions>` to fix, or check the branch manually.",
            "next_stage": "dev (tests failed)",
        }

    all_files = changed
    for path in all_files:
        run_git(["add", path], cwd=repo_path)

    import subprocess as _sp
    commit_result = _sp.run(
        ["git", "commit", "-m", f"feat: {issue_title} (attempts: {len(attempts)}, tests: {'pass' if final['test_passed'] else 'fail'})"],
        cwd=repo_path, capture_output=True, text=True
    )
    _commit_out = commit_result.stdout + commit_result.stderr
    # git reports an empty commit several ways depending on staging state;
    # treat all of them as a benign no-op rather than crashing the stage.
    _benign_commit = (
        "nothing to commit",
        "no changes added to commit",
        "nothing added to commit",
    )
    if commit_result.returncode != 0 and not any(b in _commit_out for b in _benign_commit):
        raise RuntimeError(f"git commit failed: {_commit_out.strip()}")
    run_git(["push", "-u", "origin", branch_name], cwd=repo_path)

    issue_number = session_id.split("-")[-1] if "-" in session_id else None
    pr_url = None
    pr_error = None
    try:
        pr_url = create_pull_request(repo_path, branch_name, issue_title, issue_number, pr_description, summary, main_branch)
    except RuntimeError as e:
        pr_error = str(e)

    # Check for file overlap with other open PRs
    import os as _os
    token = _os.environ.get("GITHUB_TOKEN", "")
    conflicting_prs = check_pr_file_overlap(repo_path, branch_name, token)

    result = {
        "branch": branch_name,
        "issue_title": issue_title,
        "codebase_analysis": codebase_analysis,
        "impact_analysis": impact,
        "pr_description": pr_description,
        "summary": summary,
        "files_changed": changed,
        "test_files": [p for p in changed if "test" in p.lower() or "spec" in p.lower()],
        "affected_files": affected_files,
        "test_passed": final["test_passed"],
        "test_output": final["test_output"],
        "attempts": len(attempts),
        "pr_url": pr_url,
        "pr_error": pr_error,
        "conflicting_prs": conflicting_prs,
        "next_stage": "review",
    }

    save_session(session_id, {**result, "stage": "dev", "repo_path": repo_path, "dev_raw_output": output, "main_branch": main_branch})
    return result
