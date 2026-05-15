def review_prompt(issue_title, diff, impact_analysis, test_diff, affected_files, codebase_analysis="", pr_description=""):
    affected_section = "\n".join(f"- {f}" for f in affected_files) if affected_files else "None"
    return f"""Review this code change. Output ONLY the structured report below — no prose, no padding.

TASK: {issue_title}

PR DESCRIPTION:
{pr_description or "Not provided."}

IMPACT ANALYSIS:
{impact_analysis or "Not provided."}

AFFECTED FILES:
{affected_section}

CODE DIFF:
{diff}

TEST DIFF:
{test_diff}

---

## Review Summary
**Verdict:** Approved / Needs Changes / Rejected

## Files Reviewed
| File | Status | Notes |
|------|--------|-------|
| [file] | OK / Issue / Problem | [one line] |

## Issues Found
- **[severity: Critical/Major/Minor]** `[file:line]` — [one line description]
(list only — omit section if none)

## What's Good
- [one line]
(max 3 bullets — omit section if nothing noteworthy)

## Required Changes
- [ ] [specific actionable change]
(omit section if Approved)
"""


def revision_review_prompt(issue_title, original_review, new_diff, new_test_diff, human_feedback=""):
    return f"""You are a senior software engineer re-reviewing code after the developer addressed your feedback.

TASK: {issue_title}

YOUR ORIGINAL REVIEW:
{original_review}

HUMAN REVIEWER FEEDBACK (if any):
{human_feedback or "None."}

UPDATED CODE DIFF:
{new_diff}

UPDATED TEST DIFF:
{new_test_diff}

Re-review the changes using the same structured format. For each blocking issue from your original review — is it now fixed? (YES / NO / PARTIAL). Flag any new issues introduced. Update the Verdict accordingly.
"""


def human_revision_prompt(issue_title, previous_review, diff, human_feedback):
    return f"""You are a senior peer reviewer revising your code review based on human feedback.

TASK: {issue_title}

YOUR PREVIOUS REVIEW:
{previous_review}

CURRENT DIFF:
{diff}

HUMAN FEEDBACK:
{human_feedback}

Update your code review to address the feedback. If the feedback overrides a Rejected verdict, change it to Approved and explain why the concern is addressed. Return the complete updated review using the same structured format.
"""
