import argparse
import subprocess
import json
import os

parser = argparse.ArgumentParser()
parser.add_argument("--issue_number")
parser.add_argument("--title")
parser.add_argument("--body")
parser.add_argument("--repo_path")

args = parser.parse_args()

repo_path = args.repo_path
issue_number = args.issue_number

branch_name = f"ai/fix-issue-{issue_number}"

try:
    os.chdir(repo_path)

    # checkout fresh branch
    subprocess.run(["git", "checkout", "main"], check=True)
    subprocess.run(["git", "pull"], check=True)
    subprocess.run(["git", "checkout", "-b", branch_name], check=True)

    # 🔥 THIS IS WHERE CLAUDE CODE COMES IN
    # For now we simulate fix (manual edit expected)

    # Example: fix subtract function
    file_path = "src/calculator.js"

    with open(file_path, "r") as f:
        content = f.read()

    fixed = content.replace("return a + b;", "return a - b;")

    with open(file_path, "w") as f:
        f.write(fixed)

    # commit changes
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", f"Fix issue #{issue_number}"], check=True)

    # push branch
    subprocess.run(["git", "push", "-u", "origin", branch_name], check=True)

    print(json.dumps({
        "status": "success",
        "branch": branch_name,
        "pr_title": f"Fix issue #{issue_number}",
        "pr_body": f"Fixes issue #{issue_number}",
        "approved": True
    }))

except Exception as e:
    print(json.dumps({
        "status": "error",
        "message": str(e),
        "approved": False
    }))
    