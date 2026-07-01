def codebase_understanding_prompt(issue_title, issue_description, file_contents, file_tree):
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    return f"""Before writing any code, understand what's already there.

TASK: {issue_title}
{issue_description}

FILE TREE:
{file_tree}

RELEVANT FILES:
{files_section}

Write a short pre-implementation analysis — scale it to the task. A small bug fix needs 1-2 paragraphs. A bigger feature needs more.

**What exists and how it works** — the specific functions/files relevant to this task, how they work, what calls them.

**What needs to change** — exact files and functions. What changes and why.

**What could break** — anything that depends on what you're changing. Be honest about the risk level.

**Code style to follow** — naming, error handling, export style from the existing code. You must match it exactly.

**Test plan** — happy path, edge cases, error conditions to cover. Focus on what could be missed.
"""


def implementation_prompt(issue_title, issue_description, file_contents, affected_files,
                           file_tree, codebase_analysis, pm_tasks=None):
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    affected_section = "\n".join(f"- {f}" for f in affected_files) if affected_files else "None identified"
    pm_section = f"\nTASK DETAILS FROM PM:\n{pm_tasks}" if pm_tasks else ""

    return f"""CONSTRAINT: You have no tool access — no shell, no network, no file reads. Everything you need (file tree and current file contents) is already in this prompt. This is a SINGLE-SHOT request: you will NOT get another turn, so do not say "let me check" or "reading the files" or emit exploratory shell commands. Do NOT emit `<function_calls>` or any tool-invocation XML. Produce the implementation now, as precise edits in the `## Changes` format specified below.

Implement the task. Match the existing code style exactly.

TASK: {issue_title}
{issue_description}
{pm_section}

YOUR ANALYSIS:
{codebase_analysis}

FILES THAT MAY BE AFFECTED:
{affected_section}

CURRENT FILE CONTENTS:
{files_section}

FILE TREE:
{file_tree}

CRITICAL — how to edit:
- To change an EXISTING file, output a SEARCH/REPLACE edit. The SEARCH block must be copied VERBATIM from the CURRENT FILE CONTENTS above (exact characters, indentation, and enough surrounding lines to be UNIQUE in that file). Only the lines you want to change should differ in REPLACE.
- NEVER reproduce a whole existing file. Edits must be minimal — touch only what the task needs. Do not delete or rewrite code unrelated to the task.
- Respect the VERB of the task. If it asks to ADD something (a comment, a function, an option), INSERT new lines and leave existing lines unchanged — your SEARCH and REPLACE should be identical except for the added lines (a pure addition). Only reword or replace existing lines when the task is explicitly to change existing behaviour/wording. Do not "improve" or rephrase existing content that already works.
- Only use NEWFILE for a file that does not exist yet.
- Match existing style; handle errors; don't break callers (note signature changes in Impact Analysis).

---

## Impact Analysis

For each affected file: does it need changes? If yes, what and why. If no, confirm it's compatible.
Note any function signature changes (before → after) and who calls them.

## Changes

For each existing file you change, one or more blocks of exactly this form:

EDIT: <relative path>
<<<<<<< SEARCH
<exact lines copied verbatim from the current file — unique anchor>
=======
<the replacement lines>
>>>>>>> REPLACE

For a brand-new file only:

NEWFILE: <relative path>
```<language>
<complete file content>
```

## Unit Tests

Add or update tests the same way (EDIT an existing test file, or NEWFILE a new one).
Cover: happy path, edge cases, boundary values, error conditions, and every acceptance criterion. Match the existing test style. If the change genuinely needs no test (e.g. a comment-only change), say so here and add none.

## PR Description

**Summary:** What changed and why (2-3 sentences).

**Files changed:** bullet list

**How to test:** steps a reviewer can follow to verify it works

## Summary
One paragraph: what was built, key decisions, what was verified.
"""


