def qa_prompt(issue_title, test_output, review_verdict, review_dimensions, impact_analysis,
              codebase_analysis="", pr_description="", sdd=""):
    dims_text = "\n".join(
        f"- **{k}:** {v['status']} — {v['notes'][:300]}"
        for k, v in (review_dimensions or {}).items()
    )
    sdd_section = f"\nSOLUTION DESIGN:\n{sdd}" if sdd else ""
    return f"""You're QA giving final sign-off. Be proportional — a small bug fix needs a quick check, a complex feature needs thorough verification.

TASK: {issue_title}

PR: {pr_description or "Not provided."}

IMPACT: {impact_analysis or "Not provided."}
{sdd_section}

PEER REVIEW: {review_verdict}
{dims_text or "Not provided."}

TEST RESULTS:
{test_output or "Not provided."}

---

## 1. Acceptance Criteria Check

Did the implementation satisfy each criterion? MET / NOT MET / PARTIAL, with evidence (test name or code reference).

## 2. Test Coverage

What's covered and what's missing? Focus on gaps that could fail in production — edge cases, boundary values, error conditions. If it's solid, say so briefly.

## 3. Peer Review Follow-up

Were blocking issues from the reviewer resolved? For each: RESOLVED / UNRESOLVED / PARTIAL.

## 5. Regression Risk

What could have been affected? Risk level? Covered by tests? One line is enough for a small isolated change.

## 6. Deployment Gate: STAGE

- [ ] Tests passing
- [ ] Acceptance criteria met
- [ ] High-risk gaps addressed
- [ ] Peer review issues resolved

**STAGE Gate: OPEN / BLOCKED**

What to manually verify on STAGE (be specific).

## 7. Deployment Gate: PRODUCTION

- [ ] STAGE gate passed and verified
- [ ] No new errors in STAGE logs
- [ ] Rollback plan confirmed

**PROD Gate: OPEN / BLOCKED**

**Rollback:** exact steps to revert if needed.

## 8. QA Verdict

**APPROVED** or **REJECTED**

If APPROVED: confidence (HIGH / MEDIUM / LOW) and any conditions.
If REJECTED: what must be fixed and who fixes it.
"""


def revision_prompt(issue_title, previous_qa, human_feedback):
    return f"""A reviewer has feedback on your QA report. Update it.

TASK: {issue_title}

YOUR QA REPORT:
{previous_qa}

FEEDBACK:
{human_feedback}

Address the feedback. If it resolves blocking issues, update gate statuses and verdict. Return the updated report.
"""
