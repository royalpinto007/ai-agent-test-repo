# SDLC Agent

An AI-powered software development pipeline built on GitHub Issues, Claude Code CLI, and n8n. Open an issue, assign it to `support-accellier`, and a chain of AI agents handles the full lifecycle — from requirements analysis to deployment — with human approval at every stage.

## How it works

```
GitHub Issue assigned to support-accellier
      ↓ (automatic, milestone: BA Working)
BA Agent        — writes a Business Requirements Document
      ↓ (comment: approve, milestone: SA Working)
SA Agent        — writes a Solution Design Document
      ↓ (comment: approve, milestone: PM Working)
PM Agent        — breaks work into tasks, creates GitHub sub-issues
      ↓ (comment: approve, milestone: DEV Working)
Dev Agent       — writes code, runs tests, pushes branch, opens PR
      ↓ (comment: approve, milestone: Deploy / Complete)
Deploy Agent    — deploys to stage, smoke tests, then deploys to prod
                  auto-merges PR, deletes branch, creates GitHub Release
```

Each agent posts its output as a comment on the issue. You review it, then comment to advance — or give feedback to revise.

## Quick links

- [Deployment guide](DEPLOYMENT.md) — set up on a Linux server
- [Issue guide](ISSUE_GUIDE.md) — how to write issues for best results
- [n8n setup](N8N_SETUP.md) — import and configure the workflows
- [Pipeline reference](PIPELINE_REFERENCE.md) — full pipeline reference
