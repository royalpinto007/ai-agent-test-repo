# n8n workflow exports

Live snapshots of the SDLC pipeline workflows, exported from n8n via the public
API (`GET /api/v1/workflows/{id}`). These are the **source of truth** — keep them
in sync after editing a workflow in the n8n UI/API.

| File | n8n name | Purpose |
|------|----------|---------|
| `start-pipeline.json` | SDLC - 1. Start Pipeline (New Issue) | BA trigger on `agent-accellier` assignment |
| `approval-gate.json` | SDLC - 2. Approval Gate | approve / revise / redo-dev / reopen + stage chaining |
| `start-acornsafety.json` | SDLC - 1. Start (acornsafety) | acornsafety-specific start variant |
| `approval-acornsafety.json` | SDLC - 2. Approval (acornsafety) | acornsafety-specific approval variant |

**Re-import note:** the public-API `PUT` rejects `settings` keys outside its schema
(e.g. `binaryMode`) — filter `settings` to allowed keys (e.g. `executionOrder`)
before `PUT`, and `POST /workflows/{id}/activate` afterwards (PUT deactivates).

These replace the older single-pipeline `n8n-workflow-1-start.json` /
`n8n-workflow-2-approval.json` (removed; they predated the acornsafety/Thrive split
and the `Comment Dev Result` nested-expression fix).
