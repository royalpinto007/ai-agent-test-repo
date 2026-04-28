import os
import json

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sessions")


def save_session(session_id, data):
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    existing = load_session(session_id) or {}
    existing.update(data)
    with open(path, "w") as f:
        json.dump(existing, f, indent=2)
    return existing


def load_session(session_id):
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)
