# SDLC Agent

An AI-powered software development pipeline that runs entirely through GitHub issues and comments. Open an issue, and a chain of AI agents handles the full lifecycle — from requirements to QA sign-off — with human approval at every stage.

## How it works

```
New GitHub Issue
      ↓ (automatic)
BA Agent       — writes a Business Requirements Document
      ↓ (comment: approve)
SA Agent       — writes a Solution Design Document
      ↓ (comment: approve)
PM Agent       — breaks work into tasks, creates GitHub issues per task
      ↓ (comment: approve)
Dev Agent      — writes code, runs tests, pushes branch, opens PR
      ↓ (comment: approve)
Review Agent   — peer code review
      ↓ (comment: approve)
QA Agent       — final sign-off with STAGE and PROD deployment gates
```

Each agent posts its output as a comment on the issue. You review it, then comment to advance — or give feedback to revise.

---

## Prerequisites

- Python 3.10+
- [Claude Code CLI](https://claude.ai/code) installed and authenticated (`claude` available in PATH)
- [n8n](https://n8n.io) running locally (default port 5678)
- [ngrok](https://ngrok.com) or any tunnel to expose n8n to GitHub webhooks
- A GitHub Personal Access Token with `repo` scope

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-org/your-repo
cd your-repo/sdlc-agent

python3 -m venv ../venv
source ../venv/bin/activate
pip install -r requirements.txt
```

### 2. Register your repo

Edit `repos.json` to add your repo:

```json
{
  "your-org/your-repo": {
    "repo_path": "/absolute/path/to/cloned/repo",
    "test_command": ["npm", "test"],
    "main_branch": "main"
  }
}
```

Or do it via the API after starting (see step 4):

```bash
curl -X POST http://localhost:5001/repos \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "your-org",
    "repo": "your-repo",
    "repo_path": "/absolute/path/to/cloned/repo",
    "test_command": ["npm", "test"],
    "main_branch": "main"
  }'
```

**Supported test commands by stack:**

| Stack | test_command |
|-------|-------------|
| Node.js | `["npm", "test"]` |
| Python pytest | `["pytest"]` |
| Python unittest | `["python", "-m", "unittest"]` |
| Go | `["go", "test", "./..."]` |
| Java Maven | `["mvn", "test"]` |
| Ruby | `["bundle", "exec", "rspec"]` |

### 3. Start the API

```bash
export GITHUB_TOKEN=your_personal_access_token
./start.sh
```

The API runs on `http://localhost:5001`. You should see your registered repos printed on startup.

### 4. Set up n8n

**Import the workflows:**

In n8n: **Workflows → Import from File**, import both files in order:
1. `n8n-workflow-1-start.json` — triggers on new issues, starts the BA agent
2. `n8n-workflow-2-approval.json` — handles all comment commands

**Configure GitHub credentials:**

In n8n: **Settings → Credentials → Add → GitHub API**
- Add your GitHub Personal Access Token
- Apply this credential to every GitHub node in both workflows (click each node → select credential)

**Activate both workflows** (toggle the switch in the top right of each workflow).

### 5. Set up GitHub webhook

Start ngrok to expose n8n:

```bash
ngrok http 5678
```

In your GitHub repo: **Settings → Webhooks → Add webhook**

| Field | Value |
|-------|-------|
| Payload URL | `https://your-ngrok-url/webhook/sdlc-start` |
| Content type | `application/json` |
| Events | Issues, Issue comments |

> For multiple repos: add the same webhook URL to each repo. The pipeline reads `repository.owner.login` and `repository.name` from the payload automatically.

---

## Adding a second (or third) repo

No n8n changes needed. Just:

1. Clone the repo locally
2. Register it:

```bash
curl -X POST http://localhost:5001/repos \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "other-org",
    "repo": "other-repo",
    "repo_path": "/path/to/other-repo",
    "test_command": ["pytest"],
    "main_branch": "main"
  }'
```

3. Add the GitHub webhook to that repo (same ngrok URL)

Done. The same API and n8n instance handles all repos.

---

## Comment commands

Post any of these as a comment on a GitHub issue to control the pipeline:

| Comment | What it does |
|---------|-------------|
| `approve` | Advance to the next stage |
| `revise: <feedback>` | Re-run the current stage's agent with your feedback |
| `redo-dev: <instructions>` | Re-run the Dev agent with extra instructions |
| `reopen: <reason>` | Reset pipeline back to BA with a reason |
| `skip-qa` | Mark QA as approved without running the agent |
| `assign: @username` | Assign all PM-created GitHub issues to a user |
| `status` | Post a summary of the current pipeline state |

**`revise:` works at every stage.** Examples:

```
revise: the scope is too broad, focus only on the API layer
revise: split task 2 into two separate issues
revise: the test coverage section misses the error cases
```

---

## API endpoints

The API runs at `http://localhost:5001`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/repos` | List registered repos |
| POST | `/repos` | Register a new repo |
| GET | `/session/<id>` | Inspect a pipeline session |
| POST | `/ba-agent` | Run BA agent |
| POST | `/sa-agent` | Run SA agent |
| POST | `/pm-agent` | Run PM agent |
| POST | `/dev-agent` | Run Dev agent |
| POST | `/review-agent` | Run Review agent |
| POST | `/qa-agent` | Run QA agent |
| POST | `/create-pr` | Create PR for existing branch |
| POST | `/reopen` | Reset pipeline to BA |
| POST | `/skip-qa` | Manually approve QA |
| POST | `/assign` | Assign issues to a user |

**Session ID format:** `{owner}-{repo}-{issue_number}`
Example: `royalpinto007-ai-agent-test-repo-42`

Inspect any session:
```bash
curl http://localhost:5001/session/royalpinto007-ai-agent-test-repo-42
```

---

## Project structure

```
sdlc-agent/
├── agents/
│   ├── ba/          # Business Analyst — BRD
│   ├── sa/          # Solution Architect — SDD
│   ├── pm/          # Project Manager — task breakdown + GitHub issues
│   ├── dev/         # Developer — code, tests, PR
│   ├── review/      # Peer Reviewer — code review
│   └── qa/          # QA Engineer — sign-off + deployment gates
├── shared/
│   ├── claude.py    # Claude CLI wrapper
│   ├── config.py    # repos.json loader
│   ├── session.py   # session persistence
│   └── utils.py     # git, file tree, GitHub API helpers
├── sessions/        # per-issue session state (gitignored)
├── repos.json       # registered repos
├── sdlc_api.py      # Flask API
├── start.sh         # startup script
├── n8n-workflow-1-start.json
└── n8n-workflow-2-approval.json
```

---

## Troubleshooting

**Pipeline doesn't start when I open an issue**
- Check ngrok is running and the webhook URL matches `https://your-ngrok-url/webhook/sdlc-start`
- Check n8n workflow 1 is active (green toggle)
- Check the API is running: `curl http://localhost:5001/repos`

**"Session not found" comment on the issue**
- The approval webhook fired before BA completed, or the session was never created
- Check the API logs for errors from the BA agent run

**PR creation fails**
- Make sure `GITHUB_TOKEN` is exported before running `start.sh`
- Token needs `repo` scope
- Run `curl -X POST http://localhost:5001/create-pr -H "Content-Type: application/json" -d '{"session_id": "owner-repo-42"}'` to retry without re-running dev

**Tests fail on dev agent**
- Check `test_command` in `repos.json` matches how tests are run in that repo
- Check the local clone has all dependencies installed (e.g. `npm install` or `pip install -r requirements.txt`)

**Double comments on the issue**
- In n8n, make sure there are no error-path wires connected to the comment nodes — delete any red error connections from agent nodes
