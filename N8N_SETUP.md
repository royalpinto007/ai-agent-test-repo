# n8n SDLC Pipeline Setup

## Step 1 — Set n8n Environment Variables

In n8n UI: **Settings → Variables → Add Variable**

| Name | Value |
|------|-------|
| `GITHUB_OWNER` | `royalpinto007` |
| `GITHUB_REPO` | `ai-agent-test-repo` |
| `SDLC_API_URL` | `http://localhost:5001` |
| `REPO_PATH` | `/home/royalpinto007/Open-Source/ai-agent-test-repo` |

## Step 2 — Import Workflows

In n8n UI: **Workflows → Import from File**

Import both files in order:
1. `n8n-workflow-1-start.json` — triggers on new GitHub issues, runs BA agent
2. `n8n-workflow-2-approval.json` — triggers on `approve` comments, advances the pipeline

## Step 3 — Configure GitHub Credentials

Both workflows use the **GitHub** node. Make sure your GitHub credential is set in n8n:
- **Settings → Credentials → GitHub API**
- Use a Personal Access Token with `repo` scope

## Step 4 — Set Up Webhooks (ngrok)

The GitHub Trigger nodes need a public URL. Start ngrok:

```bash
ngrok http 5678
```

In GitHub repo settings → Webhooks, set the Payload URL to your ngrok URL.
Alternatively, activate the workflows in n8n and copy the webhook URLs from each trigger node.

## Step 5 — Start the SDLC API

```bash
cd sdlc-agent
./start.sh
```

---

## How It Works

### Starting the pipeline
1. Open a new GitHub issue — the BA agent runs automatically and posts the BRD as a comment.

### Advancing between stages
Comment `approve` on the issue at any time. The pipeline reads the current stage from session and automatically runs the next agent:

| Current stage | `approve` runs |
|---------------|----------------|
| `ba` | PM Agent |
| `pm` | Dev Agent |
| `dev` | Review Agent |
| `review` | QA Agent |

### Session ID
Each issue gets session ID `sdlc-{issue_number}` (e.g. `sdlc-42`).
You can inspect any session at: `http://localhost:5001/session/sdlc-{issue_number}`

### Flow summary
```
New Issue
   ↓ (automatic)
BA Agent → posts BRD comment
   ↓ (comment: approve)
SA Agent → posts Solution Design Document
   ↓ (comment: revise: <feedback>  ← repeat until satisfied)
SA Agent (revised) → posts updated SDD
   ↓ (comment: approve)
PM Agent → posts task breakdown comment
   ↓ (comment: approve)
Dev Agent → writes code, runs tests, pushes branch → posts result comment
   ↓ (comment: approve)
Review Agent → reviews diff → posts review comment
   ↓ (comment: approve)
QA Agent → final sign-off with STAGE/PROD gates → posts verdict comment
```

### Comment commands
| Comment | Effect |
|---------|--------|
| `approve` | Advance to the next stage |
| `revise: <your feedback>` | Re-run the SA agent with your feedback (only valid during SA stage) |
