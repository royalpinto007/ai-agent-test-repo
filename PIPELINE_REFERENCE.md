# SDLC Agent — Reference

An AI-powered software development pipeline that runs entirely through GitHub issues and comments. Assign an issue to `agent-accellier` and a chain of AI agents handles the full lifecycle — with human approval at every stage.

---

## Pipeline overview

The pipeline has three distinct flows based on the GitHub issue type. Set the native `Type` field on the issue to `Bug` or `Feature`, or use a `[Prefix]` in the title for Task mode.

---

### Bug flow

```
Issue assigned (type: Bug)
      ↓  milestone → Bug Analysis Working
BA Agent        — one-pass bug analysis: Clarification, Verification, Cause Determination,
                  Cause Verification, Possible Solution
      ↓  comment: approve  →  milestone → Dev Working
Dev Agent       — writes fix, runs tests, opens PR
      ↓  comment: approve  →  milestone → Deploy / Complete
Deploy Agent    — deploys to STAGE, then PROD
```

| Milestone | When |
|-----------|------|
| Bug Analysis Working | BA agent running |
| Bug Analysis Awaiting Approval | BA complete, waiting for approve |
| Dev Working | Dev agent running |
| Dev Awaiting Approval | Dev complete, waiting for approve |
| Deploy / Complete | Deployed |

---

### Feature flow

The BA agent detects whether the requirement needs code changes or only configuration, and includes `CONFIG_ONLY: true/false` in its output.

**Code-change path (config_only: false):**

```
Issue assigned (type: Feature)
      ↓  milestone → BRD Working
BA Agent        — writes BRD, emits CONFIG_ONLY: false
      ↓  comment: approve  →  milestone → TRD Working
SA Agent        — writes Solution Design Document (TRD + Test Cases)
      ↓  comment: approve  →  milestone → Planning Working
PM Agent        — granular task breakdown, creates GitHub sub-issues
      ↓  comment: approve  →  milestone → Dev Working
Dev Agent       — writes code, runs tests, opens PR
      ↓  comment: approve  →  milestone → Review Working
Review Agent    — code review
      ↓  comment: approve  →  milestone → Test Working
QA Agent        — quality assurance
      ↓  comment: approve  →  milestone → Deploy / Complete
Deploy Agent    — stage then prod
```

**Config-only path (config_only: true):**

```
Issue assigned (type: Feature)
      ↓  milestone → BRD Working
BA Agent        — writes BRD, emits CONFIG_ONLY: true
      ↓  comment: approve  →  milestone → TRD Working
SA Agent        — writes config steps
      ↓  comment: approve  →  milestone → Planning Working
PM Agent        — posts config instructions, marks terminal → milestone: Config Complete → DONE
```

| Milestone | When |
|-----------|------|
| BRD Working | BA agent running |
| BRD Awaiting Approval | BA complete |
| TRD Working | SA agent running |
| TRD Awaiting Approval | SA complete |
| Planning Working | PM agent running |
| Planning Awaiting Approval | PM complete (code-change path) |
| Config Complete | PM complete (config-only path) |
| Dev Working | Dev agent running |
| Dev Awaiting Approval | Dev complete |
| Review Working | Review agent running |
| Review Awaiting Approval | Review complete |
| Test Working | QA agent running |
| Test Awaiting Approval | QA complete |
| Deploy / Complete | Deployed |

---

### Task flow

For targeted single-agent runs, prefix the issue title with `[AgentName]`. The issue type field is ignored — prefix detection takes priority.

| Title prefix | Agents run |
|--------------|-----------|
| `[BA]` | BA only → done |
| `[SA]` | SA only → done |
| `[PM]` | PM only → done |
| `[Dev]` | Dev → Review → QA → done (no Deploy) |
| `[Review]` | Review → QA → done |
| `[QA]` | QA only → done |
| `[Deploy]` | Deploy only → done |

Milestones: `Task: Assigned` on start, `Task: Complete` when done.

---

