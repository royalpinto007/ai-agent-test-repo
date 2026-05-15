# How to Write Issues for the SDLC Agent

The pipeline starts when you assign `agent-accellier` to an issue on `Thrive-ERP/thrive-requirements`. Everything — the BRD, the architecture, the task breakdown, the code — flows from what you write. A vague issue produces vague output. A clear issue produces a PR you can merge.

---

## Issue types

The pipeline runs different flows depending on the **GitHub issue type** (the native `Type` field on the issue). Set it before assigning `agent-accellier`.

| Issue type | When to use | Flow |
|------------|-------------|------|
| **Bug** | Something is broken and needs a root-cause fix | BA (analysis only) → Dev → Deploy |
| **Feature** | New functionality or enhancement | BA → SA → PM → Dev → Review → QA → Deploy (or config-only shortcut) |
| **Task** (via title prefix) | Direct single-agent invocation | Detected from `[Prefix]` in the title — see Task section below |

### When to use Bug vs Feature

- **Bug**: you know something is broken and want a root-cause analysis + fix. The BA agent produces a structured bug report (Clarification, Verification, Cause Determination, Cause Verification, Possible Solution) in one pass. No architecture phase — goes straight to Dev.
- **Feature**: anything additive. New screens, new APIs, new integrations, refactors that change behaviour. Goes through the full BA → SA → PM planning cycle before any code is written.

### Config-only detection (Feature type)

When the issue type is Feature, the BA agent automatically detects whether the requirement can be satisfied through configuration alone (no code changes). If so, it sets `CONFIG_ONLY: true` in its output and the pipeline skips Dev/Review/QA, routing to PM which posts config instructions and terminates.

The BA comment on the issue will indicate: **Config only: ✅ Yes** or **❌ No**.

### Task prefix usage

For targeted single-agent runs, prefix the issue title with `[AgentName]`. The issue type field is ignored when a prefix is detected.

| Title prefix | Agents run |
|--------------|-----------|
| `[BA]` | BA analysis only |
| `[SA]` | SA design only |
| `[PM]` | PM planning only |
| `[Dev]` | Dev → Review → QA (no Deploy) |
| `[Review]` | Review → QA |
| `[QA]` | QA only |
| `[Deploy]` | Deploy only |

**Examples:**
```
[Dev] Fix checkout calculation rounding error
[QA] Regression test for order confirmation flow
[SA] Design caching layer for product catalogue API
```

Tasks use milestone `Task: Assigned` → `Task: Complete`. No approval gates are required — all agents in the chain run automatically.

---

## Trigger

The pipeline does **not** start when an issue is created. It starts when `agent-accellier` is **assigned** to the issue.

This means you can:
- Draft issues without triggering the pipeline
- Review and edit the description before assigning
- Assign later when you're ready for the agents to start

Once `agent-accellier` is assigned, the BA agent starts immediately and the first milestone (`BA Working`) is set.

---

## Issue structure

### Title

Write the title as a short, specific action. The Dev agent uses it as the branch name and commit message prefix.

**Good:**
```
Add FedEx shipping rate integration to delivery module
Fix pagination bug on /api/orders endpoint
Refactor auth middleware to use JWT
```

**Bad:**
```
Bug fix
Improvements
Update stuff
```

### Body

The body is what the BA agent reads first. Give it enough to write a real requirements document.

A solid description covers:

- **What** — what are you building or fixing?
- **Why** — what problem does this solve?
- **Who** — who uses this? (user, admin, warehouse operator, etc.)
- **Scope** — what's explicitly in and out of scope?
- **Constraints** — technical constraints, existing systems to integrate with

---

## Templates

### New feature

```
## What
[One sentence on what the feature does]

## Why
[Why this is needed — user pain point, business requirement, or missing capability]

## Who uses it
[User type — end user, admin, warehouse operator, etc.]

## Expected behaviour
- [Bullet each expected behaviour or flow]
- [Include edge cases you already know about]

## Out of scope
- [Anything you explicitly don't want the agent to build]

## Additional context
[Related issues, existing code references, third-party APIs involved]
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
[Relevant version, stack, config — no secrets or tokens]

## Root cause (if known)
[Your best guess, or leave blank]
```

