import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uuid
from flask import Flask, request, jsonify

from shared.session import load_session
import agents.ba.agent as ba
import agents.pm.agent as pm
import agents.dev.agent as dev
import agents.review.agent as review
import agents.qa.agent as qa

app = Flask(__name__)

DEFAULT_REPO_PATH = os.environ.get(
    "REPO_PATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _sid(data):
    return data.get("session_id") or str(uuid.uuid4())


def _repo(data, session):
    return data.get("repo_path") or session.get("repo_path") or DEFAULT_REPO_PATH


@app.route("/ba-agent", methods=["POST"])
def ba_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    try:
        result = ba.run(
            session_id=sid,
            requirement=data.get("requirement") or session.get("requirement", ""),
            repo_path=_repo(data, session),
            clarification_answers=data.get("clarification_answers"),
        )
        return jsonify({"status": "success", "stage": "ba", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/pm-agent", methods=["POST"])
def pm_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    try:
        result = pm.run(
            session_id=sid,
            repo_path=_repo(data, session),
            brd=data.get("brd"),
        )
        return jsonify({"status": "success", "stage": "pm", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/dev-agent", methods=["POST"])
def dev_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    try:
        result = dev.run(
            session_id=sid,
            issue_title=data.get("issue_title", ""),
            issue_description=data.get("issue_description", ""),
            repo_path=_repo(data, session),
            branch_name=data.get("branch_name"),
        )
        return jsonify({"status": "success", "stage": "dev", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/review-agent", methods=["POST"])
def review_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    try:
        result = review.run(
            session_id=sid,
            repo_path=_repo(data, session),
            branch_name=data.get("branch"),
            issue_title=data.get("issue_title"),
            impact_analysis=data.get("impact_analysis"),
            affected_files=data.get("affected_files"),
        )
        return jsonify({"status": "success", "stage": "review", "session_id": sid, "awaiting_approval": True, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/qa-agent", methods=["POST"])
def qa_agent():
    data = request.json or {}
    sid = _sid(data)
    session = load_session(sid) or {}
    try:
        result = qa.run(
            session_id=sid,
            issue_title=data.get("issue_title"),
            test_output=data.get("test_output"),
            review_verdict=data.get("verdict"),
            review_dimensions=data.get("dimensions"),
            impact_analysis=data.get("impact_analysis"),
        )
        return jsonify({"status": "success", "stage": "qa", "session_id": sid, **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/session/<session_id>", methods=["GET"])
def get_session(session_id):
    session = load_session(session_id)
    if not session:
        return jsonify({"status": "error", "message": "Session not found"}), 404
    return jsonify({"status": "success", "session": session})


if __name__ == "__main__":
    app.run(port=5001)
