def security_review_prompt(issue_title, diff, tool_outputs):
    tools_section = "\n\n".join(
        f"### {name}\n```\n{output[:3000]}\n```"
        for name, output in tool_outputs.items()
        if output.strip()
    ) or "No tool output available."

    return f"""You're a security engineer reviewing a code change before it merges.

TASK: {issue_title}

CODE DIFF:
{diff[:4000]}

AUTOMATED SCAN RESULTS:
{tools_section}

---

Be direct. Only flag things that are real issues in this specific change.

**Dependency vulnerabilities**
List any CVEs or high/critical vulnerabilities found in the scan. If none: "None found."

**Secrets / credential exposure**
Any hardcoded secrets, tokens, or credentials in the diff? If none: "None found."

**Code-level security issues**
Injection risks, unsafe operations, missing input validation, insecure defaults — only from the diff. If none: "None found."

**Verdict**
PASS — safe to proceed to review
WARN — issues present but not blocking (note them)
FAIL — must fix before review (list what)

One sentence summary.
"""
