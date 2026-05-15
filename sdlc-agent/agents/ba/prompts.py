def bug_analysis_prompt(issue_title, issue_description, file_contents, file_tree_str):
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    return f"""You're a senior engineer performing a thorough bug analysis. Read the codebase carefully, then produce a structured report covering all five sections below. Be direct and specific — name actual files, functions, and line ranges.

BUG TITLE: {issue_title}

BUG DESCRIPTION:
{issue_description}

FILE TREE:
{file_tree_str}

RELEVANT FILES:
{files_section}

---

## 1. Issue Clarification
Fully describe the bug as you understand it. What is the expected behaviour? What is the actual behaviour? Who is affected and under what conditions? Identify any ambiguity in the report and state your assumptions.

## 2. Issue Verification
List the exact steps to confirm this bug is reproducible. Include environment requirements, preconditions, and expected vs actual output at each step. If automated tests exist, name which ones cover this area.

## 3. Cause Determination
Identify the root cause in the codebase. Name the specific file(s), function(s), and line(s) where the defect lives. Explain the chain of events from trigger to symptom.

## 4. Cause Verification
How would you confirm you've found the right root cause? Describe a targeted test or diagnostic step (e.g. adding a log, running a specific unit test, checking a specific DB query) that isolates the faulty logic.

## 5. Possible Solution
Propose 2–3 concrete fix approaches. For each: what changes are needed, which files are affected, and what the trade-off is (simplicity vs completeness, risk of regression, etc.). Recommend one.
"""


def system_analysis_prompt(requirement, file_tree, file_contents):
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    return f"""You're a Business Analyst looking at a new requirement. Read the relevant code first, then write a brief, honest briefing — like you're explaining to a teammate what exists and what's missing.

REQUIREMENT: {requirement}

FILE TREE:
{file_tree}

RELEVANT FILES:
{files_section}

Write proportionally to the complexity. A small bug fix = 2-3 short paragraphs. A bigger feature = more detail. Don't pad.

**What exists today** — what does the current code do in this area? Name specific functions/files.

**What's missing or broken** — the actual gap between now and what's needed.

**Type of change** — bug fix, small enhancement, new feature, or something bigger?

**Obvious risks** — anything that looks tricky? Keep it to things that genuinely matter.
"""


def brd_prompt(requirement, system_analysis, file_tree):
    return f"""You're writing up requirements for a development team. Be direct and clear — write for a smart developer, not a committee.

REQUIREMENT: {requirement}

YOUR ANALYSIS:
{system_analysis}

FILE TREE:
{file_tree}

**Scale your output to the complexity of the change.** A simple bug fix needs half a page. A multi-part feature needs more. Skip any section where you'd just write N/A.

---

**What we're building and why**
1-3 sentences. What is this, and what does success look like?

**Current behaviour vs required behaviour**
Be specific — name the actual functions and files. What happens today vs what should happen after this ships?

**Acceptance criteria**
Every testable requirement as Given/When/Then. Include error cases and edge cases. For a tiny change, a short bullet list is fine.

**What needs to be built**
The actual dev items. For each: what it is, which files change, rough size (trivial / small / medium / large). If it's a config-only change, say so.

**Open questions** *(only if something would actually block us)*
If you have none, say "None — good to go."

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

Update every part of the BRD affected by the answers. Resolve the open questions. If an answer opens up a genuinely new blocking question, add it. Otherwise mark open questions as resolved and return the updated BRD.
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

Address every point. If scope changes, update the acceptance criteria and dev items. Return the updated BRD.
"""
