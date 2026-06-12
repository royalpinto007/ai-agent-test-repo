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
Return the updated implementation in the same format: EDIT (SEARCH/REPLACE) blocks for existing files (SEARCH copied verbatim, minimal edits — never whole-file rewrites) and NEWFILE blocks for new files.
Also update ## PR Description and ## Summary sections to reflect the changes.
"""
