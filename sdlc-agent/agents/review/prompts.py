def review_prompt(issue_title, diff, impact_analysis, test_diff, affected_files):
    affected_section = "\n".join(f"- {f}" for f in affected_files) if affected_files else "None"
    return f"""You are a senior software engineer conducting a thorough peer code review.

TASK: {issue_title}

IMPACT ANALYSIS (from developer):
{impact_analysis}

FILES POTENTIALLY AFFECTED:
{affected_section}

CODE DIFF:
{diff}

TEST DIFF:
{test_diff}

Review each dimension independently using exactly these headings:

## Verdict
PASS or FAIL (overall)

### Correctness
PASS or FAIL — Does the implementation correctly solve the task? Any logic errors or missing cases?

### Security
PASS or FAIL — Any injection risks, data exposure, insecure defaults, or missing input validation?

### Performance
PASS or FAIL — Unnecessary loops, redundant computation, memory leaks, or blocking operations?

### Error Handling
PASS or FAIL — Are error conditions handled? Edge cases covered? Fails gracefully?

### Test Coverage
PASS or FAIL — Do tests cover happy path, edge cases, boundary values, and error conditions?

## Issues Found
Numbered list of all blocking issues (must fix before merge). If none, write "None."

## Suggestions
Numbered list of non-blocking improvements. If none, write "None."

## Summary
One paragraph overall assessment.
"""
