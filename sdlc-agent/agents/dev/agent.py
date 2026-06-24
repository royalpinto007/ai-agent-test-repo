import re
import logging
import subprocess
from shared.claude import ask_claude, ask_claude_agentic
from shared.utils import get_file_tree, read_file, write_file, run_git, run_tests, identify_relevant_files, create_pull_request, check_pr_file_overlap, get_github_issue_state, grep_repo_fast
from shared.session import save_session, load_session
from agents.dev.prompts import (
    codebase_understanding_prompt, implementation_prompt, retry_prompt, redo_prompt,
    agentic_implementation_prompt, agentic_retry_prompt,
)

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
            # Path is the FIRST line after EDIT: only — the model sometimes adds
            # prose between the path line and the SEARCH marker, so skip any
            # intervening lines (.*?) rather than folding them into the path.
            r'EDIT:[ \t]*([^\n]+)\n.*?[<]{3,}\s*SEARCH\s*\n(.*?)\n[=]{3,}\s*\n(.*?)\n[>]{3,}\s*REPLACE',
            output, re.DOTALL | re.IGNORECASE):
        path = _clean_path(path)
        if path:
            ops.append({"type": "edit", "path": path, "search": search, "replace": replace})
    for path, content in re.findall(r'NEWFILE:[ \t]*([^\n]+)\n```(?:\w+)?\n(.*?)```', output, re.DOTALL):
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

    # New-module request (BA flagged target_repo with create=True): stand the repo
    # up — create it on GitHub, clone it, bind-mount into the live htdocs/custom,
    # and register it in repos.json — before anything touches repo_path.
    if isinstance(target_repo, dict) and target_repo.get("create"):
        import os as _osp
        from shared.provision import provision_module
        target_repo = provision_module(target_repo, _osp.environ.get("GITHUB_TOKEN", ""))
        repo_path = target_repo.get("repo_path") or repo_path
        test_command = test_command or target_repo.get("test_command")
        main_branch = target_repo.get("main_branch", main_branch)
        session["target_repo"] = target_repo
        save_session(session_id, {"target_repo": target_repo, "repo_path": repo_path})

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

    # Agentic (skill-driven) path — opt-in per repo via repos.json
    # ("dev_mode": "agentic"). Used for the Dolibarr/Thrive code repo so the
    # dolibarr-dev skill drives the change with tools + MCP against the live
    # install, instead of pasting whole files into a text-only prompt. Any repo
    # without this flag (e.g. the Moodle/IOMAD acorn repos) keeps the text path
    # below unchanged.
    if _is_agentic(target_repo):
        return _run_agentic(
            session_id, issue_title, issue_description, repo_path, branch_name,
            main_branch, test_command, pm_tasks, redo_instructions,
            target_repo if isinstance(target_repo, dict) else {},
        )

    file_tree = get_file_tree(repo_path)
    # On very large repos (e.g. Moodle/IOMAD core, ~21k files) dumping the whole
    # tree into file-selection is unreliable — the model can't reliably pick the
    # right file, so its SEARCH anchors miss. Narrow to the files the issue/BRD
    # actually name (by basename) plus keyword grep matches, so the target file is
    # found and read in full.
    if len(file_tree) > 800:
        _text = (issue_description or "") + "\n" + session.get("brd_draft", "") + "\n" + session.get("sdd", "")
        _basenames = {p.rsplit("/", 1)[-1] for p in re.findall(r'[\w./-]+\.php', _text)}
        cand = [f for f in file_tree if f.rsplit("/", 1)[-1] in _basenames]
        _kws = [w.lower() for w in re.findall(r'[A-Za-z]{5,}', issue_title or "")][:6]
        for f in grep_repo_fast(repo_path, _kws, max_results=60):
            if f not in cand:
                cand.append(f)
        if cand:
            file_tree = sorted(set(cand))[:150]
            log.warning("dev: large repo (%s files) narrowed to %d candidate file(s)", "many", len(file_tree))
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
    # Track the BEST attempt across retries, not the last one. A retry that
    # regresses (e.g. the model returns fewer/no ops on the second pass) must
    # not discard a better earlier attempt's applied edits.
    best = None
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
        applied_content = {}
        for op in file_ops:
            path = op["path"]
            if op["type"] == "new":
                ok, reason = _safe_to_write(repo_path, path, op["content"])
                if not ok:
                    skipped.append((path, reason)); log.warning("dev: skipped NEWFILE %s — %s", path, reason); continue
                write_file(repo_path, path, op["content"]); applied.append(path); applied_content[path] = op["content"]
            else:  # edit
                existing = read_file(repo_path, path)
                if existing is None:
                    failed.append((path, "file not found for EDIT")); continue
                new_content, reason = _apply_edit(existing, op["search"], op["replace"])
                if new_content is None:
                    failed.append((path, reason)); continue
                write_file(repo_path, path, new_content); applied.append(path); applied_content[path] = new_content
        changed = sorted(set(applied))
        if failed:
            log.warning("dev: %d edit(s) did not apply: %s", len(failed), failed)

        # Lint the files we changed: fail only on NEW problems (syntax errors, or
        # MORE coding-standard errors than the base had) so we don't choke on a
        # repo's pre-existing violations. No-op if php/phpcs aren't on the box.
        lint_problems = []
        if changed:
            from shared import lint
            def _orig(p):
                r = subprocess.run(["git", "show", f"{main_branch}:{p}"], cwd=repo_path,
                                   capture_output=True, text=True)
                return r.stdout if r.returncode == 0 else None
            lint_problems = lint.lint_changed(_orig, applied_content)
            if lint_problems:
                log.warning("dev: lint problems introduced: %s", lint_problems)

        test_passed, test_output = run_tests(repo_path, test_command)
        attempts.append({"attempt": attempt, "test_passed": test_passed, "test_output": test_output,
                         "lint_problems": lint_problems})

        # Snapshot this attempt and keep it if it's the best so far. Ranking:
        # tests passing first, then most edits applied, then fewest failed, then
        # fewest new lint problems. This is what we'll ship after the loop, so a
        # later empty/worse retry can't wipe a good earlier attempt.
        snapshot = {
            "changed": changed, "failed": failed, "applied_content": dict(applied_content),
            "lint_problems": lint_problems, "test_passed": test_passed, "test_output": test_output,
            "output": output, "impact": impact, "pr_description": pr_description, "summary": summary,
        }
        score = (1 if test_passed else 0, len(changed), -len(failed), -len(lint_problems))
        if changed and (best is None or score > best["score"]):
            best = {**snapshot, "score": score}

        # Success only when something applied, every edit landed, tests pass, and
        # the change introduced no new syntax/standards errors. Else retry.
        if test_passed and changed and not failed and not lint_problems:
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
            elif lint_problems:
                nudge = ("Your change introduced new problems on the files you edited: "
                         + "; ".join(f"{p}: {why}" for p, why in lint_problems)
                         + ". Fix them — match the existing code style (indentation, spacing, "
                           "braces) exactly and don't add violations. Keep the edit minimal.")
                output = ask_claude(retry_prompt(issue_title, output, nudge, attempt, codebase_analysis))
            else:
                output = ask_claude(retry_prompt(issue_title, output, test_output, attempt, codebase_analysis))

    # Prefer the best attempt over whatever the last retry happened to produce.
    failed_edits = []
    if best is not None:
        changed = best["changed"]
        applied_content = best["applied_content"]
        failed_edits = best["failed"]
        output = best["output"]
        impact, pr_description, summary = best["impact"], best["pr_description"], best["summary"]
        final = {"attempt": 0, "test_passed": best["test_passed"],
                 "test_output": best["test_output"], "lint_problems": best["lint_problems"]}
        # Re-stage the best attempt's content onto the branch — later retries may
        # have left the working tree in a worse state than `best` reflects.
        run_git(["checkout", main_branch], cwd=repo_path)
        try:
            run_git(["branch", "-D", branch_name], cwd=repo_path)
        except RuntimeError:
            pass
        run_git(["checkout", "-b", branch_name], cwd=repo_path)
        for _p, _c in applied_content.items():
            write_file(repo_path, _p, _c)
    else:
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

    if final.get("lint_problems"):
        save_session(session_id, {
            "stage": "dev", "repo_path": repo_path, "branch": branch_name,
            "issue_title": issue_title, "codebase_analysis": codebase_analysis,
            "dev_raw_output": output, "test_passed": final["test_passed"],
            "files_changed": changed, "attempts": len(attempts),
        })
        return {
            "branch": branch_name,
            "issue_title": issue_title,
            "test_passed": final["test_passed"],
            "files_changed": changed,
            "attempts": len(attempts),
            "error": ("Change introduces new syntax/coding-standard errors that would fail CI: "
                      + "; ".join(f"{p}: {why}" for p, why in final["lint_problems"])
                      + ". Use `redo-dev: <instructions>` to fix."),
            "next_stage": "dev (lint failed)",
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

    if failed_edits:
        note = ("\n\n---\n### ⚠️ Edits the agent could not auto-apply\n"
                "These changes from the plan did not match the current file and were left for a human to complete:\n"
                + "\n".join(f"- `{p}` — {why}" for p, why in failed_edits))
        pr_description = (pr_description or "") + note
        log.warning("dev: shipping best attempt with %d unapplied edit(s): %s", len(failed_edits), failed_edits)

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


# ── Agentic (skill-driven) Dev path ─────────────────────────────────────────

def _is_agentic(target_repo):
    """A repo opts into the tool-enabled dolibarr-dev path with
    {"dev_mode": "agentic"} (or "skill": "dolibarr-dev") in repos.json."""
    if not isinstance(target_repo, dict):
        return False
    return target_repo.get("dev_mode") == "agentic" or bool(target_repo.get("skill"))


def _changed_paths(repo_path):
    """Files modified/added in the working tree (the agent's edits), from
    `git status --porcelain`. Handles renames (takes the new path)."""
    r = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path,
                       capture_output=True, text=True)
    paths = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        p = line[3:]
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        paths.append(p.strip().strip('"'))
    return sorted(set(paths))


