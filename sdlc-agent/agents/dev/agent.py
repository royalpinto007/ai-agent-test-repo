import re
from shared.claude import ask_claude
from shared.utils import get_file_tree, read_file, write_file, run_git, run_tests, identify_relevant_files
from shared.session import save_session, load_session
from agents.dev.prompts import dev_prompt, retry_prompt

MAX_RETRIES = 3


def parse_output(output):
    changes = {}
    tests = {}
    for path, content in re.findall(r'FILE:\s*(.+?)\n```(?:\w+)?\n(.*?)```', output, re.DOTALL):
        path = path.strip()
        content = content.strip()
        if "test" in path.lower() or "spec" in path.lower():
            tests[path] = content
        else:
            changes[path] = content

    impact = ""
    m = re.search(r'## Impact Analysis\n(.*?)(?=##|\Z)', output, re.DOTALL)
    if m:
        impact = m.group(1).strip()

    summary = ""
    m = re.search(r'## Summary\n(.*?)(?=##|\Z)', output, re.DOTALL)
    if m:
        summary = m.group(1).strip()

    return changes, tests, impact, summary


def run(session_id, issue_title, issue_description, repo_path, branch_name=None):
    session = load_session(session_id) or {}
    repo_path = repo_path or session.get("repo_path")
    branch_name = branch_name or f"ai/feature-{session_id[:8]}"

    file_tree = get_file_tree(repo_path)
    file_tree_str = "\n".join(file_tree)

    seed_files, affected_files = identify_relevant_files(issue_title, issue_description, repo_path, file_tree)

    file_contents = {}
    for f in set(seed_files + affected_files):
        content = read_file(repo_path, f)
        if content:
            file_contents[f] = content

    attempts = []
    output = ask_claude(dev_prompt(issue_title, issue_description, file_contents, affected_files, file_tree_str))

    for attempt in range(1, MAX_RETRIES + 1):
        changes, tests, impact, summary = parse_output(output)

        try:
            run_git(["checkout", "main"], cwd=repo_path)
            run_git(["pull"], cwd=repo_path)
            if attempt == 1:
                run_git(["checkout", "-b", branch_name], cwd=repo_path)
            else:
                run_git(["checkout", branch_name], cwd=repo_path)
        except RuntimeError:
            run_git(["checkout", branch_name], cwd=repo_path)

        for path, content in {**changes, **tests}.items():
            write_file(repo_path, path, content)

        test_passed, test_output = run_tests(repo_path)
        attempts.append({"attempt": attempt, "test_passed": test_passed, "test_output": test_output})

        if test_passed:
            break
        if attempt < MAX_RETRIES:
            output = ask_claude(retry_prompt(issue_title, output, test_output, attempt))

    all_files = list({**changes, **tests}.keys())
    for path in all_files:
        run_git(["add", path], cwd=repo_path)

    final = attempts[-1]
    run_git(["commit", "-m", f"feat: {issue_title} (attempts: {len(attempts)}, tests: {'pass' if final['test_passed'] else 'fail'})"], cwd=repo_path)
    run_git(["push", "-u", "origin", branch_name], cwd=repo_path)

    result = {
        "branch": branch_name,
        "issue_title": issue_title,
        "impact_analysis": impact,
        "summary": summary,
        "files_changed": list(changes.keys()),
        "test_files": list(tests.keys()),
        "affected_files": affected_files,
        "test_passed": final["test_passed"],
        "test_output": final["test_output"],
        "attempts": len(attempts),
        "next_stage": "review",
    }

    save_session(session_id, {**result, "stage": "dev", "repo_path": repo_path})
    return result