### Refactor / tech debt

```
## What to refactor
[Which module, file, or pattern needs changing]

## Why now
[Performance issue, upcoming feature, maintenance burden]

## What good looks like
[The target state after the refactor]

## Constraints
[What must not change — API contracts, behaviour, test coverage]
```

---

## What makes a bad issue

| Problem | Why it matters |
|---------|---------------|
| One-line description | BA agent has nothing to work with, produces a generic BRD |
| Missing "why" | PM agent can't prioritise correctly, may over- or under-scope |
| Ambiguous scope | Dev agent guesses — often too broad or too narrow |
| Multiple unrelated features | Split it. One pipeline run = one coherent change. |
| "As discussed" references | Agents can't read Slack or meeting notes |
| Secrets or tokens in the body | Never put credentials in issue descriptions |

---

## After you assign the issue

The pipeline runs automatically. You'll see the first milestone change to `BA Working`, then a BA agent comment within 1-2 minutes.

From there, control the pipeline through comments:

| Comment | What it does |
|---------|-------------|
| `approve` | Advance to the next stage |
| `revise: <feedback>` | Re-run the current agent with your feedback |
| `redo-dev: <instructions>` | Re-run only the Dev agent |
| `reopen: <reason>` | Reset the entire pipeline back to BA |
| `assign: @username` | Assign all PM-created sub-issues to someone |
| `status` | Show current pipeline state |

### Giving feedback with `revise:`

Use `revise:` any time the agent output isn't right. Be specific:

```
revise: scope is too broad — focus only on the API layer, skip the frontend
revise: split task 3 into two issues: schema migration and the API handler separately
revise: the acceptance criteria for task 1 are missing the error case when the token expires
```

---

## Milestone progression

As the pipeline advances, the GitHub milestone on the issue updates automatically:

```
BA Working → BA Awaiting Approval
                ↓ approve
SA Working → SA Awaiting Approval
                ↓ approve
PM Working → PM Awaiting Approval
                ↓ approve
DEV Working → DEV Awaiting Approval
                ↓ approve
Deploy / Complete
```

Only one milestone is active at a time. You can filter issues by milestone in the GitHub UI to see where each one is in the pipeline.

---

## Cross-repo changes

If a change touches more than one Thrive-ERP repo, say so in the description. The PM agent detects it and automatically opens sub-issues in the other repos.

```
## Cross-repo impact
This change also requires updating thrive-pos:
- The POS checkout screen needs a new delivery option selector
- The carrier rate API response shape changes from this work
```

You don't need to open issues in the other repo manually — the PM agent handles it.

---

## Example: a well-written issue

**Title:**
```
Add FedEx real-time shipping rates to the delivery module
```

**Body:**
```
## What
Integrate FedEx REST API into the existing delivery module so users can get
live shipping rates at checkout instead of manual price rules.

## Why
Currently all delivery costs are entered manually or use fixed rules.
Sales reps have to look up FedEx rates separately and type them in,
which causes errors and slows down order confirmation.

## Who uses it
Warehouse operators creating shipments, and sales reps confirming orders
with customers over the phone.

## Expected behaviour
- At checkout, the delivery wizard shows live FedEx rates for the order
  (Ground, 2Day, Overnight) with estimated transit days
- Operator selects a rate and it's added to the order
- On shipment validation, a FedEx label is generated and stored on the picking
- Tracking number appears on the picking and links to FedEx tracking page
- If FedEx API returns an error, show the error message — don't silently fail

## Out of scope
- UPS or DHL integration (follow-on)
- Label printing infrastructure (assume PDF download for now)
- Tracking status webhooks / polling

## Constraints
- Target the FedEx REST API (2022+), not the deprecated SOAP API
- API credentials must be configurable per carrier record, not hardcoded
- Must work with the existing delivery.carrier model and wizard flow
```

---

## Checklist before assigning

- [ ] Title is a specific action, not a category
- [ ] Body explains what, why, and who
- [ ] Scope is explicit — what's in, what's out
- [ ] No secrets, tokens, or credentials in the body
- [ ] If cross-repo, the affected repos are named
- [ ] One feature or bug per issue (not a bundle)
