def brd_review_prompt(brd, system_analysis, file_tree, sdd="", other_repos=None):
    sdd_section = f"\nSOLUTION DESIGN:\n{sdd}" if sdd else ""
    other_repos_section = ""
    if other_repos:
        repos_list = "\n".join(f"- {r}" for r in other_repos)
        other_repos_section = f"\nOTHER REGISTERED REPOS (that could be affected):\n{repos_list}\n"

    return f"""You're the PM reviewing this before dev starts. Output ONLY the structured report below — no prose, no padding.

SYSTEM ANALYSIS:
{system_analysis}

REQUIREMENTS:
{brd}
{sdd_section}

FILE TREE:
{file_tree}
{other_repos_section}
---

## 📋 Task Breakdown

| # | Title | Type | Effort | Priority | Depends On |
|---|-------|------|--------|----------|------------|
| 1 | [title] | Feature/Bug/Refactor | S/M/L | P1/P2/P3 | - |

(add rows as needed — one task per row)

Then emit the full task JSON block required for issue creation:

```json
[
  {{
    "title": "Short imperative title",
    "type": "Bug Fix | Enhancement | New Feature | Refactor | Test",
    "description": "What to build — specific enough that a dev doesn't need to ask questions",
    "acceptance_criteria": "The conditions this task must satisfy",
    "affected_files": "Best guess from the file tree",
    "depends_on": "Task numbers or None",
    "effort": "XS | S | M | L | XL",
    "complexity": "Low | Medium | High",
    "risk": "Low | Medium | High",
    "priority": "P1 | P2 | P3"
  }}
]
```

## 🔗 Cross-Repo Impact
| Repo | Change Needed |
|------|--------------|
| [repo] | [one line] |

(omit table if no other repos are affected — write "None — changes are contained to this repo." instead)

If repos are affected, also emit a JSON block:

```json
[
  {{
    "repo": "owner/repo",
    "what": "Specific description of what must change in that repo",
    "why": "Why this repo is affected",
    "issue_title": "A clear one-line title for the issue to open in that repo",
    "issue_body": "Full description with acceptance criteria for that repo's issue"
  }}
]
```

## ⚡ Recommendation
[1-2 sentences on sequencing, priority callouts, or what's blocking — write "None — ready to go." if nothing is blocking]
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

Update the tasks and questions based on the answers. If answers add or remove scope, adjust the task list. Return the updated review using the same structured format.
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

Address the feedback — split, merge, reprioritise, or rewrite tasks as asked. Return the updated review using the same structured format.
"""