At every stage you can:
- `approve` — advance to the next agent
- `revise: <feedback>` — re-run the current agent with your notes

---

## Trigger

The pipeline starts **only** when an issue is assigned to `agent-accellier`.

- Issue opened without that assignee → nothing happens
- Issue opened with `agent-accellier` assigned → pipeline starts immediately
- Existing issue later assigned to `agent-accellier` → pipeline starts from BA

This lets you create draft issues without triggering the pipeline prematurely.

---

## Milestones

The pipeline automatically creates and updates GitHub milestones as it progresses:

| Milestone | When it's set |
|-----------|--------------|
| BA Working | Issue assigned to agent-accellier, BA agent running |
| BA Awaiting Approval | BA agent complete, waiting for `approve` |
| SA Working | SA agent running |
| SA Awaiting Approval | SA agent complete, waiting for `approve` |
| PM Working | PM agent running |
| PM Awaiting Approval | PM agent complete, waiting for `approve` |
| DEV Working | Dev agent running |
| DEV Awaiting Approval | Dev agent complete, waiting for `approve` |
| Deploy / Complete | Deploy complete |

Only one milestone is active at a time. The old one is replaced when the pipeline advances.

---

## Comment commands

Post any of these as a comment on the issue:

| Comment | What it does |
|---------|-------------|
| `approve` | Advance to the next stage |
| `revise: <feedback>` | Re-run the current agent with your feedback |
| `redo-dev: <instructions>` | Re-run only the Dev agent with extra instructions |
| `reopen: <reason>` | Reset the entire pipeline back to BA |
| `assign: @username` | Assign all PM-created sub-issues to a user |
| `status` | Post a summary of current pipeline state |

### Using `revise:`

Works at every stage. Be specific — the agent re-runs with your note as extra context:

```
revise: scope is too broad, focus only on the API layer
revise: split task 3 into two issues — schema migration and API handler separately
revise: acceptance criteria for task 1 are missing the error case
```

---

## Multi-repo support (Thrive-ERP setup)

The pipeline supports a hub-and-spoke model where:
- Issues are created in a single **requirements repo** (`Thrive-ERP/thrive-requirements`)
- Code changes land in one or more **code repos** (`Thrive-ERP/*`)

The PM agent reads the issue, determines which code repo(s) are affected, and the Dev agent works in the correct repo automatically. Cross-repo issues are opened as sub-issues in the affected repos.

All 30 Thrive-ERP code repos are cloned to `/opt/repos/` on the server and registered with the API.

---

## Project structure

```
sdlc-agent/
├── agents/
│   ├── ba/              # Business Analyst — BRD from issue + codebase analysis
│   ├── sa/              # Solution Architect — SDD with components and risks
│   ├── pm/              # Project Manager — task breakdown, GitHub sub-issues
│   ├── dev/             # Developer — code, tests, PR (3 retry attempts)
│   └── deploy/          # Deploy — stage/prod deploy, auto-merge, GitHub Release
├── shared/
│   ├── claude.py        # Claude Code CLI wrapper (claude -p)
│   ├── config.py        # repos.json loader, requirements_repo detection
│   ├── session.py       # per-issue session persistence
│   └── utils.py         # git, GitHub API, milestone, file tree helpers
├── sessions/            # per-issue JSON state (gitignored)
├── repos.json           # registered repos
├── sdlc_api.py          # Flask API (port 5001)
├── setup.sh             # one-shot Ubuntu server setup
├── scripts/
│   └── setup-thrive.sh  # clone + register all Thrive-ERP repos
├── n8n-workflow-1-start.json      # webhook → BA agent
└── n8n-workflow-2-approval.json   # comment commands → agents
```

---

## API endpoints

