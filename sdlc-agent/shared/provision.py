"""Provision a brand-new Dolibarr custom-module repo from a requirements issue.

The pipeline normally edits an existing registered repo. For a "new module"
request we must first stand the repo up: create it on GitHub, clone it, bind-mount
it into the live Dolibarr htdocs/custom (so the skill's amb_*/REST scaffolding is
live), make it web-writable, and register it in repos.json — then the agentic Dev
stage scaffolds it and opens the PR like any other repo. All idempotent.

Config via env (sensible defaults):
  NEW_MODULE_ORG          default "Thrive-ERP"
  NEW_MODULE_REPO_PREFIX  default "dolibarr_custom_"
  CODE_REPOS_DIR          default "/opt/repos"
  DOL_HTDOCS              live Dolibarr root (enables the live bind-mount)
  DOLIBARR_DEV_MCP_CONFIG MCP config to attach to the new repo entry
"""
import json
import logging
import os
import re
import subprocess
import urllib.error
import urllib.request

from shared.config import _REPOS_PATH, all_repos

log = logging.getLogger("provision")

ORG = os.environ.get("NEW_MODULE_ORG", "Thrive-ERP")
REPO_PREFIX = os.environ.get("NEW_MODULE_REPO_PREFIX", "dolibarr_custom_")
CODE_REPOS_DIR = os.environ.get("CODE_REPOS_DIR", "/opt/repos")


def slugify_module(name):
    """A Dolibarr module dir name: lowercase alphanumeric only."""
    return "".join(c for c in (name or "").lower() if c.isalnum())


def module_target(name):
    """Build a target_repo dict (create=True) for a NEW module named `name`."""
    slug = slugify_module(name)
    if not slug:
        return None
    repo = f"{REPO_PREFIX}{slug}"
    target = {
        "slug": f"{ORG}/{repo}",
        "repo_path": os.path.join(CODE_REPOS_DIR, repo),
        "test_command": ["echo", "no test command detected"],
        "main_branch": "main",
        "dev_mode": "agentic",
        "skill": "dolibarr-dev",
        "module": slug,
        "create": True,
    }
    htdocs = os.environ.get("DOL_HTDOCS", "").strip()
    if htdocs:
        target["dol_htdocs"] = htdocs
    mcp = os.environ.get("DOLIBARR_DEV_MCP_CONFIG", "").strip()
    if mcp:
        target["mcp_config"] = mcp
    return target


def _gh(method, path, token, body=None):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=(json.dumps(body).encode() if body is not None else None),
        method=method,
    )
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read() or b"{}"
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except Exception:
            payload = {}
        return e.code, payload


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def _register(slug, cfg):
    """Persist the new repo into repos.json (drop the transient 'create' flag)."""
    repos = all_repos()
    repos[slug] = {k: v for k, v in cfg.items() if k != "create"}
    tmp = _REPOS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(repos, f, indent=2)
    os.replace(tmp, _REPOS_PATH)


def provision_module(target_repo, token):
    """Create+clone+mount+register the module repo. Idempotent. Returns target_repo
    with repo_path guaranteed to exist as a git clone. Raises on hard failures
    (repo create / clone); system steps (mount/perms) are best-effort + logged."""
    org, name = target_repo["slug"].split("/", 1)
    repo_path = target_repo["repo_path"]
    module = target_repo.get("module") or (name[len(REPO_PREFIX):] if name.startswith(REPO_PREFIX) else name)
    if not token:
        raise RuntimeError("provision: GITHUB_TOKEN not set")

    # 1) create the GitHub repo if it doesn't exist (auto_init => has a 'main' branch)
    status, _ = _gh("GET", f"/repos/{org}/{name}", token)
    if status == 404:
        st, payload = _gh("POST", f"/orgs/{org}/repos", token, {
            "name": name, "private": True, "auto_init": True,
            "description": f"Dolibarr custom module {module} (agent-created)",
        })
        if st not in (200, 201):
            raise RuntimeError(f"provision: repo create failed ({st}): {payload.get('message')}")
        log.warning("provision: created repo %s/%s", org, name)
    elif status >= 400:
        raise RuntimeError(f"provision: repo lookup failed ({status}) for {org}/{name}")

    # 2) clone if not already present
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        url = f"https://x-access-token:{token}@github.com/{org}/{name}.git"
        r = _run(["git", "clone", url, repo_path])
        if r.returncode != 0:
            raise RuntimeError(f"provision: clone failed: {r.stderr.strip()[:300]}")
        _run(["git", "config", "--global", "--add", "safe.directory", repo_path])
        log.warning("provision: cloned %s -> %s", name, repo_path)

    # 3) bind-mount into the live htdocs/custom + make web-writable (best effort)
    htdocs = target_repo.get("dol_htdocs") or os.environ.get("DOL_HTDOCS", "").strip()
    if htdocs:
        mnt = os.path.join(htdocs, "custom", module)
        is_mounted = os.path.isdir(mnt) and _run(["mountpoint", "-q", mnt]).returncode == 0
        if not is_mounted:
            os.makedirs(mnt, exist_ok=True)
            mr = _run(["mount", "--bind", repo_path, mnt])
            if mr.returncode != 0:
                log.warning("provision: bind-mount failed (%s) — live amb_* won't see the module; "
                            "agent will hand-scaffold into the repo instead.", mr.stderr.strip()[:200])
            else:
                try:
                    with open("/etc/fstab") as f:
                        fstab = f.read()
                    if repo_path not in fstab:
                        with open("/etc/fstab", "a") as f:
                            f.write(f"{repo_path} {mnt} none bind 0 0\n")
                except Exception as e:
                    log.warning("provision: could not update fstab: %s", e)
        # let the web user (amb_*/REST scaffolder) write into the module
        _run(["chgrp", "-R", "www-data", repo_path])
        _run(["bash", "-c", f"chmod -R g+rwX {repo_path!r} && find {repo_path!r} -type d -exec chmod g+s {{}} +"])

    # 4) register in repos.json so every stage resolves it
    _register(target_repo["slug"], target_repo)
    log.warning("provision: registered %s (repo_path=%s, module=%s)", target_repo["slug"], repo_path, module)
    return target_repo
