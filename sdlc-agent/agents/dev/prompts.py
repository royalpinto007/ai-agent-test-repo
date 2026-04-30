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

    return f"""Implement the task. Match the existing code style exactly.

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

Rules:
- Match the existing code style exactly (naming, spacing, error handling, exports)
- Don't change anything not required by the task
- Handle error conditions — don't let things fail silently
- Output complete file contents, never partial snippets

---

## Impact Analysis

For each affected file: does it need changes? If yes, what and why. If no, confirm it's compatible.
Note any function signature changes (before → after) and who calls them.

## Changes

FILE: <relative path>
```<language>
<complete file content>
```

## Unit Tests

FILE: <relative test file path>
```<language>
<complete test file content>
```

Cover: happy path, edge cases, boundary values, error conditions, and every acceptance criterion.
Match the existing test style.

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

All implementation rules from before still apply.
Your entire response must be valid code within the headings — no prose outside them.
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
Return the complete updated implementation in the same FILE:/```...``` format.
Also update ## PR Description and ## Summary sections to reflect the changes.
"""