def agentic_implementation_prompt(issue_title, issue_description, pm_tasks=None, redo_instructions=None):
    """Prompt for the tool-enabled Dolibarr/Thrive Dev path. Claude has the
    dolibarr-dev skill + file tools + the dolibarr_expert MCP, and works directly
    in the checked-out module. No files are pasted in — the skill scans what it
    needs, which is the whole point (lean context, live verification)."""
    pm_section = f"\n\nPLAN / TASK DETAIL FROM PM:\n{pm_tasks}" if pm_tasks else ""
    redo_section = f"\n\nEXTRA INSTRUCTIONS FROM REVIEWER (address these):\n{redo_instructions}" if redo_instructions else ""
    return f"""You are the Dev stage of an automated pipeline, implementing one issue in a live Dolibarr/Thrive codebase. Your current working directory is a fresh feature branch already checked out for you.

**Use the `dolibarr-dev` skill** — follow its Step 0 (read LEARNINGS, the module brain, scan existing code/DB before writing) and its plan-first, reuse-first, security, and prove-it discipline. Scan with the skill's helper scripts and the dolibarr_expert MCP rather than reading whole files; keep your context lean.

TASK: {issue_title}

{issue_description}{pm_section}{redo_section}

Rules for this automated run:
- Implement the smallest correct change that satisfies the task. Match existing Dolibarr conventions exactly (mirror real code; reuse before rewriting).
- **Scaffolding — prefer the Module Builder MCP.** When the task is to add a standard object/table/field/page to a module, you MUST use the `dolibarr_expert` MCP Module Builder tools, whose real names are prefixed **`aimodulebuilder_`** (NOT `amb_` — that prefix does not exist). First call `aimodulebuilder_status` to confirm the builder is ready and `aimodulebuilder_native_actions` if you need the exact action names, then use the incremental tools: `aimodulebuilder_add_object` (add a table/object), `aimodulebuilder_add_field`/`aimodulebuilder_update_field`/`aimodulebuilder_delete_field`, `aimodulebuilder_init_part`, `aimodulebuilder_init_object_page`, and `aimodulebuilder_write_file`/`aimodulebuilder_read_file` to refine generated files. Only hand-write as a fallback if a specific `aimodulebuilder_*` call genuinely fails — and when you do, say so explicitly in the Summary (name the exact tool + the error). For small edits to existing code (a lang key, a tweak in an existing method), just edit the file directly.
- **Finish the scaffold — no placeholder leftovers.** The Module Builder generates template files with boilerplate (`README.md` saying "MYMODULE … Description of the module…", an empty `ChangeLog`, stub `doc/`). Before you finish you MUST replace the README's placeholder with a real description of THIS module (what it is, its object/fields, how it's used) and remove obvious "MYMODULE"/"Description of the module..." boilerplate. A module that ships the template README is not done.
- **If the module has reference auto-numbering, set `module_parts['models'] => 1`** in the descriptor (and note that reactivation registers it) — otherwise the numbering model never loads and refs stay `(PROV…)`. (See LEARNINGS.)
- Edit files **in place** in the working directory with your file tools. Do NOT run `git add`, `git commit`, `git push`, `git checkout`, or create branches — the pipeline commits, pushes, and opens the PR from your working-tree changes.
- Verify behaviour the skill's way where you can (drive the flow / read the log / check the DB), but do not start long-running servers or background processes.
- If a schema/descriptor change needs a module reactivation to take effect, note it in the PR description rather than reactivating in this run.

When you are done editing, output ONLY the following two sections as your final message (everything above was tool work):

## PR Description
**Summary:** what changed and why (2-3 sentences).
**Files changed:** bullet list of the files you edited/created.
**How to test:** steps a reviewer can follow to verify it.

## Summary
One paragraph: what was built, which existing functions/mechanisms you reused, what you verified, and whether a module reactivation is needed.
"""


