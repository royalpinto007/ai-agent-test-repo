import re
from shared.claude import ask_claude
from shared.session import save_session, load_session
from agents.qa.prompts import qa_prompt


def parse_output(output):
    approved = False
    m = re.search(r'## QA Verdict\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if m and "APPROVED" in m.group(1).upper():
        approved = True

    risk = "UNKNOWN"
    m = re.search(r'## Regression Risk\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if m:
        text = m.group(1).upper()
        for level in ["HIGH", "MEDIUM", "LOW"]:
            if level in text:
                risk = level
                break

    return approved, risk


def run(session_id, issue_title=None, test_output=None, review_verdict=None,
        review_dimensions=None, impact_analysis=None):
    session = load_session(session_id) or {}
    issue_title = issue_title or session.get("issue_title", "")
    test_output = test_output or session.get("test_output", "")
    review_verdict = review_verdict or session.get("review_verdict", "")
    review_dimensions = review_dimensions or session.get("review_dimensions", {})
    impact_analysis = impact_analysis or session.get("impact_analysis", "")

    if not issue_title:
        raise ValueError("issue_title is required")

    qa = ask_claude(qa_prompt(issue_title, test_output, review_verdict, review_dimensions, impact_analysis))
    approved, risk = parse_output(qa)

    result = {
        "qa_output": qa,
        "approved": approved,
        "risk": risk,
        "issue_title": issue_title,
        "pipeline_complete": True,
    }

    save_session(session_id, {**result, "stage": "qa"})
    return result
