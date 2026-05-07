import subprocess
import os
import urllib.request
import urllib.error
import json
from shared.session import save_session, load_session
from shared.config import get_repo_config


def _run_command(cmd, cwd, timeout=300):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except Exception as e:
        return False, str(e)


def _smoke_test(cmd, cwd):
    if not cmd:
        return True, "No smoke test configured."
    ok, out = _run_command(cmd, cwd)
    return ok, out


def _get_pr_number(repo_path, branch_name, token, owner, repo):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/pulls?head={owner}:{branch_name}&state=open",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            prs = json.loads(resp.read())
            return prs[0]["number"] if prs else None
    except Exception:
        return None


def _merge_pr(owner, repo, pr_number, token, merge_method="squash"):
    payload = json.dumps({"merge_method": merge_method}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/merge",
        data=payload,
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
        method="PUT"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return True, json.loads(resp.read()).get("message", "Merged")
    except urllib.error.HTTPError as e:
        return False, e.read().decode()


def _delete_branch(owner, repo, branch_name, token):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{branch_name}",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
        method="DELETE"
    )
    try:
        urllib.request.urlopen(req)
        return True
    except Exception:
        return False


def _create_release(owner, repo, token, tag, name, body, main_branch):
    payload = json.dumps({
        "tag_name": tag,
        "target_commitish": main_branch,
        "name": name,
        "body": body,
        "draft": False,
        "prerelease": False,
    }).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/releases",
        data=payload,
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            return data.get("html_url", "")
    except Exception:
        return ""


def _get_merged_prs_since_last_tag(owner, repo, token, main_branch):
    """Get titles of PRs merged to main_branch since the last release tag."""
    # Get latest release
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req) as resp:
            last_release = json.loads(resp.read())
            since = last_release.get("published_at", "")
    except Exception:
        since = ""

    # Get merged PRs
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=closed&base={main_branch}&per_page=30"
    if since:
        url += f"&sort=updated&direction=desc"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req) as resp:
            prs = json.loads(resp.read())
        merged = [p for p in prs if p.get("merged_at") and (not since or p["merged_at"] > since)]
        return [{"number": p["number"], "title": p["title"], "url": p["html_url"]} for p in merged]
    except Exception:
        return []


def _derive_owner_repo(repo_path):
    r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo_path, capture_output=True, text=True)
    remote = r.stdout.strip().replace("git@github.com:", "https://github.com/")
    parts = remote.rstrip(".git").rstrip("/").split("/")
    return parts[-2], parts[-1]


def run(session_id, env="stage", repo_path=None):
    """
    env: "stage" or "prod"
    Runs the deploy command for the given env from repos.json deploy config,
    runs smoke test, auto-merges PR (on prod), creates GitHub release (on prod).
    """
    session = load_session(session_id) or {}
    repo_path = repo_path or session.get("repo_path")
    branch_name = session.get("branch", "")
    main_branch = session.get("main_branch", "main")
    issue_title = session.get("issue_title") or session.get("requirement", "").split("\n")[0].strip()
    token = os.environ.get("GITHUB_TOKEN", "")

    owner, repo = _derive_owner_repo(repo_path)

    # Load deploy config
    parts = session_id.rsplit("-", 1)
    owner_repo_key = parts[0].replace("-", "/", 1) if "-" in session_id else ""
    cfg = get_repo_config(*owner_repo_key.split("/")) if "/" in owner_repo_key else {}
    deploy_cfg = (cfg or {}).get("deploy", {}).get(env, {})

    deploy_command = deploy_cfg.get("command")
    smoke_command = deploy_cfg.get("smoke_test")

    # ── Run deploy ───────────────────────────────────────────────────────────
    deploy_ok = True
    deploy_output = "No deploy command configured for this environment."
    if deploy_command:
        deploy_ok, deploy_output = _run_command(deploy_command, repo_path)

    # ── Smoke test ───────────────────────────────────────────────────────────
    smoke_ok = True
    smoke_output = "No smoke test configured."
    if deploy_ok and smoke_command:
        smoke_ok, smoke_output = _smoke_test(smoke_command, repo_path)

    overall_ok = deploy_ok and smoke_ok

    # ── Auto-merge PR + delete branch (on stage success or prod) ─────────────
    merge_result = None
    branch_deleted = False
    release_url = ""

    if overall_ok and token and branch_name:
        pr_number = _get_pr_number(repo_path, branch_name, token, owner, repo)
        if pr_number:
            merged, merge_msg = _merge_pr(owner, repo, pr_number, token)
            merge_result = {"pr": pr_number, "merged": merged, "message": merge_msg}
            if merged:
                branch_deleted = _delete_branch(owner, repo, branch_name, token)

        # ── Create GitHub release on prod deploy ─────────────────────────────
        if env == "prod" and merged:
            import datetime
            tag = f"v{datetime.date.today().isoformat()}-{session_id.split('-')[-1]}"
            merged_prs = _get_merged_prs_since_last_tag(owner, repo, token, main_branch)
            release_body = f"## Changes\n" + "\n".join(
                f"- #{p['number']} {p['title']}" for p in merged_prs
            ) if merged_prs else f"Deployed from session `{session_id}`."
            release_url = _create_release(owner, repo, token, tag, f"Release {tag}", release_body, main_branch)

    result = {
        "env": env,
        "deploy_ok": deploy_ok,
        "deploy_output": deploy_output[:2000],
        "smoke_ok": smoke_ok,
        "smoke_output": smoke_output[:1000],
        "overall_ok": overall_ok,
        "merge_result": merge_result,
        "branch_deleted": branch_deleted,
        "release_url": release_url,
        "issue_title": issue_title,
        "next_stage": f"prod deployment" if (env == "stage" and overall_ok) else ("done" if overall_ok else f"{env} deploy failed"),
    }

    save_session(session_id, {**result, "stage": f"deploy-{env}"})
    return result
