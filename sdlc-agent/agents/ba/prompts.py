def bug_analysis_prompt(issue_title, issue_description, file_contents, file_tree_str):
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    return f"""You're a senior engineer performing a bug analysis. Output ONLY the structured report below — no prose, no padding.

BUG TITLE: {issue_title}

BUG DESCRIPTION:
{issue_description}

FILE TREE:
{file_tree_str}

RELEVANT FILES:
{files_section}

---

## 🐛 Issue Clarification
[2-3 sentences describing the bug clearly — expected vs actual behaviour, who is affected]

## 🔍 Verification Steps
1. [step]
2. [step]
(max 5 steps — include preconditions and expected vs actual output)

## 🔎 Root Cause
[1-2 sentences on likely cause + specific file/function/line if known]

## ✅ Cause Verification
- [how to confirm the root cause — targeted test, log, or diagnostic step]
(max 3 bullets)

## 🛠️ Proposed Fix
**Option A:** [one line]
**Option B:** [one line]
Recommendation: Option [A/B] — [one line reason]
"""


def system_analysis_prompt(requirement, file_tree, file_contents):
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    return f"""You're a Business Analyst reviewing a new requirement. Output ONLY the structured report below — no prose, no padding.

REQUIREMENT: {requirement}

FILE TREE:
{file_tree}

RELEVANT FILES:
{files_section}

---

## 📦 What Exists Today
- [specific function/file and what it does — one bullet per relevant item]

## 🔧 What's Missing or Broken
- [the actual gap between current code and the requirement]

## 🏷️ Type of Change
Bug fix / Small enhancement / New feature / Large feature — [one line reason]

## ⚠️ Obvious Risks
- [only things that genuinely matter — skip if none]
"""


def brd_prompt(requirement, system_analysis, file_tree):
    return f"""You're writing requirements for a development team. Output ONLY the structured report below — no prose, no padding.

REQUIREMENT: {requirement}

YOUR ANALYSIS:
{system_analysis}

FILE TREE:
{file_tree}

---

## 🎯 What
[1-2 sentences max — what is this and what does success look like]

## 💡 Why
[1 sentence — the business or user reason]

## 👤 Who
[one line — who is affected or benefits]

## ✅ Acceptance Criteria
- [ ] [criterion]
- [ ] [criterion]
(max 6 bullets — testable, include error cases)

## 🚫 Out of Scope
- [item]
(max 4 bullets — omit section if none)

## ⚙️ Config Only?
Yes / No — [one line reason]

## ❓ Open Questions
- [question] — Blocking: Yes/No
(max 3 questions — omit section if none)

Finally, on the very last line of your response, write exactly one of:
CONFIG_ONLY: true
CONFIG_ONLY: false

Write `CONFIG_ONLY: true` only if the requirement can be satisfied entirely through configuration with no code changes needed. Otherwise write `CONFIG_ONLY: false`.
"""


def followup_prompt(requirement, system_analysis, previous_brd, clarification_qa, file_tree):
    return f"""You wrote a BRD with open questions and got answers back. Update the BRD to reflect them.

REQUIREMENT: {requirement}

YOUR ANALYSIS: {system_analysis}

YOUR BRD:
{previous_brd}

ANSWERS:
{clarification_qa}

FILE TREE:
{file_tree}

Update every part of the BRD affected by the answers. Resolve the open questions. If an answer opens up a genuinely new blocking question, add it. Otherwise mark open questions as resolved and return the updated BRD using the same structured format.
"""


def revision_prompt(requirement, system_analysis, previous_brd, human_feedback, file_tree):
    return f"""A reviewer asked for changes to your BRD. Update it.

REQUIREMENT: {requirement}

YOUR ANALYSIS: {system_analysis}

YOUR BRD:
{previous_brd}

FEEDBACK:
{human_feedback}

FILE TREE:
{file_tree}

Address every point. If scope changes, update the acceptance criteria and dev items. Return the updated BRD using the same structured format.
"""
