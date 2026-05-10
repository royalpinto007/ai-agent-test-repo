import json
import os

_REPOS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "repos.json")


def get_repo_config(owner, repo):
    try:
        with open(_REPOS_PATH) as f:
            repos = json.load(f)
    except FileNotFoundError:
        return None
    return repos.get(f"{owner}/{repo}")


def all_repos():
    try:
        with open(_REPOS_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def get_code_repos():
    """Return all repos that are NOT requirements repos."""
    return {k: v for k, v in all_repos().items() if not v.get("requirements_repo")}


def is_requirements_repo(owner, repo):
    cfg = get_repo_config(owner, repo)
    return bool(cfg and cfg.get("requirements_repo"))
