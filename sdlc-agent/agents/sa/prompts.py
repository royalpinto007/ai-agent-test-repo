def solution_design_prompt(brd, system_analysis, file_tree):
    return f"""You're a Solution Architect writing a technical design. Output ONLY the structured report below — no prose, no padding.

SYSTEM ANALYSIS:
{system_analysis}

REQUIREMENTS:
{brd}

FILE TREE:
{file_tree}

---

## Components Affected
| Component | File/Module | Change Type |
|-----------|-------------|-------------|
| [name]    | [path]      | Add/Modify/Remove |

## Changes Required
**[Component name]**
- [change 1]
- [change 2]

(repeat per component, max 3 components shown in detail)

## Risks
- [risk] — Mitigation: [one line]
(max 3 risks — omit section if none)

## Test Cases
- [ ] [test case]
(max 6 test cases — focus on cases a developer might miss)

## Dependencies
- [dependency or "None"]

## Open Questions
- [question] — Blocking: Yes/No
(omit section if none — otherwise: "None — ready to implement.")
"""


def revision_prompt(brd, previous_sdd, human_feedback, file_tree):
    return f"""A reviewer has feedback on your technical design. Update it.

REQUIREMENTS:
{brd}

YOUR DESIGN:
{previous_sdd}

FEEDBACK:
{human_feedback}

FILE TREE:
{file_tree}

Address every point. If you disagree with something, say so briefly and explain your reasoning. Return the updated design using the same structured format.
"""
