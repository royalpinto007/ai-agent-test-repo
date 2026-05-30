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


def analysis_and_brd_prompt(requirement, file_tree, file_contents, ui_needed=False):
    """Single-call prompt that produces System Analysis + BRD together.

    ui_needed: when True, the BA also produces an HTML mockup of the proposed
    UI. Gated by the issue's 'UI mockup needed?' field to control token usage.
    """
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    if not files_section.strip():
        files_section = "(no files were loaded — file tree may be empty or no files matched the requirement)"

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

    return f"""You're a Business Analyst writing a requirement document for a development team. Output ONLY the two structured sections below — no prose, no padding.

{_STACK_DETECTION_RULES}

REQUIREMENT: {requirement}

FILE TREE:
{file_tree}

RELEVANT FILES (excerpts):
{files_section}

---

## System Analysis

### Detected Stack
[1-2 lines summarising the stack you inferred from the file tree/contents. Cite specific evidence — e.g. "htdocs/main.inc.php and PHP files → Dolibarr". If unclear, say so.]

### What Exists Today
- [specific function/file/module and what it does — one bullet per relevant item. Each bullet MUST reference a path from the file tree.]

### What's Missing or Broken
- [the actual gap between current code and the requirement]

### Type of Change
Bug fix / Small enhancement / New feature / Large feature — [one line reason]

### Obvious Risks
- [only things that genuinely matter — skip if none]

---

## Business Requirements Document

### What
[1-2 sentences max — what is this and what does success look like]

### Why
[1 sentence — the business or user reason]

### Who
[one line — who is affected or benefits]

### Acceptance Criteria
- [ ] [criterion]
- [ ] [criterion]
(max 6 bullets — testable, include error cases)

### Out of Scope
- [item]
(max 4 bullets — omit section if none)

### Resolution Approach
Pick the cheapest tier that actually solves the requirement.

| Tier | When to choose |
|------|---------------|
| **Config** | Existing functionality can be configured to meet the requirement. No code changes, no behavioural changes for other users. |
| **Workaround** | Existing functionality already supports this — the user just needs to use it differently. No config change, no code change. |
| **Code change** | Neither config nor workaround can satisfy the requirement. New code is required. |

Chosen tier: Config / Workaround / Code change — [one line reason that cites evidence from the file tree where possible]

### Workaround (if applicable)
[omit this section entirely if tier is not "Workaround"]
[3-5 concrete steps using existing functionality — be specific about screens, fields, settings]

### Test Cases
Cover both happy path and failure modes — the cases a developer might miss.

**Positive (should work):**
- [ ] [action → expected result]
(2-4 cases)

**Negative (should be rejected / handled gracefully):**
- [ ] [invalid input or edge case → expected handling — e.g. wrong role, empty field, cross-company access, duplicate]
(2-4 cases)
{ui_section}
### Open Questions
- [question] — Blocking: Yes/No
(max 3 questions — omit section if none)

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
