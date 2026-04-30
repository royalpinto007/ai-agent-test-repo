def review_prompt(issue_title, diff, impact_analysis, test_diff, affected_files, codebase_analysis="", pr_description=""):
    affected_section = "\n".join(f"- {f}" for f in affected_files) if affected_files else "None"
    return f"""Review this code change. Be direct — say what's wrong and why, or say it looks good. Reference specific lines/functions.

Scale your review to the change. A one-line bug fix doesn't need a 10-section report. A big feature change does.

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

**What was changed** — quick summary of what the diff actually does.

## 2. Correctness
**Status: PASS / FAIL**
Does it actually solve the task? Any logic errors, missing branches, wrong conditions? Are all acceptance criteria satisfied?
If none: "Looks correct."

## 3. Security
**Status: PASS / FAIL**
Input validation, injection risks, exposed secrets, unsafe operations? Only flag things relevant to this change.
If none: "No security concerns."

## 4. Performance
**Status: PASS / FAIL**
Obvious inefficiencies? Only flag things that actually matter at scale.
If none: "No performance concerns."

## 5. Error Handling
**Status: PASS / FAIL**
Are errors caught and handled properly? Silent failures? Missing validation?
If none: "Error handling looks good."

## 6. Test Coverage
**Status: PASS / FAIL**
Are the important cases tested? Missing edge cases or error conditions?
If none: "Tests cover what they need to."

## 8. Blocking Issues
Things that must be fixed before this merges. Only real bugs, security issues, or missing tests for acceptance criteria — not style nits.

If none: "None — approved to merge."

## 9. Suggestions *(optional)*
Non-blocking improvements worth mentioning. Skip this section if there's nothing worth saying.

## 10. Verdict
**PASS** or **FAIL**

## Summary
One or two sentences: overall quality and what to do next.
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

Re-review the changes:
1. For each blocking issue from your original review — is it now fixed? (YES / NO / PARTIAL)
2. Were any new issues introduced by the fixes?
3. Did the developer address the human reviewer's feedback?

Use the same section headings as the original review.
Focus on changes — you do not need to re-review unchanged code.
Update the Verdict based on what remains.
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

Update your code review to address the feedback. If the feedback overrides a FAIL verdict, change it to PASS and explain why the concern is addressed. Return the complete updated review using the same section numbering.
"""
