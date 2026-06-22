_STACK_DETECTION_RULES = """STACK DETECTION RULES (read carefully):
- Determine the actual technology stack ONLY from the file tree and file contents shown below.
- File extensions, framework-specific filenames, and module paths are your evidence (e.g. composer.json/php → PHP; manage.py → Django; pom.xml → Java/Maven; module manifests → Odoo/Dolibarr).
- If the evidence is thin, say "Stack unclear — need more files" instead of guessing.
- Do NOT assume Odoo, Django, Rails, Laravel, or any other framework based on the requirement description alone.
- Do NOT invent file paths, classes, or APIs that are not visible in the file tree.
- If you reference a file in your analysis, the file MUST appear in the file tree above.
"""


def bug_analysis_prompt(issue_title, issue_description, file_contents, file_tree_str):
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    return f"""You're a senior engineer performing a bug analysis. Output ONLY the structured report below — no prose, no padding.

{_STACK_DETECTION_RULES}

BUG TITLE: {issue_title}

BUG DESCRIPTION:
{issue_description}

FILE TREE:
{file_tree_str}

RELEVANT FILES:
{files_section}

---

## Issue Clarification
[2-3 sentences describing the bug clearly — expected vs actual behaviour, who is affected]

## Verification Steps
1. [step]
2. [step]
(max 5 steps — include preconditions and expected vs actual output)

## Root Cause
[1-2 sentences on likely cause + specific file/function/line if known — cite a path from the file tree]

## Cause Verification
- [how to confirm the root cause — targeted test, log, or diagnostic step]
(max 3 bullets)

## Proposed Fix
**Option A:** [one line]
**Option B:** [one line]
Recommendation: Option [A/B] — [one line reason]
"""


def complexity_classify_prompt(requirement):
    """Triage that separates two axes: config-vs-code, and small-vs-large.

    Returns guidance for a single-word answer: config | small | large.
    - config decides whether the pipeline short-circuits (no build).
    - small vs large decides how terse the BRD is. BOTH small and large are code
      changes that go through Dev and produce a PR.
    """
    return f"""Classify this software request in ONE word.

REQUIREMENT:
{requirement}

Answer with exactly one of:
- config — can be satisfied WITHOUT editing source code: by changing an admin/site setting, or by using existing functionality differently. No PR will be produced.
- small  — needs a SMALL source-code edit (a few lines, typically one file): e.g. add a code comment, change a constant/default in code, add a small helper. This IS a code change and must go through development.
- large  — a new feature or a multi-file code change.

Key rule: if it requires editing source files AT ALL (even a one-line code comment), it is "small" or "large", NEVER "config". "config" is only for settings/no-code solutions. If unsure between small and large, answer "small"; if unsure whether code is needed at all, answer "small".

Output ONLY the one word, nothing else."""


def minimal_brd_prompt(requirement, file_contents, live_config=""):
    """Terse doc for a SIMPLE (config/workaround) request — no feature-spec padding.

    Deliberately omits System Analysis / Why / Who / Out of Scope / Test Cases so
    the model can't pad a one-setting change into an essay.
    """
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    if not files_section.strip():
        files_section = "(no files loaded)"
    live_section = ""
    if live_config and live_config.strip():
        live_section = f"\n{live_config}\nUse the live config above as ground truth about the current state.\n"

    return f"""You're a Business Analyst answering a SIMPLE configuration/workaround request. Be brief — this should read like a short how-to, not a spec.

REQUIREMENT: {requirement}
{live_section}
RELEVANT FILES (excerpts):
{files_section}

Write ONLY the following, and keep the whole thing under ~12 lines:

## What
[one sentence — what the user wants.]

## How to do it
[the exact steps: screen → setting → value. Cite a real path from the files above if relevant. 2-6 short steps.]

[Optional single line starting with "Note:" only if there is a genuine caveat — otherwise omit entirely.]

Then, on the very last line, write exactly one of:
RESOLUTION_TIER: config
RESOLUTION_TIER: workaround

Do NOT include: System Analysis, Why, Who, Acceptance Criteria, Out of Scope, Test Cases, Open Questions, or any table. No extra headings beyond the two above."""


def minimal_code_brd_prompt(requirement, file_contents, live_config=""):
    """Terse BRD for a SMALL code change — brief, but still a code change that
    goes through development (ends with RESOLUTION_TIER: code_change). Avoids the
    full feature-spec padding while giving Dev enough to implement."""
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    if not files_section.strip():
        files_section = "(no files loaded)"
    live_section = ""
    if live_config and live_config.strip():
        live_section = f"\n{live_config}\n"

    return f"""You're a Business Analyst scoping a SMALL code change for a developer. Be brief — a few lines, not a full spec.

REQUIREMENT: {requirement}
{live_section}
RELEVANT FILES (excerpts):
{files_section}

Write ONLY:

## What
[one sentence — what the change is.]

## Where
[the file(s) / area to change, citing a real path from the files above if you can.]

## Acceptance Criteria
- [ ] [2-3 short, testable criteria — include "no unrelated behaviour changes" when apt]

Then, on the very last line, write exactly:
RESOLUTION_TIER: code_change

Do NOT include System Analysis, Why/Who, Out of Scope, Test Cases, or Open Questions. This is a code change — it will go through development and produce a PR."""


