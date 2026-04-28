def system_analysis_prompt(requirement, file_tree, file_contents):
    files_section = "\n\n".join(
        f"FILE: {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    return f"""You are a senior Business Analyst with 15+ years of experience across enterprise software projects.
You have just joined a discovery call and been handed a raw requirement. Before writing anything, you must deeply understand the current system.

RAW REQUIREMENT:
{requirement}

CODEBASE FILE TREE:
{file_tree}

CURRENT SYSTEM CODE (relevant files):
{files_section}

Analyse the current system in relation to the requirement. Output ONLY the following sections:

## Current System Capabilities
List every existing feature, function, or behaviour in the codebase that is relevant to this requirement.
For each one, state: what it does, how it works, its inputs/outputs, and any known limitations.

## Current State Gaps
What is missing, broken, or insufficient in the current system relative to the requirement?
Be specific — name functions, modules, data structures.

## Requirement Classification
Classify this requirement as one or more of:
- Bug Fix (something broken that needs fixing)
- Enhancement (existing feature needs extension)
- New Feature (does not exist at all)
- Config/Workaround (can be achieved without code)
- Non-functional (performance, security, scalability)

## Initial Risk Flags
Any concerns about feasibility, scope creep, technical debt, or conflicting requirements spotted immediately.
"""


def brd_prompt(requirement, system_analysis, file_tree):
    return f"""You are a senior Business Analyst producing a comprehensive Business Requirements Document.

RAW REQUIREMENT:
{requirement}

SYSTEM ANALYSIS (your earlier analysis of the current codebase):
{system_analysis}

CODEBASE FILE TREE:
{file_tree}

Produce a detailed, professional BRD. Every section must be specific to this requirement and this codebase.
Do not write generic placeholder text. If something does not apply, explain why.

---

## 1. Executive Summary
Two to three paragraphs. What is being requested, why it matters, and what the expected outcome is.
Include the business value or user impact.

## 2. Stakeholders
List every role or team affected by this requirement:
- Who is requesting it
- Who will use the new functionality
- Who will be impacted by the change (even if not directly using it)
- Who needs to approve it

## 3. Current State
Describe the current behaviour of the system in detail.
Reference specific functions, files, and modules from the codebase.
Include what works, what is missing, and what is technically limiting the current experience.

## 4. Future State
Describe what the system should do after this requirement is implemented.
Be specific: name the functions or modules that will change, and describe the new behaviour precisely.

## 5. Gap Analysis
| Area | Current State | Required State | Gap |
|------|--------------|----------------|-----|
(Fill in every area affected by this requirement)

## 6. What Can Be Done With Config or Workarounds
For each item:
- What the workaround achieves
- Exact steps to implement it (config keys, flags, manual steps)
- Limitations of the workaround vs the full solution
- Whether this is a permanent or temporary measure
If nothing can be done without code changes, state that explicitly and explain why.

## 7. What Needs Development
For each development item:
- **Item:** Name of the change
- **Type:** Bug Fix / Enhancement / New Feature
- **Current behaviour:** What happens today (with code reference)
- **Required behaviour:** What must happen after the change
- **Affected modules:** Specific files and functions that will need to change
- **Estimated complexity:** Low / Medium / High — with reasoning
- **Dependencies:** Does this depend on any other item in this list?

## 8. User Stories
Write one user story per distinct use case. Use this format exactly:

### Story N: <title>
**As a** [specific user role]
**I want to** [specific action or capability]
**So that** [specific business outcome]

**Acceptance Criteria (Given/When/Then):**
- Given [precondition], When [action], Then [expected outcome]
- Given [precondition], When [action], Then [expected outcome]
(Write at least 3 criteria per story, including edge cases and error conditions)

**Out of Scope for this story:**
- List what this story explicitly does NOT cover

## 9. Non-Functional Requirements
For each that applies:
- **Performance:** Response time, throughput, or load expectations
- **Security:** Authentication, authorisation, data validation, input sanitisation
- **Reliability:** Error handling, fallback behaviour, data integrity
- **Scalability:** Expected growth or load patterns
- **Maintainability:** Code standards, documentation, testability requirements
State "Not applicable" with reasoning for any that do not apply.

## 10. Assumptions
List every assumption being made. For each:
- The assumption itself
- What happens if this assumption is wrong
- How to validate it

## 11. Constraints
Technical, business, time, or resource constraints that limit how this can be implemented.

## 12. Dependencies
External systems, libraries, APIs, or other requirements this depends on.

## 13. Risks
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
(List every risk identified)

## 14. Clarification Questions
List every question that MUST be answered before development begins.
For each question:
- **Question:** The specific question
- **Why it matters:** What decision or design choice depends on the answer
- **Impact if unanswered:** What will be assumed or blocked

If all questions are resolved, write "None — requirement is fully specified."
"""


def followup_prompt(requirement, system_analysis, previous_brd, clarification_qa, file_tree):
    return f"""You are a senior Business Analyst refining a Business Requirements Document based on answers to your clarification questions.

ORIGINAL REQUIREMENT:
{requirement}

SYSTEM ANALYSIS:
{system_analysis}

PREVIOUS BRD:
{previous_brd}

ANSWERS TO YOUR CLARIFICATION QUESTIONS:
{clarification_qa}

CODEBASE FILE TREE:
{file_tree}

Update the BRD incorporating all the answers. Be specific — update every section that is affected by the new information.
Resolve every open question. Where an answer changes a requirement, user story, or acceptance criteria, update it precisely.
If any answers introduce new questions, list them under Section 14.
If all questions are resolved, set Section 14 to "None — requirement is fully specified."

Return the complete updated BRD using the same section numbering.
"""
