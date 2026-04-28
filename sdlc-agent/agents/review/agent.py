import re
from shared.claude import ask_claude
from shared.utils import run_git
from shared.session import save_session, load_session
from agents.review.prompts import review_prompt


def parse_output(output):
    verdict = "FAIL"
    m = re.search(r'## Verdict\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if m and "PASS" in m.group(1).upper():
        verdict = "PASS"

    dimensions = {}
    for dim in ["Correctness", "Security", "Performance", "Error Handling", "Test Coverage"]:
        m = re.search(rf'### {dim}\s*\n(.*?)(?=###|##|\Z)', output, re.DOTALL)
        if m:
            text = m.group(1).strip()
            status = "PASS" if "PASS" in text[:20].upper() else "FAIL" if "FAIL" in text[:20].upper() else "N/A"
            dimensions[dim] = {"status": status, "notes": text}

    return verdict, dimensions


def run(session_id, repo_path=None, branch_name=None, issue_title=None, impact_analysis=None, affected_files=None):
    session = load_session(session_id) or {}
    repo_path = repo_path or session.get("repo_path")
    branch_name = branch_name or session.get("branch", "")
    issue_title = issue_title or session.get("issue_title", "")
    impact_analysis = impact_analysis or session.get("impact_analysis", "")
    affected_files = affected_files or session.get("affected_files", [])

    if not branch_name:
        raise ValueError("branch is required")

    diff = run_git(["diff", f"main...{branch_name}"], cwd=repo_path)
    test_diff = run_git(["diff", f"main...{branch_name}", "--", "*test*", "*spec*"], cwd=repo_path)

    review = ask_claude(review_prompt(issue_title, diff, impact_analysis, test_diff, affected_files))
    verdict, dimensions = parse_output(review)

    result = {
        "review": review,
        "verdict": verdict,
        "dimensions": dimensions,
        "branch": branch_name,
        "issue_title": issue_title,
        "next_stage": "qa",
    }

    save_session(session_id, {**result, "review_verdict": verdict, "review_dimensions": dimensions, "stage": "review"})
    return result