def agentic_new_module_prompt(issue_title, issue_description, module_key, module_dir,
                              pm_tasks=None, redo_instructions=None):
    """Prompt for building a BRAND-NEW Dolibarr module entirely through the
    dolibarr_expert Module Builder MCP. The module dir does not exist yet — the
    MCP's create endpoint refuses a pre-existing dir, so it must scaffold fresh.
    The pipeline harvests `module_dir` into the git clone and opens the PR."""
    pm_section = f"\n\nPLAN / TASK DETAIL FROM PM:\n{pm_tasks}" if pm_tasks else ""
    redo_section = f"\n\nEXTRA INSTRUCTIONS FROM REVIEWER (address these):\n{redo_instructions}" if redo_instructions else ""
    return f"""You are the Dev stage of an automated pipeline. Your job is to build a BRAND-NEW Dolibarr custom module, and you MUST build it through the `dolibarr_expert` Module Builder MCP — not by hand. This is the whole point of this run: prove the module can be generated by the MCP.

**Use the `dolibarr-dev` skill** for conventions (Step 0: scan existing custom modules + DB first to mirror real patterns), but the SCAFFOLDING must go through the MCP.

TASK: {issue_title}

{issue_description}{pm_section}{redo_section}

MODULE FACTS (do not deviate):
- Module key (lowercase, alphanumeric): **{module_key}**  — pass this EXACT value as `module_key` so the files land in `{module_dir}`.
- The module directory `{module_dir}` does NOT exist yet. The MCP `aimodulebuilder_create_module` endpoint REFUSES to run if the directory already exists — so do not create it yourself, and do not hand-write files into it first.

How to build (in this order):
1. Call **`aimodulebuilder_status`** to confirm the builder API is installed and ready. If it is not ready, stop and report that in your Summary — do NOT hand-scaffold.
2. Call **`aimodulebuilder_create_module`** with a JSON manifest: `module_name` (human name), `module_key` = `{module_key}`, `description`, `menu_title`, and `tables` (each with its `fields`), plus `features`/`permissions`/`menus`/`pages` as the task needs. This generates the descriptor, object class, SQL, card/list pages, lang, and menus in one shot.
3. Refine with the incremental tools where needed: `aimodulebuilder_add_object`, `aimodulebuilder_add_field`, `aimodulebuilder_init_object_page`, and `aimodulebuilder_write_file`/`aimodulebuilder_read_file` for hand-tuning generated files (e.g. business rules, a real README).
4. The real MCP tool names are prefixed **`aimodulebuilder_`**. There is NO `amb_*` tool — never call one. If unsure of an exact name, call `aimodulebuilder_native_actions`.

Quality bar (verify before finishing):
- **Real README** — replace any generated `MYMODULE` / "Description of the module..." boilerplate with a real description of THIS module.
- **Numbering:** if the object has reference auto-numbering, set `module_parts['models'] => 1` in the descriptor (via `aimodulebuilder_write_file` if the generator didn't), else refs stay `(PROV…)`.
- **Uninstall SQL must be named plain `uninstall.sql`** (NOT `llx_<mod>.uninstall.sql`) — a `DROP TABLE` in an `llx_`-prefixed file is auto-run by `_load_tables()` on ENABLE and drops the table on install. If the generator emitted an `llx_*.uninstall.sql`, rename/rewrite it to `uninstall.sql`.

Do NOT run any git commands (no add/commit/push/checkout/branch) — the pipeline versions `{module_dir}` and opens the PR. Do not enable the module or start servers.

When done, output ONLY:

## PR Description
**Summary:** what the module is and how it was generated (name the MCP tools you called).
**Files changed:** bullet list of the generated files.
**How to test:** steps a reviewer can follow (enable module → create/validate a record → check ref numbering).

## Summary
One paragraph: what was built, which `aimodulebuilder_*` calls generated it, what you verified, and whether a module reactivation is needed. If any MCP call failed and you had to hand-write, say exactly which call and why.
"""


def agentic_retry_prompt(issue_title, test_output):
    return f"""The change you just made to this Dolibarr/Thrive working tree FAILED the automated tests.

TASK: {issue_title}

TEST OUTPUT:
{test_output}

Using the dolibarr-dev skill and your file tools, diagnose the ROOT cause (not just the failing assertion) and fix it in place in the working directory. Keep the change minimal and do not run any git commands. When done, output ONLY the `## PR Description` and `## Summary` sections as before.
"""


def retry_prompt(issue_title, previous_output, test_output, attempt, codebase_analysis):
    return f"""You are a senior software engineer. Your implementation attempt {attempt} failed automated tests.

TASK: {issue_title}

YOUR PRE-IMPLEMENTATION ANALYSIS:
{codebase_analysis}

TEST FAILURES:
{test_output}

YOUR PREVIOUS IMPLEMENTATION:
{previous_output}

Diagnose the failures carefully:
1. Identify the root cause — do not just fix the failing assertion
2. Check if the failure reveals a flaw in your impact analysis
3. Check if the failure is in your implementation or your tests
4. Fix the root cause, not the symptom

Return the corrected implementation using the exact same format:
## Impact Analysis, ## Changes, ## Unit Tests, ## PR Description, ## Summary

Use the same EDIT (SEARCH/REPLACE) blocks for existing files and NEWFILE blocks for new files. SEARCH must match the current file verbatim. Keep edits minimal — don't rewrite whole files. All implementation rules from before still apply.
"""


def redo_prompt(issue_title, previous_output, extra_instructions, codebase_analysis):
    return f"""You are a senior software developer revising your implementation based on new instructions.

TASK: {issue_title}

YOUR PREVIOUS IMPLEMENTATION:
{previous_output}

EXTRA INSTRUCTIONS FROM REVIEWER:
{extra_instructions}

CODEBASE ANALYSIS:
{codebase_analysis}

Revise the implementation to satisfy the extra instructions while keeping all existing passing tests intact.

Output your changes in EXACTLY this format (no other format will be parsed):

## Changes

For each existing file you change:

EDIT: <relative path>
<<<<<<< SEARCH
<exact lines copied VERBATIM from the current file — enough to be unique>
=======
<the replacement lines>
>>>>>>> REPLACE

For a brand-new file only:

NEWFILE: <relative path>
```<language>
<complete file content>
```

Keep edits minimal — copy the SEARCH text exactly, change only what's needed, never rewrite a whole file.

## PR Description
**Summary:** what changed and why.

## Summary
One paragraph on what was revised.
"""
