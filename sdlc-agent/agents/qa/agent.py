import re
from shared.claude import ask_claude
from shared.session import save_session, load_session
from agents.qa.prompts import qa_prompt, revision_prompt as qa_revision_prompt


def parse_output(output):
    # QA Verdict from Section 8
    approved = False
    m = re.search(r'## 8\. QA Verdict\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if not m:
        m = re.search(r'## QA Verdict\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if m and "APPROVED" in m.group(1).upper():
        approved = True

    # Risk level from Section 5
    risk = "UNKNOWN"
    m = re.search(r'## 5\. Regression Risk Assessment\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if m:
        text = m.group(1).upper()
        for level in ["HIGH", "MEDIUM", "LOW"]:
            if level in text[:200]:
                risk = level
                break

    # Stage gate status from Section 6
    stage_gate = "BLOCKED"
    m = re.search(r'\*\*STAGE Gate:\s*(OPEN|BLOCKED)\*\*', output, re.IGNORECASE)
    if m:
        stage_gate = m.group(1).upper()

    # Prod gate status from Section 7
    prod_gate = "BLOCKED"
    m = re.search(r'\*\*PROD Gate:\s*(OPEN|BLOCKED)\*\*', output, re.IGNORECASE)
    if m:
        prod_gate = m.group(1).upper()

    # Unresolved blocking issues — skip table cell lines (contain |)
    unresolved = []
    m = re.search(r'## 4\. Peer Review Follow-up\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if m:
        section = m.group(1)
        unresolved = re.findall(r'^(?!.*\|).*UNRESOLVED.*?:\s*(.+)', section, re.MULTILINE | re.IGNORECASE)

    return approved, risk, stage_gate, prod_gate, unresolved


def run(session_id, issue_title=None, test_output=None, review_verdict=None,
        review_dimensions=None, impact_analysis=None, human_feedback=None):
    session = load_session(session_id) or {}
    issue_title = issue_title or session.get("issue_title") or session.get("requirement", "").split("\n")[0].strip()
    test_output = test_output or session.get("test_output", "")
    review_verdict = review_verdict or session.get("review_verdict", "")
    review_dimensions = review_dimensions or session.get("review_dimensions", {})
    impact_analysis = impact_analysis or session.get("impact_analysis", "")
    codebase_analysis = session.get("codebase_analysis", "")
    pr_description = session.get("pr_description", "")
    sdd = session.get("sdd", "")

    if not issue_title:
        raise ValueError("issue_title is required")

    previous_qa = session.get("qa_output", "")
    if human_feedback and previous_qa:
        qa = ask_claude(qa_revision_prompt(issue_title, previous_qa, human_feedback))
    else:
        qa = ask_claude(qa_prompt(
            issue_title, test_output, review_verdict, review_dimensions,
            impact_analysis, codebase_analysis, pr_description, sdd
        ))

    approved, risk, stage_gate, prod_gate, unresolved_issues = parse_output(qa)

    result = {
        "qa_output": qa,
        "approved": approved,
        "risk": risk,
        "stage_gate": stage_gate,
        "prod_gate": prod_gate,
        "unresolved_review_issues": unresolved_issues,
        "issue_title": issue_title,
        "pipeline_complete": approved,
        "next_stage": "stage deployment" if approved else "dev (QA rejected)",
    }

    save_session(session_id, {**result, "stage": "qa"})
    return result
