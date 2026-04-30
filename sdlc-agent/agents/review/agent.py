import re
from shared.claude import ask_claude
from shared.utils import run_git, get_file_tree, read_file
from shared.session import save_session, load_session
from agents.review.prompts import review_prompt, revision_review_prompt

DIMENSIONS = ["Correctness", "Security", "Performance", "Error Handling", "Test Coverage"]


def parse_output(output):
    # Overall verdict from Section 10
    verdict = "FAIL"
    m = re.search(r'## 10\. Verdict\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if not m:
        m = re.search(r'## Verdict\s*\n(.*?)(?=\n##|\Z)', output, re.DOTALL)
    if m and "PASS" in m.group(1).upper():
        verdict = "PASS"

    # Per-dimension statuses from sections 2-6
    dimensions = {}
    section_map = {
        "Correctness": r'## 2\. Correctness',
        "Security": r'## 3\. Security',
        "Performance": r'## 4\. Performance',
        "Error Handling": r'## 5\. Error Handling',
        "Test Coverage": r'## 6\. Test Coverage',
    }
    for dim, header in section_map.items():
        m = re.search(rf'{header}\s*\n(.*?)(?=\n## |\Z)', output, re.DOTALL)
        if m:
            text = m.group(1).strip()
            # Only look at the Status line, not the body (which may mention FAIL in examples)
            status_match = re.search(r'\*\*Status:\s*(PASS|FAIL)\*\*', text)
            if status_match:
                status = status_match.group(1)
            else:
                # Fall back to first line only
                first_line = text.split('\n')[0].upper()
                status = "PASS" if "PASS" in first_line else "FAIL"
            dimensions[dim] = {"status": status, "notes": text[:500]}

    # Blocking issues list
    blocking_issues = []
    m = re.search(r'## 8\. Blocking Issues\s*\n(.*?)(?=\n## |\Z)', output, re.DOTALL)
    if m:
        section = m.group(1).strip()
        if "none" not in section.lower()[:20]:
            blocking_issues = re.findall(r'\d+\.\s+\*\*Issue:\*\*\s*(.+?)(?=\n\d+\.|\Z)', section, re.DOTALL)
            blocking_issues = [b.strip() for b in blocking_issues]

    return verdict, dimensions, blocking_issues


def run(session_id, repo_path=None, branch_name=None, issue_title=None,
        impact_analysis=None, affected_files=None, human_feedback=None):
    session = load_session(session_id) or {}
    repo_path = repo_path or session.get("repo_path")
    branch_name = branch_name or session.get("branch", "")
    issue_title = issue_title or session.get("issue_title") or session.get("requirement", "").split("\n")[0].strip()
    impact_analysis = impact_analysis or session.get("impact_analysis", "")
    affected_files = affected_files or session.get("affected_files", [])
    codebase_analysis = session.get("codebase_analysis", "")
    pr_description = session.get("pr_description", "")

    if not branch_name:
        raise ValueError("branch is required")

    diff = run_git(["diff", f"main...{branch_name}"], cwd=repo_path)
    test_diff = run_git(["diff", f"main...{branch_name}", "--", "*test*", "*spec*"], cwd=repo_path)

    # If this is a re-review after human feedback or developer revisions
    original_review = session.get("review", "")
    if human_feedback and original_review:
        review = ask_claude(revision_review_prompt(
            issue_title, original_review, diff, test_diff, human_feedback
        ))
    else:
        review = ask_claude(review_prompt(
            issue_title, diff, impact_analysis, test_diff, affected_files,
            codebase_analysis, pr_description
        ))

    verdict, dimensions, blocking_issues = parse_output(review)

    # If no blocking issues found, verdict must be PASS regardless of parser result
    if not blocking_issues:
        verdict = "PASS"

    result = {
        "review": review,
        "verdict": verdict,
        "dimensions": dimensions,
        "blocking_issues": blocking_issues,
        "branch": branch_name,
        "issue_title": issue_title,
        "has_blocking_issues": len(blocking_issues) > 0,
        "next_stage": "qa" if verdict == "PASS" else "dev (fix review issues)",
    }

    save_session(session_id, {
        **result,
        "review_verdict": verdict,
        "review_dimensions": dimensions,
        "review_blocking_issues": blocking_issues,
        "stage": "review",
    })
    return result
