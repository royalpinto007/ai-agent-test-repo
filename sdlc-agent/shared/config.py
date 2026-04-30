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
