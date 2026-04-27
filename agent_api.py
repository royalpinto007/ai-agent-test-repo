from flask import Flask, request, jsonify
import subprocess
import os

app = Flask(__name__)

@app.route("/run-agent", methods=["POST"])
def run_agent():
    data = request.json

    issue_number = data["issue_number"]
    repo_path = data["repo_path"]

    branch_name = f"ai/fix-issue-{issue_number}"

    try:
        os.chdir(repo_path)

        subprocess.run(["git", "checkout", "main"])
        subprocess.run(["git", "pull"])
        subprocess.run(["git", "checkout", "-b", branch_name])

        file_path = "src/calculator.js"

        with open(file_path, "r") as f:
            content = f.read()

        fixed = content.replace("return a + b;", "return a - b;")

        with open(file_path, "w") as f:
            f.write(fixed)

        subprocess.run(["git", "add", "."])
        subprocess.run(["git", "commit", "-m", f"Fix issue #{issue_number}"])
        subprocess.run(["git", "push", "-u", "origin", branch_name])

        return jsonify({
            "status": "success",
            "branch": branch_name,
            "approved": True
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "approved": False
        })

if __name__ == "__main__":
    app.run(port=5000)