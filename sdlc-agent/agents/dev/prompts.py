def dev_prompt(issue_title, issue_description, file_contents, affected_files, file_tree):
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    affected_section = "\n".join(f"- {f}" for f in affected_files) if affected_files else "None identified"

    return f"""You are a senior software engineer implementing a task.

TASK TITLE: {issue_title}

TASK DESCRIPTION:
{issue_description}

FILES THAT MAY BE AFFECTED (from dependency analysis):
{affected_section}

RELEVANT FILE CONTENTS:
{files_section}

FULL CODEBASE FILE TREE:
{file_tree}

INSTRUCTIONS:
- Implement ONLY what is described in the task.
- Add a brief inline comment above every change explaining WHY (not what).
- Do not remove or alter existing comments, tests, or unrelated code.
- Write or update unit tests covering: happy path, edge cases, boundary values, error conditions.
- Check all affected files — update them if your change breaks their interface.
- Your entire response must be valid code — no prose outside the headings below.

OUTPUT FORMAT (use exactly these headings):

## Impact Analysis
For each affected file: does it need changes and why / why not. List indirect effects.

## Changes
FILE: <relative path>
```javascript
<complete updated file content>
```

## Unit Tests
FILE: <relative test file path>
```javascript
<complete test file content>
```

## Summary
What was changed, why, and what was verified.
"""


def retry_prompt(issue_title, previous_output, test_output, attempt):
    return f"""You are a senior software engineer. Your implementation attempt {attempt} failed tests.

TASK: {issue_title}

TEST FAILURES:
{test_output}

YOUR PREVIOUS OUTPUT:
{previous_output}

Analyse the failures. Fix the root cause — do not patch the assertion.
Return the corrected implementation using the same format (## Impact Analysis, ## Changes, ## Unit Tests, ## Summary).
Your entire response must be valid code — no prose outside the headings.
"""
