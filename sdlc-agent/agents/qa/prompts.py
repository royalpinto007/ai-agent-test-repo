def qa_prompt(issue_title, test_output, review_verdict, review_dimensions, impact_analysis,
              codebase_analysis="", pr_description="", sdd=""):
    dims_text = "\n".join(
        f"- **{k}:** {v['status']} — {v['notes'][:300]}"
        for k, v in (review_dimensions or {}).items()
    )
    sdd_section = f"\nSOLUTION DESIGN:\n{sdd}" if sdd else ""
    return f"""You're QA giving final sign-off. Output ONLY the structured report below — no prose, no padding.

TASK: {issue_title}

PR: {pr_description or "Not provided."}

IMPACT: {impact_analysis or "Not provided."}
{sdd_section}

PEER REVIEW: {review_verdict}
{dims_text or "Not provided."}

TEST RESULTS:
{test_output or "Not provided."}

---

## 🧪 QA Summary
**Result:** ✅ Pass / ⚠️ Pass with notes / ❌ Fail

## Test Coverage
| Area | Tested | Result |
|------|--------|--------|
| [area] | Yes/No | ✅/❌ |

## 🐛 Issues Found
- **[severity]** [one line description]
(omit section if none)

## 📋 Sign-off Checklist
- [x] Tests pass
- [x] No regressions
- [ ] [any outstanding item]

## 🚀 Deploy Recommendation
Go / No-go — [one line reason including rollback note if No-go]
"""


def revision_prompt(issue_title, previous_qa, human_feedback):
    return f"""A reviewer has feedback on your QA report. Update it.

TASK: {issue_title}

YOUR QA REPORT:
{previous_qa}

FEEDBACK:
{human_feedback}

Address the feedback. If it resolves blocking issues, update the checklist and deploy recommendation. Return the updated report using the same structured format.
"""