def analysis_and_brd_prompt(requirement, file_tree, file_contents, ui_needed=False, live_config=""):
    """Single-call prompt that produces System Analysis + BRD together.

    ui_needed: when True, the BA also produces an HTML mockup of the proposed
    UI. Gated by the issue's 'UI mockup needed?' field to control token usage.
    live_config: optional block of CURRENT live-instance settings read from the
    running site; when present the BA must use it instead of guessing defaults.
    """
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    if not files_section.strip():
        files_section = "(no files were loaded — file tree may be empty or no files matched the requirement)"

    live_section = ""
    if live_config and live_config.strip():
        live_section = f"""
{live_config}

Use the live config above as ground truth about the CURRENT state of the running site.
- State the actual current setting(s) explicitly (don't say "depending on the active plugin" when the live config already tells you which one is active).
- Base the Resolution Approach on what is really configured now, not on Moodle defaults.
- Only raise an Open Question about a setting if it is NOT answered by the live config above.
"""

    ui_section = ""
    if ui_needed:
        ui_section = """
### UI Mockup
A UI change was requested for this feature. Produce a single self-contained HTML mockup of the proposed screen so the team can preview it before any code is written.

- Wrap it in a fenced ```html code block.
- Inline all CSS in a `<style>` tag — no external files, no JS frameworks, no CDN links.
- Show the realistic layout: headings, form fields, buttons, tables, and any state the requirement implies (e.g. a validation error, an empty state).
- Keep it to one screen. Use placeholder text/data that reflects this requirement.
- This is a visual mockup for review, not production markup.
"""

    return f"""You're a Business Analyst writing a requirement document for a development team.

MATCH THE LENGTH OF YOUR OUTPUT TO THE SIZE OF THE CHANGE. This is the most important rule:
- A simple Config or Workaround (e.g. flip one admin setting) needs only a few lines: what it is, the exact steps, and the tier. Then STOP. Do not invent Out of Scope, exhaustive test cases, or multiple open questions for a one-setting change — padding a trivial ask into a feature spec wastes the reader's time.
- Only a genuine new feature or non-trivial code change earns the full breakdown (detailed acceptance criteria, positive/negative test cases, open questions).
When in doubt, err on the side of shorter.

{_STACK_DETECTION_RULES}

REQUIREMENT: {requirement}
{live_section}
FILE TREE:
{file_tree}

RELEVANT FILES (excerpts):
{files_section}

---

## System Analysis
- Simple config/workaround → 1-2 lines: what currently provides this and the gap (cite a path if you have one).
- Feature/code change → Detected Stack, What Exists Today, What's Missing, Type of Change, Obvious Risks — each bullet citing a path from the tree.

---

## Business Requirements Document

### What
[1-2 sentences — what success looks like.]

### Resolution Approach
| Tier | When to choose |
|------|---------------|
| **Config** | Existing functionality can be configured to meet the requirement. No code changes. |
| **Workaround** | Existing functionality already supports this — use it differently. No config or code change. |
| **Code change** | Neither config nor workaround can satisfy it. New code required. |

Chosen tier: Config / Workaround / Code change — [one line reason, cite a path where possible].

**If Config or Workaround:** give the exact steps to do it (screens → settings → values, or the precise existing-feature steps). That IS the deliverable. Add at most 2-3 acceptance criteria ONLY if they aren't obvious from the steps. Then go straight to the RESOLUTION_TIER line — no Out of Scope, no Test Cases section.

**If Code change / new feature**, also include the sections below:

### Why
[1 sentence]

### Who
[one line]

### Acceptance Criteria
- [ ] [criterion] (max 6, testable, include error cases — these double as the expected-behaviour flows)

### Test Cases
**Positive (should work):**
- [ ] [action → expected result] (2-4)
**Negative (should be rejected / handled gracefully):**
- [ ] [edge case → expected handling] (2-4)
{ui_section}
### Open Questions
- [only genuinely blocking or decision-changing unknowns] — Blocking: Yes/No
(max 3 — omit the section entirely if none; a clear config change usually has none)

Finally, on the very last line of your response, write exactly one of:
RESOLUTION_TIER: config
RESOLUTION_TIER: workaround
RESOLUTION_TIER: code_change

- `config` — satisfied by configuration only
- `workaround` — satisfied by using existing functionality differently
- `code_change` — requires development work
"""


def followup_prompt(requirement, system_analysis, previous_brd, clarification_qa, file_tree):
    return f"""You wrote a BRD with open questions and got answers back. Update the BRD to reflect them.

{_STACK_DETECTION_RULES}

REQUIREMENT: {requirement}

YOUR PREVIOUS ANALYSIS:
{system_analysis}

YOUR PREVIOUS BRD:
{previous_brd}

ANSWERS TO YOUR QUESTIONS:
{clarification_qa}

FILE TREE:
{file_tree}

Update every part of the BRD affected by the answers. Resolve the open questions. If an answer opens up a genuinely new blocking question, add it. Otherwise mark open questions as resolved and return the updated BRD using the same structured format (starting with `## Business Requirements Document`).
"""


def revision_prompt(requirement, system_analysis, previous_brd, human_feedback, file_tree):
    return f"""A reviewer asked for changes to your BRD. Update it.

{_STACK_DETECTION_RULES}

REQUIREMENT: {requirement}

YOUR PREVIOUS ANALYSIS:
{system_analysis}

YOUR PREVIOUS BRD:
{previous_brd}

FEEDBACK FROM REVIEWER:
{human_feedback}

FILE TREE:
{file_tree}

Address every point in the feedback. If scope changes, update the acceptance criteria. Return the updated BRD using the same structured format (starting with `## Business Requirements Document`).
"""
