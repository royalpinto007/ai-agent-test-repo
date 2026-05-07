import subprocess
import re
from shared.claude import ask_claude
from shared.utils import run_git
from shared.session import save_session, load_session
from agents.security.prompts import security_review_prompt


def _run_tool(cmd, cwd, timeout=60):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _detect_stack(repo_path):
    import os
    files = os.listdir(repo_path)
    if "package.json" in files:
        return "node"
    if "requirements.txt" in files or "pyproject.toml" in files or "setup.py" in files:
        return "python"
    if "go.mod" in files:
        return "go"
    if "pom.xml" in files:
        return "java"
    return "unknown"


def _run_scans(repo_path, branch_name, main_branch):
    results = {}
    stack = _detect_stack(repo_path)

    # ── Dependency vulnerabilities ──────────────────────────────────────────
    if stack == "node":
        out = _run_tool(["npm", "audit", "--json"], repo_path)
        if out:
            # Summarise — just count severities rather than dump the full JSON
            try:
                import json
                data = json.loads(out)
                vulns = data.get("vulnerabilities", {})
                summary_lines = []
                for name, v in list(vulns.items())[:20]:
                    summary_lines.append(f"{v.get('severity','?').upper()} — {name}: {v.get('via', ['?'])[0] if isinstance(v.get('via'), list) else v.get('via','?')}")
                results["npm audit"] = "\n".join(summary_lines) if summary_lines else "No vulnerabilities found."
            except Exception:
                results["npm audit"] = out[:2000]

    elif stack == "python":
        out = _run_tool(["pip-audit", "--format", "columns"], repo_path)
        results["pip-audit"] = out[:2000] if out else ""

    elif stack == "go":
        out = _run_tool(["govulncheck", "./..."], repo_path)
        results["govulncheck"] = out[:2000] if out else ""

    # ── Secret scanning ─────────────────────────────────────────────────────
    for tool, cmd in [
        ("gitleaks", ["gitleaks", "detect", "--source", ".", "--no-git"]),
        ("trufflehog", ["trufflehog", "git", "file://.", "--only-verified", "--json"]),
    ]:
        out = _run_tool(cmd, repo_path, timeout=30)
        if out:
            results[tool] = out[:2000]
            break  # one secrets scanner is enough

    # ── Diff-level stats ────────────────────────────────────────────────────
    try:
        diff_stat = run_git(["diff", "--stat", f"origin/{main_branch}...{branch_name}"], cwd=repo_path)
        results["diff stat"] = diff_stat
    except Exception:
        pass

    return results


def _parse_verdict(output):
    m = re.search(r'\*\*Verdict\*\*\s*\n(PASS|WARN|FAIL)', output, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    if "FAIL" in output[:200]:
        return "FAIL"
    if "WARN" in output[:200]:
        return "WARN"
    return "PASS"


def run(session_id, repo_path=None, branch_name=None, issue_title=None, main_branch=None):
    session = load_session(session_id) or {}
    repo_path = repo_path or session.get("repo_path")
    branch_name = branch_name or session.get("branch", "")
    issue_title = issue_title or session.get("issue_title") or session.get("requirement", "").split("\n")[0].strip()
    main_branch = main_branch or session.get("main_branch", "main")

    if not branch_name:
        raise ValueError("branch is required")

    try:
        diff = run_git(["diff", f"origin/{main_branch}...{branch_name}"], cwd=repo_path)
    except Exception:
        diff = ""

    tool_outputs = _run_scans(repo_path, branch_name, main_branch)
    analysis = ask_claude(security_review_prompt(issue_title, diff, tool_outputs))
    verdict = _parse_verdict(analysis)

    result = {
        "security_output": analysis,
        "verdict": verdict,
        "passed": verdict != "FAIL",
        "tool_outputs": {k: v[:500] for k, v in tool_outputs.items()},
        "branch": branch_name,
        "issue_title": issue_title,
        "next_stage": "review" if verdict != "FAIL" else "dev (security issues)",
    }

    save_session(session_id, {**result, "stage": "security", "security_verdict": verdict})
    return result