The Flask API runs on port 5001.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/repos` | List all registered repos |
| POST | `/repos` | Register a repo |
| GET | `/session/<id>` | Inspect a pipeline session |
| POST | `/ba-agent` | Run BA agent |
| POST | `/sa-agent` | Run SA agent |
| POST | `/pm-agent` | Run PM agent |
| POST | `/dev-agent` | Run Dev agent |
| POST | `/deploy-agent` | Run Deploy agent (`env=stage` or `env=prod`) |
| POST | `/set-milestone` | Set GitHub issue milestone by title |
| POST | `/reopen` | Reset pipeline to BA |
| POST | `/assign` | Assign sub-issues to a user |
| GET | `/metrics` | Pipeline metrics (sessions, retry rates) |
| GET | `/status` | Current pipeline status for a session |

**Session ID format:** `{owner}-{repo}-{issue_number}`
Example: `Thrive-ERP-thrive-requirements-17`

```bash
# Inspect any session
curl http://localhost:5001/session/Thrive-ERP-thrive-requirements-17

# Manually trigger BA agent
curl -X POST http://localhost:5001/ba-agent \
  -H "Content-Type: application/json" \
  -d '{"owner":"Thrive-ERP","repo":"thrive-requirements","issue_number":17,"requirement":"..."}'
```

---

## repos.json schema

```json
{
  "owner/repo": {
    "repo_path": "/opt/repos/repo-name",
    "test_command": ["npm", "test"],
    "main_branch": "main",
    "requirements_repo": false,
    "deploy": {
      "stage": {
        "command": ["./scripts/deploy.sh", "stage"],
        "smoke_test": ["curl", "-f", "https://staging.example.com/health"]
      },
      "prod": {
        "command": ["./scripts/deploy.sh", "prod"],
        "smoke_test": ["curl", "-f", "https://example.com/health"]
      }
    }
  }
}
```

- `requirements_repo: true` — marks this as an issue hub (e.g. thrive-requirements). The PM agent builds a combined file tree from all code repos.
- `deploy` is optional. If omitted, the deploy agent skips the deploy command but still auto-merges the PR.

**Supported test commands:**

| Stack | test_command |
|-------|-------------|
| Node.js | `["npm", "test"]` |
| Python pytest | `["pytest"]` |
| Python unittest | `["python", "-m", "unittest"]` |
| Go | `["go", "test", "./..."]` |
| Java Maven | `["mvn", "test"]` |
| Ruby | `["bundle", "exec", "rspec"]` |

---

## Troubleshooting

**Pipeline doesn't start when I assign the issue**
- Check the webhook delivered: repo → Settings → Webhooks → Recent Deliveries
- Check n8n workflow 1 is active (green toggle)
- Confirm the assignee username is exactly `agent-accellier`
- Check API: `curl http://localhost:5001/repos`

**BA agent returns 500**
- Check API logs: `journalctl -u sdlc-api -n 50`
- Test Claude CLI: `claude -p "say hello"`
- Test manually: `curl -X POST http://localhost:5001/ba-agent -H "Content-Type: application/json" -d '{"owner":"...","repo":"...","issue_number":1,"requirement":"test"}'`

**Milestone not updating**
- Check `GITHUB_TOKEN` in `/etc/sdlc-agent/env` has `repo` scope
- Test: `curl -X POST http://localhost:5001/set-milestone -H "Content-Type: application/json" -d '{"owner":"Thrive-ERP","repo":"thrive-requirements","issue_number":1,"milestone_title":"BA Working"}'`

**Dev agent tests fail**
- Check `test_command` in `repos.json` matches how tests run in that repo
- Ensure local clone has dependencies installed (`npm install` / `pip install -r requirements.txt`)

**PR creation fails**
- `GITHUB_TOKEN` needs `repo` scope with write access to the target repo
- Retry without re-running dev: `curl -X POST http://localhost:5001/create-pr -H "Content-Type: application/json" -d '{"session_id":"owner-repo-42"}'`

**Sessions directory fills up**
- Safe to delete: `find /opt/sdlc-agent/sdlc-agent/sessions -name "*.json" -mtime +30 -delete`
- A cron is added by `setup.sh` to do this nightly automatically