def _run_agentic(session_id, issue_title, issue_description, repo_path, branch_name,
                 main_branch, test_command, pm_tasks, redo_instructions, target_repo):
    """Tool-enabled implementation: Claude works directly in a checked-out branch
    using the dolibarr-dev skill, then the pipeline commits/pushes/opens the PR
    from the resulting working-tree diff. Mirrors the text path's commit/PR tail."""
    extra_dirs = [d for d in [target_repo.get("dol_htdocs")] if d]
    mcp_config = target_repo.get("mcp_config") or None

    # Fresh branch off main so the working-tree diff IS the change.
    run_git(["checkout", main_branch], cwd=repo_path)
    run_git(["pull"], cwd=repo_path)
    try:
        run_git(["branch", "-D", branch_name], cwd=repo_path)
    except RuntimeError:
        pass
    run_git(["checkout", "-b", branch_name], cwd=repo_path)

    prompt = agentic_implementation_prompt(issue_title, issue_description, pm_tasks, redo_instructions)
    output = ask_claude_agentic(prompt, cwd=repo_path, mcp_config=mcp_config, extra_dirs=extra_dirs)

    changed = _changed_paths(repo_path)
    attempts = 1

    def _lint_and_test(changed_now):
        from shared import lint
        applied_content = {}
        for p in changed_now:
            c = read_file(repo_path, p)
            if c is not None:
                applied_content[p] = c
        def _orig(p):
            r = subprocess.run(["git", "show", f"{main_branch}:{p}"], cwd=repo_path,
                               capture_output=True, text=True)
            return r.stdout if r.returncode == 0 else None
        problems = lint.lint_changed(_orig, applied_content) if applied_content else []
        passed, out = run_tests(repo_path, test_command)
        return problems, passed, out

    lint_problems, test_passed, test_output = ([], True, "") if not changed else _lint_and_test(changed)

    # One agentic retry on test failure — let the skill self-correct in place.
    if changed and not test_passed and MAX_RETRIES > 1:
        output = ask_claude_agentic(
            agentic_retry_prompt(issue_title, test_output),
            cwd=repo_path, mcp_config=mcp_config, extra_dirs=extra_dirs,
        )
        attempts += 1
        changed = _changed_paths(repo_path)
        if changed:
            lint_problems, test_passed, test_output = _lint_and_test(changed)

    impact, pr_description, summary = parse_output(output)[1:]

    base_session = {
        "stage": "dev", "repo_path": repo_path, "branch": branch_name,
        "issue_title": issue_title, "dev_raw_output": output,
        "files_changed": changed, "attempts": attempts, "main_branch": main_branch,
    }

    if not changed:
        save_session(session_id, {**base_session, "test_passed": False})
        return {"branch": branch_name, "issue_title": issue_title, "test_passed": False,
                "files_changed": [], "attempts": attempts,
                "error": "Dev (agentic) produced no working-tree changes. Re-run dev or use `redo-dev: <instructions>`.",
                "next_stage": "dev (no files generated)"}

    if not test_passed:
        save_session(session_id, {**base_session, "test_passed": False, "test_output": test_output})
        return {"branch": branch_name, "issue_title": issue_title, "test_passed": False,
                "test_output": test_output, "attempts": attempts,
                "error": f"Tests failed after {attempts} attempt(s). Use `redo-dev: <instructions>` to fix, or check the branch manually.",
                "next_stage": "dev (tests failed)"}

    if lint_problems:
        save_session(session_id, {**base_session, "test_passed": True})
        return {"branch": branch_name, "issue_title": issue_title, "test_passed": True,
                "files_changed": changed, "attempts": attempts,
                "error": ("Change introduces new syntax/coding-standard errors that would fail CI: "
                          + "; ".join(f"{p}: {why}" for p, why in lint_problems)
                          + ". Use `redo-dev: <instructions>` to fix."),
                "next_stage": "dev (lint failed)"}

    run_git(["add", "-A"], cwd=repo_path)
    commit_result = subprocess.run(
        ["git", "commit", "-m", f"feat: {issue_title} (agentic, tests: {'pass' if test_passed else 'fail'})"],
        cwd=repo_path, capture_output=True, text=True,
    )
    _commit_out = commit_result.stdout + commit_result.stderr
    _benign = ("nothing to commit", "no changes added to commit", "nothing added to commit")
    if commit_result.returncode != 0 and not any(b in _commit_out for b in _benign):
        raise RuntimeError(f"git commit failed: {_commit_out.strip()}")
    run_git(["push", "-u", "origin", branch_name], cwd=repo_path)

    issue_number = session_id.split("-")[-1] if "-" in session_id else None
    pr_url = pr_error = None
    try:
        pr_url = create_pull_request(repo_path, branch_name, issue_title, issue_number, pr_description, summary, main_branch)
    except RuntimeError as e:
        pr_error = str(e)

    import os as _os
    token = _os.environ.get("GITHUB_TOKEN", "")
    conflicting_prs = check_pr_file_overlap(repo_path, branch_name, token)

    result = {
        "branch": branch_name, "issue_title": issue_title,
        "impact_analysis": impact, "pr_description": pr_description, "summary": summary,
        "files_changed": changed,
        "test_files": [p for p in changed if "test" in p.lower() or "spec" in p.lower()],
        "test_passed": test_passed, "test_output": test_output, "attempts": attempts,
        "pr_url": pr_url, "pr_error": pr_error, "conflicting_prs": conflicting_prs,
        "next_stage": "review",
    }
    save_session(session_id, {**result, **base_session, "test_passed": test_passed})
    return result
