def brd_review_prompt(brd, system_analysis, file_tree, sdd="", other_repos=None):
    sdd_section = f"\nSOLUTION DESIGN:\n{sdd}" if sdd else ""
    other_repos_section = ""
    if other_repos:
        repos_list = "\n".join(f"- {r}" for r in other_repos)
        other_repos_section = f"\nOTHER REGISTERED REPOS (that could be affected):\n{repos_list}\n"

    return f"""You're the PM reviewing this before dev starts. Make sure the work is well-scoped and a developer has everything they need.

Scale your output to the size of the change. One small task = short review. Multiple features = more detail. Don't pad.

SYSTEM ANALYSIS:
{system_analysis}

REQUIREMENTS:
{brd}
{sdd_section}

FILE TREE:
{file_tree}
{other_repos_section}
---

**Requirements check**
Are the requirements clear and complete? Flag anything ambiguous, missing, or contradictory. If everything looks solid, one line is fine.

**Task breakdown**
Break the work into tasks a single developer can pick up.

For each task:

### Task [N]: <title>
- **Type:** Bug Fix / Enhancement / New Feature / Refactor / Test
- **Description:** What to build, specific enough that a dev doesn't need to ask questions
- **Acceptance Criteria:** The conditions this task must satisfy
- **Affected Files:** Best guess from the file tree
- **Depends On:** Task numbers, or "None"
- **Effort Estimate:** XS (<1h) / S (1-4h) / M (half day) / L (1 day) / XL (2+ days)
- **Complexity:** Low / Medium / High
- **Risk:** Low / Medium / High
- **Priority:** P1 (must have) / P2 (should have) / P3 (nice to have)

**Cross-repo impact** *(only fill this in if the change genuinely requires code changes in another registered repo)*
For each affected repo:

### Cross-repo: <owner/repo>
- **What needs to change:** Specific description of what must change in that repo
- **Why:** Why this repo is affected — what dependency or integration requires the change
- **Suggested issue title:** A clear one-line title for the issue to open in that repo
- **Suggested issue body:** Full description with acceptance criteria for that repo's issue

If no other repos are affected: "None — changes are contained to this repo."

**Questions for the BA** *(only if something would actually block a dev from starting)*
If none: "None — ready to go."

## 10. PM Recommendation

**Ready for development:** Yes / No / Partially

If not: what's blocking and who needs to resolve it.
"""


def questions_followup_prompt(brd, previous_pm_output, ba_answers, file_tree):
    return f"""You asked the BA some questions and got answers. Update your PM review.

REQUIREMENTS:
{brd}

YOUR REVIEW:
{previous_pm_output}

ANSWERS:
{ba_answers}

FILE TREE:
{file_tree}

Update the tasks and questions based on the answers. If answers add or remove scope, adjust the task list. Return the updated review.
"""


def revision_prompt(brd, previous_pm_output, human_feedback, file_tree):
    return f"""A reviewer has feedback on your PM review. Update it.

REQUIREMENTS:
{brd}

YOUR REVIEW:
{previous_pm_output}

FEEDBACK:
{human_feedback}

FILE TREE:
{file_tree}

Address the feedback — split, merge, reprioritise, or rewrite tasks as asked. Return the updated review.
"""
