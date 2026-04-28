def pm_prompt(brd, file_tree):
    return f"""You are a Project Manager reviewing a Business Requirements Document.

BRD:
{brd}

CODEBASE FILE TREE:
{file_tree}

Review the BRD and decompose it into actionable development tasks.

OUTPUT FORMAT (use exactly these headings):

## BRD Review
Gaps, ambiguities, missing acceptance criteria, or risks in the BRD.

## Questions for the BA
Remaining clarifications needed. If none, write "None."

## Task Breakdown
For each task write:

### Task N: <title>
- **Description:** What needs to be done
- **Affected Files:** Files from the file tree likely to be touched
- **Dependencies:** Which task numbers must complete first. If none, write "None."
- **Effort:** XS / S / M / L / XL
- **Risk:** Low / Medium / High — and why
- **Priority:** P1 / P2 / P3

## Execution Order
Tasks in the order they should be developed, respecting dependencies.

## Parallelisation
Which tasks can run in parallel and which must be sequential.
"""
