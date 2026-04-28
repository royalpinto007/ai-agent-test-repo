def qa_prompt(issue_title, test_output, review_verdict, review_dimensions, impact_analysis):
    dims_text = "\n".join(
        f"- {k}: {v['status']} — {v['notes'][:200]}"
        for k, v in (review_dimensions or {}).items()
    )
    return f"""You are a QA engineer signing off on a software change.

TASK: {issue_title}

PEER REVIEW VERDICT: {review_verdict}
REVIEW DIMENSIONS:
{dims_text}

IMPACT ANALYSIS:
{impact_analysis}

TEST RESULTS:
{test_output}

Provide a complete QA sign-off using exactly these headings:

## QA Verdict
APPROVED or REJECTED

## Test Coverage Assessment
Are the automated tests sufficient? What scenarios are tested? What is missing?

## Edge Cases Verification
List edge cases that should be verified. For each state: YES / NO / PARTIAL coverage.

## Regression Risk
Low / Medium / High — which existing functionality could be affected?

## Sign-off Conditions
If APPROVED: follow-up items or monitoring recommendations.
If REJECTED: exactly what must be fixed before approval.

## Notes
Any other observations. If none, write "None."
"""
