def ba_prompt(requirement, file_tree):
    return f"""You are a senior Business Analyst working on a software project.

RAW REQUIREMENT:
{requirement}

CODEBASE FILE TREE:
{file_tree}

Your job is to produce a structured Business Requirements Document (BRD).

OUTPUT FORMAT (use exactly these headings):

## Summary
One paragraph describing what is being requested.

## What Can Be Done With Config or Workarounds
List any parts of the requirement that can be handled without code changes.

## What Needs Development
List each feature or fix that requires code changes. Be specific about functionality.

## User Stories
Write one or more user stories in the format:
As a [user], I want [goal] so that [reason].

## Acceptance Criteria
Bullet list of measurable conditions that must be true for this to be considered complete.

## Clarification Questions
List any questions that need answers before development can begin. If none, write "None."
"""


def pm_prompt(brd, file_tree):
    return f"""You are a Project Manager reviewing a Business Requirements Document.

BRD:
{brd}

CODEBASE FILE TREE:
{file_tree}

Your job is to review the BRD and prepare work assignments for the development team.

OUTPUT FORMAT (use exactly these headings):

## Review Notes
Any gaps, ambiguities, or concerns with the BRD.

## Questions for the BA
Any clarifications needed before work can begin. If none, write "None."

## Issues / Tasks
List each development task as a numbered item with:
- Title
- Description
- Affected files (based on the file tree)
- Priority: High / Medium / Low

## Assignment
State which developer role should handle each task and in what order.
"""


def dev_prompt(issue_title, issue_description, file_contents, file_tree):
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    return f"""You are a senior software engineer implementing a task.

TASK TITLE: {issue_title}
TASK DESCRIPTION:
{issue_description}

RELEVANT FILES:
{files_section}

CODEBASE FILE TREE:
{file_tree}

INSTRUCTIONS:
- Implement ONLY what is described in the task. Do not change unrelated code.
- Add a brief comment above every change explaining why it was made.
- Do not remove existing comments or documentation.
- Return your response in this exact format:

## Impact Analysis
List every file and function that could be affected by this change, including indirect effects.

## Changes
For each file you modify, write:
FILE: <relative file path>
```
<complete updated file content>
```

## Unit Tests
FILE: <relative test file path>
```
<complete test file content>
```

## Summary
One paragraph describing what was changed and why.
"""


def review_prompt(issue_title, file_changes, impact_analysis, test_content):
    return f"""You are a senior software engineer doing a peer code review.

TASK: {issue_title}

IMPACT ANALYSIS:
{impact_analysis}

CODE CHANGES:
{file_changes}

UNIT TESTS:
{test_content}

Review the changes thoroughly. OUTPUT FORMAT (use exactly these headings):

## Verdict
PASS or FAIL

## Summary
One paragraph describing the quality of the change.

## Issues Found
List any bugs, missing edge cases, style violations, or logic errors. If none, write "None."

## Suggestions
Any non-blocking improvements. If none, write "None."
"""


def qa_prompt(issue_title, test_output, review_verdict, review_summary):
    return f"""You are a QA engineer signing off on a software change.

TASK: {issue_title}

PEER REVIEW VERDICT: {review_verdict}
PEER REVIEW SUMMARY: {review_summary}

TEST RESULTS:
{test_output}

Based on the test results and peer review, provide your QA sign-off.

OUTPUT FORMAT (use exactly these headings):

## QA Verdict
APPROVED or REJECTED

## Test Coverage Assessment
Comment on whether the tests adequately cover the change.

## Risk Assessment
Low / Medium / High — and why.

## Notes
Any observations or follow-up items. If none, write "None."
"""
