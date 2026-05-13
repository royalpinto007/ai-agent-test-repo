# Deploying the SDLC Agent

This guide covers running the full pipeline on an Ubuntu server or LXC container. Once set up, GitHub webhooks drive everything automatically.

---

## Architecture

```
GitHub (issues + webhooks)
        │
        ▼
  agent-workflow.accellier.net   ← n8n (webhook router + approval handler)
        │
        ▼  HTTP calls to port 5001
  10.68.103.135 (LXC container)
  ├── sdlc-api (Flask, port 5001)   ← runs agents
  ├── /opt/repos/*                  ← 30 Thrive-ERP repos cloned here
  └── Claude Code CLI               ← LLM engine
```

n8n runs at `agent-workflow.accellier.net` and calls the Flask API at `http://10.68.103.135:5001`.

---

## Quick setup (new server)

Run the one-shot setup script on a fresh Ubuntu 24.04 server or LXC container:

```bash
curl -fsSL https://raw.githubusercontent.com/royalpinto007/ai-agent-test-repo/main/sdlc-agent/setup.sh -o setup.sh
bash setup.sh
```

It will prompt for:
- GitHub Personal Access Token (`repo` scope)
- Server IP or domain
- Webhook secret (auto-generated if left blank)

The script installs Node.js 20, Python, Claude Code CLI, n8n, nginx, and creates systemd services for the API and n8n.

After it completes, follow the printed next steps.

---

## Server requirements

| Resource | Minimum |
|----------|---------|
| OS | Ubuntu 22.04+ or Debian 12 |
| CPU | 2 vCPU |
| RAM | 4 GB (8 GB recommended) |
| Disk | 50 GB (repos take space) |
| Network | Public IP or accessible from n8n |

---

## Post-install steps

### 1. Authenticate Claude Code CLI

```bash
claude
```

Open the URL it prints, log in with your Anthropic account, paste the code back. Verify:

```bash
claude -p "say hello"
```

### 2. Clone and register Thrive-ERP repos

```bash
GITHUB_TOKEN=<token-with-Thrive-ERP-read-access> \
  bash /opt/sdlc-agent/sdlc-agent/scripts/setup-thrive.sh
```

This clones all 30 Thrive-ERP repos to `/opt/repos/` and registers them with the API. Takes ~5 minutes.

Verify:
```bash
curl -s http://localhost:5001/repos | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['repos']), 'repos registered')"
```

### 3. Configure environment

The env file at `/etc/sdlc-agent/env` must contain:

```
GITHUB_TOKEN=your_token_here
WEBHOOK_SECRET=your_webhook_secret_here
```

After editing:
```bash
systemctl restart sdlc-api
```

### 4. Import n8n workflows

Open n8n at `https://agent-workflow.accellier.net`.

1. Delete any existing SDLC workflows
2. Import workflow 1:
   ```
   https://raw.githubusercontent.com/royalpinto007/ai-agent-test-repo/main/sdlc-agent/n8n-workflow-1-start.json
   ```
3. Import workflow 2:
   ```
   https://raw.githubusercontent.com/royalpinto007/ai-agent-test-repo/main/sdlc-agent/n8n-workflow-2-approval.json
   ```
4. Add GitHub credential: **Settings → Credentials → Add → GitHub API** (paste token)
5. Apply the credential to every GitHub node in both workflows
6. Activate both workflows (green toggle)

### 5. Add GitHub webhook

Go to `https://github.com/Thrive-ERP/thrive-requirements/settings/hooks` → Add webhook:

| Field | Value |
|-------|-------|
| Payload URL | `https://agent-workflow.accellier.net/webhook/sdlc-start` |
| Content type | `application/json` |
| Secret | value of `WEBHOOK_SECRET` from `/etc/sdlc-agent/env` |
| Events | Issues, Issue comments |

### 6. Create GitHub milestones

Create these milestones on `Thrive-ERP/thrive-requirements` at `https://github.com/Thrive-ERP/thrive-requirements/milestones`:

- `BA Awaiting Approval`
- `BA Working`
- `SA Awaiting Approval`
- `SA Working`
- `PM Awaiting Approval`
- `PM Working`
- `DEV Awaiting Approval`
- `DEV Working`
- `Deploy / Complete`

The API creates them automatically if missing, but creating upfront avoids the first-run delay.

### 7. Verify

```bash
curl http://localhost:5001/repos          # API up, repos registered
curl http://localhost:5678/healthz        # n8n up
claude -p "say hello"                     # Claude CLI working
```

---

## Firewall / NAT (LXC containers)

If the API runs inside an LXC container on a bridged network, the host needs to forward traffic to the container:

```bash
# On the LXD host
iptables -I FORWARD -p tcp -d 10.68.103.135 --dport 5001 -j ACCEPT
iptables -t nat -A PREROUTING -i eno1np0 -p tcp --dport 5001 -j DNAT --to-destination 10.68.103.135:5001
```

Replace `eno1np0` with your host's external interface and `10.68.103.135` with the container's IP.

---

## Useful commands

```bash
# Service status
systemctl status sdlc-api
systemctl status n8n

# Live logs
journalctl -u sdlc-api -f
journalctl -u n8n -f

# Restart after code changes
git -C /opt/sdlc-agent pull
systemctl restart sdlc-api

# Check registered repos
curl http://localhost:5001/repos | python3 -m json.tool
```

---

## Updating

```bash
git -C /opt/sdlc-agent pull
systemctl restart sdlc-api
```

For n8n workflow changes: delete and reimport the JSON files in n8n UI, re-apply GitHub credential, re-activate.

---

## Troubleshooting

**API unreachable from n8n**
- Check it's bound to `0.0.0.0`: `ss -tlnp | grep 5001` should show `0.0.0.0:5001`
- Check iptables rules allow forwarding to the container
- Test from n8n's network: `curl http://10.68.103.135:5001/repos`

**Claude CLI not authenticated after reboot**
- Auth is stored in `~/.claude/` for the user that ran `claude`
- The systemd service must run as the same user: check `User=` in `/etc/systemd/system/sdlc-api.service`
- Re-authenticate: run `claude` as that user and follow the browser flow

**`setup-thrive.sh` hangs mid-clone**
- Some repos are large; `--depth=1` is used but clones can still take 60-120s each
- The script has 120s timeouts — it will skip and continue; re-run to retry failed repos
- Run with `GIT_TERMINAL_PROMPT=0` to prevent credential prompts blocking the script

**n8n expression errors**
- Ensure Body Content Type is `JSON` and Specify Body is `Using JSON` (not Raw) in each HTTP Request node
- Expression values must use `={{ ... }}` syntax — a backslash before `$` breaks evaluation
