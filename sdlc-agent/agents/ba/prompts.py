def initial_prompt(requirement, file_tree):
    return f"""You are a senior Business Analyst working on a software project.

RAW REQUIREMENT:
{requirement}

CODEBASE FILE TREE:
{file_tree}

Analyse this requirement and produce a structured Business Requirements Document.

OUTPUT FORMAT (use exactly these headings):

## Summary
One paragraph describing what is being requested.

## Scope
What is in scope and what is explicitly out of scope.

## What Can Be Done With Config or Workarounds
Parts of the requirement handleable without code changes. If none, write "None."

## What Needs Development
Each feature or fix requiring code changes. Name the function, module, or behaviour.

## User Stories
As a [user], I want [goal] so that [reason].

## Acceptance Criteria
Measurable bullet points that must all be true for this to be complete.

## Assumptions
Assumptions made about the requirement.

## Clarification Questions
Questions that MUST be answered before development begins. If none, write "None."
"""


def followup_prompt(requirement, previous_brd, clarification_qa):
    return f"""You are a senior Business Analyst refining a Business Requirements Document.

ORIGINAL REQUIREMENT:
{requirement}

PREVIOUS BRD DRAFT:
{previous_brd}

ANSWERS TO YOUR CLARIFICATION QUESTIONS:
{clarification_qa}

Update the BRD based on the answers. Resolve all open questions.
Produce a final complete BRD using the same section headings.
Set "Clarification Questions" to "None." if all are resolved.
"""
