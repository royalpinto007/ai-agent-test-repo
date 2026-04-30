def solution_design_prompt(brd, system_analysis, file_tree):
    return f"""You're a Solution Architect writing a technical design. Your job is to give developers a clear enough picture that they can implement without guessing — but don't over-engineer it.

**Scale to the complexity.** A simple bug fix might just need "change this function to do X, here's why". A new subsystem needs a full design. Skip sections that don't apply.

SYSTEM ANALYSIS:
{system_analysis}

REQUIREMENTS:
{brd}

FILE TREE:
{file_tree}

---

**What we're changing and why**
Plain English — what is the problem and what's the approach? If you considered alternatives, mention them briefly and why you rejected them.

**Files and components involved**
Which files change, which are new, which are untouched. For any file that changes, say what specifically changes.

**How it works — technical detail**
For each function being added or changed:
- What it does, its signature, inputs/outputs
- The key logic — algorithm, edge cases, error conditions
- Why this approach (if non-obvious)

For a trivial change (e.g. add a null check) this can be one sentence. For a new algorithm, be thorough.

**Interface changes** *(if any)*
Before → After for any function that changes its signature. Who calls it?

**Error handling**
How are error cases handled? Be specific about what throws, what's caught, what the user/caller sees.

**Tests needed**
What to test — happy path, edge cases, error conditions. Don't list tests you're confident the developer will write anyway; focus on cases they might miss.

**Open questions** *(only if genuinely blocking)*
If none: "None — ready to implement."
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

Address every point. If you disagree with something, say so briefly and explain your reasoning. Return the updated design.
"""
