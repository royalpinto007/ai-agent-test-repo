# How to Write a Good Issue for the SDLC Agent

The pipeline starts the moment you open a GitHub issue. Everything — the BRD, the architecture, the task breakdown, the code — flows from what you write here. A vague issue produces vague output. A clear issue produces a PR you can merge.

---

## Before you open an issue

Make sure the pipeline is running:

1. The SDLC API is up (`curl http://localhost:5001/repos` returns your repos)
2. n8n is running and both workflows are active (green toggle)
3. ngrok (or your tunnel) is forwarding to n8n on port 5678
4. The GitHub webhook is pointing to your tunnel URL

If any of these are off, the issue will open but nothing will happen.

---

## Issue structure

### Title

Write the title as a short, specific action. The Dev agent uses it as the branch name and commit message, so make it descriptive enough to be meaningful in a git log.

**Good:**
```
Add delete command to task CLI
Fix pagination bug on /api/posts endpoint
Refactor auth middleware to use JWT instead of sessions
```

**Bad:**
```
Bug fix
Improvements
Update stuff
```

### Description

The description is what the BA agent reads first. Give it enough context to write a real requirements document without having to guess.

A solid description covers:

**What** — what are you trying to build or fix?
**Why** — what problem does this solve, or what value does it add?
**Who** — who uses this? (user, admin, internal service, etc.)
**Scope** — what's explicitly in and out of scope?
**Constraints** — any technical constraints, deadlines, or dependencies?

---

## Templates

### New feature

```
## What
[One sentence on what the feature does]

## Why
[Why this is needed — user pain point, business requirement, or missing capability]

## Who uses it
[User type — e.g. end user, admin, another service]

## Expected behaviour
- [Bullet each expected behaviour or flow]
- [Include edge cases you already know about]

## Out of scope
- [Anything you explicitly don't want the agent to build]

## Additional context
[Any related issues, PRs, existing code references, or design decisions]
```

### Bug fix

```
## What's broken
[What is happening that shouldn't be]

## Steps to reproduce
1. [Step one]
2. [Step two]
3. [What you see vs what you expect]

## Expected behaviour
[What should happen instead]

## Environment / context
[Relevant version, stack, config — no secrets or env vars]

## Root cause (if known)
[Your best guess, or leave blank]
```

### Refactor / tech debt

```
## What to refactor
[Which module, file, or pattern needs changing]

## Why now
[What's the trigger — performance issue, upcoming feature, maintenance burden]

## What good looks like
[The target state — what should be true after the refactor]

## Constraints
[What must not change — API contracts, behaviour, test coverage requirements]
```

---

## What makes a bad issue

| Problem | Why it matters |
|---------|---------------|
| One-line description | BA agent has nothing to work with, produces a generic BRD |
| Missing "why" | PM agent can't prioritise correctly, may over- or under-scope |
| Ambiguous scope | Dev agent guesses, often too broad or too narrow |
| Mixing multiple unrelated features | Pipeline handles one thing at a time — split it |
| Referencing private context ("as discussed") | Agents can't read Slack or meeting notes |

---

## Cross-repo issues

If your change touches more than one registered repo, say so in the description. The PM agent will detect it and automatically open issues in the other repos.

```
## Cross-repo impact
This change also requires updating the `dreamchain-cli` repo:
- The CLI needs a new --format flag to consume the new API response shape
```

You don't need to manually open issues in the other repo — the PM agent handles it.

---

## After you open the issue

The pipeline runs automatically. You'll see a comment from the BA agent within a minute or two.

From there, you control it entirely through comments:

| Comment | What it does |
|---------|-------------|
| `approve` | Advance to the next stage |
| `revise: <feedback>` | Re-run the current stage with your feedback |
| `redo-dev: <instructions>` | Re-run only the Dev agent with extra instructions |
| `reopen: <reason>` | Reset the whole pipeline back to BA |
| `skip-qa` | Mark QA approved without running the agent |
| `assign: @username` | Assign all PM-created sub-issues to someone |

### Giving feedback with `revise:`

Use `revise:` any time the agent output isn't right. Be specific — the agent will re-run with your note as extra context.

```
revise: scope is too broad, focus only on the API layer, skip the frontend tasks
revise: split task 3 into two issues — schema migration and the API handler separately
revise: the acceptance criteria for task 1 are missing the error case when the token is expired
```

---

## Example: a well-written issue

**Title:**
```
Add rate limiting to the public API endpoints
```

**Description:**
```
## What
Add per-IP rate limiting to all public-facing API routes (/api/posts, /api/users).

## Why
We're seeing abuse from scrapers hitting the endpoints in tight loops. No rate limiting is in place today.

## Expected behaviour
- Requests beyond 100/minute per IP get a 429 response with a Retry-After header
- Authenticated requests have a higher limit (500/minute)
- Limits are configurable without a code deploy

## Out of scope
- Rate limiting on internal/admin routes
- Per-user limits (IP-based is enough for now)
- A dashboard for monitoring rate limit hits

## Constraints
- Must work with the existing Express middleware stack
- Redis is already in the stack and can be used for the counter store
```

This gives the BA agent everything it needs: the what, why, behaviour, explicit out-of-scope, and a constraint. The PM agent can scope tasks cleanly. The Dev agent knows exactly what to build.

---

## Checklist before submitting

- [ ] Title is a specific action, not a category
- [ ] Description explains what, why, and who
- [ ] Scope is explicit — what's in, what's out
- [ ] No secrets, tokens, or env variable values in the description
- [ ] If cross-repo, the affected repos are named
- [ ] One feature or bug per issue (not a bundle)
