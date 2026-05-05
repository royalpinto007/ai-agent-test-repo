# Deploying the SDLC Agent on a Server

This guide covers running the full pipeline — Flask API, n8n, and Claude Code CLI — on a Linux server with a public IP. Once set up, you point GitHub webhooks at the server and the pipeline runs entirely remotely.

---

## What runs on the server

| Component | Port | What it does |
|-----------|------|-------------|
| Flask API (`sdlc_api.py`) | 5001 | Receives n8n calls, runs agents, writes sessions |
| n8n | 5678 | Handles GitHub webhooks, routes approvals |
| nginx | 80 / 443 | Reverse proxy — exposes n8n and optionally the API |
| Claude Code CLI | — | Called by the API as a subprocess to run LLM calls |

---

## Server requirements

- Ubuntu 22.04 or Debian 12 (any modern Linux works)
- 2 vCPU, 4 GB RAM minimum (agents run Claude Code as subprocesses — more RAM = better)
- 20 GB disk
- A public IP or domain name
- Ports 80, 443, and 5678 open in your firewall

Providers that work well: Hetzner CX22, DigitalOcean Droplet (2 GB+), AWS EC2 t3.small, Vultr.

---

## 1. System dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-pip python3-venv nginx curl unzip
```

### Node.js (required for Claude Code CLI and n8n)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

### Claude Code CLI

```bash
npm install -g @anthropic-ai/claude-code
```

Authenticate it — this is the only interactive step:

```bash
claude
```

Follow the browser login flow. Once authenticated, `claude -p "hello"` should return a response. The auth token is stored in `~/.claude/` and persists across sessions.

### n8n

```bash
npm install -g n8n
```

---

## 2. Clone the repo and install Python dependencies

```bash
git clone https://github.com/royalpinto007/ai-agent-test-repo.git /opt/sdlc-agent
cd /opt/sdlc-agent

python3 -m venv venv
source venv/bin/activate
pip install -r sdlc-agent/requirements.txt
```

---

## 3. Clone your target repos

Each repo the agents will work on must be cloned locally on the server:

```bash
git clone https://github.com/your-org/your-repo.git /opt/repos/your-repo
```

The `GITHUB_TOKEN` you set in step 4 needs push access to these repos.

---

## 4. Environment variables

Create a file that holds your secrets (not committed to git):

```bash
sudo mkdir -p /etc/sdlc-agent
sudo nano /etc/sdlc-agent/env
```

Add:

```
GITHUB_TOKEN=your_token_here
ANTHROPIC_API_KEY=your_key_here
```

Set permissions so only root can read it:

```bash
sudo chmod 600 /etc/sdlc-agent/env
```

These get loaded into the systemd services in step 6.

---

## 5. Configure repos.json

Edit `/opt/sdlc-agent/sdlc-agent/repos.json` with the repos you cloned in step 3:

```json
{
  "your-org/your-repo": {
    "repo_path": "/opt/repos/your-repo",
    "test_command": ["npm", "test"],
    "main_branch": "main"
  }
}
```

Or add repos at runtime via the API after the service is running:

```bash
curl -X POST http://localhost:5001/repos \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "your-org",
    "repo": "your-repo",
    "repo_path": "/opt/repos/your-repo",
    "test_command": ["npm", "test"],
    "main_branch": "main"
  }'
```

---

## 6. Systemd services

### Flask API

```bash
sudo nano /etc/systemd/system/sdlc-api.service
```

```ini
[Unit]
Description=SDLC Agent API
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/sdlc-agent/sdlc-agent
EnvironmentFile=/etc/sdlc-agent/env
ExecStart=/opt/sdlc-agent/venv/bin/python sdlc_api.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> Replace `User=ubuntu` with whatever user owns `/opt/sdlc-agent` on your server.

### n8n

```bash
sudo nano /etc/systemd/system/n8n.service
```

```ini
[Unit]
Description=n8n Workflow Automation
After=network.target

[Service]
Type=simple
User=ubuntu
EnvironmentFile=/etc/sdlc-agent/env
Environment=N8N_PORT=5678
Environment=N8N_PROTOCOL=http
Environment=WEBHOOK_URL=https://your-domain.com
ExecStart=/usr/bin/n8n start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> Set `WEBHOOK_URL` to your domain or server IP. n8n uses this to build webhook URLs correctly.

Enable and start both:

```bash
sudo systemctl daemon-reload
sudo systemctl enable sdlc-api n8n
sudo systemctl start sdlc-api n8n
```

Check they're running:

```bash
sudo systemctl status sdlc-api
sudo systemctl status n8n
```

---

## 7. nginx reverse proxy

nginx sits in front of n8n so GitHub webhooks hit port 80/443 instead of 5678.

```bash
sudo nano /etc/nginx/sites-available/sdlc
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # n8n — GitHub webhooks hit this
    location / {
        proxy_pass http://localhost:5678;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_cache_bypass $http_upgrade;
    }

    # Optional: expose the SDLC API directly (useful for debugging)
    location /api/ {
        rewrite ^/api/(.*)$ /$1 break;
        proxy_pass http://localhost:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/sdlc /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### HTTPS (recommended)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Certbot auto-renews. Once done, your webhook URL is `https://your-domain.com/webhook/sdlc-start`.

---

## 8. Import n8n workflows

Open n8n in a browser at `http://your-domain.com` (or `http://your-server-ip:5678` if you skipped nginx).

1. **Workflows → Import from File**
2. Import `n8n-workflow-1-start.json`
3. Import `n8n-workflow-2-approval.json`
4. Add your GitHub credentials: **Settings → Credentials → Add → GitHub API** (paste your token)
5. Apply the credential to every GitHub node in both workflows
6. Activate both workflows (green toggle, top right)

---

## 9. GitHub webhook

In each repo you want the pipeline to watch:

**Settings → Webhooks → Add webhook**

| Field | Value |
|-------|-------|
| Payload URL | `https://your-domain.com/webhook/sdlc-start` |
| Content type | `application/json` |
| Secret | leave blank |
| Events | Issues, Issue comments |

For multiple repos: add the same webhook URL to each one. The pipeline reads the owner and repo name from the payload automatically.

---

## 10. Verify everything works

```bash
# API is up
curl http://localhost:5001/repos

# n8n is up
curl http://localhost:5678/healthz

# Claude Code CLI works
claude -p "say hello"
```

Then open a test issue in one of your repos. Within a minute you should see the BA agent comment.

---

## Keeping repos in sync

The BA agent runs `git pull` before each run, so the local clone stays current. But if you push directly to the repo from another machine, the server clone will catch up on the next issue.

For repos with dependencies (npm, pip, etc.), you may need to re-run installs after major dependency updates. There's no automatic hook for this — do it manually or add it to your deployment process.

---

## Logs

```bash
# API logs
sudo journalctl -u sdlc-api -f

# n8n logs
sudo journalctl -u n8n -f

# nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

---

## Updating the pipeline

```bash
cd /opt/sdlc-agent
git pull
source venv/bin/activate
pip install -r sdlc-agent/requirements.txt  # only if requirements changed
sudo systemctl restart sdlc-api
```

n8n workflows update in the n8n UI — reimport the JSON files and re-activate.

---

## Adding a new repo later

1. Clone it on the server: `git clone https://github.com/org/repo.git /opt/repos/repo`
2. Register it:
   ```bash
   curl -X POST http://localhost:5001/repos \
     -H "Content-Type: application/json" \
     -d '{"owner": "org", "repo": "repo", "repo_path": "/opt/repos/repo", "test_command": ["npm", "test"], "main_branch": "main"}'
   ```
3. Add the GitHub webhook to that repo (same URL as step 9)

No n8n changes needed.

---

## Troubleshooting

**BA agent doesn't fire when I open an issue**
- Check the webhook delivered: repo → Settings → Webhooks → your webhook → Recent Deliveries
- Check n8n workflow 1 is active
- Check API is running: `sudo systemctl status sdlc-api`

**n8n can't reach the API (ECONNREFUSED)**
- The API service may have crashed: `sudo journalctl -u sdlc-api --no-pager -n 50`
- Restart it: `sudo systemctl restart sdlc-api`

**Claude Code CLI not found**
- Make sure `claude` is in the PATH for the user running the API service
- Check: `which claude` as that user
- If installed globally via npm, it's usually at `/usr/bin/claude` or `/usr/local/bin/claude`

**Git push fails from Dev agent**
- The `GITHUB_TOKEN` in `/etc/sdlc-agent/env` needs `repo` scope and write access to the target repo
- Test manually: `git push` from the cloned repo directory as the service user

**Sessions directory fills up**
- Sessions live in `sdlc-agent/sessions/` — safe to delete old ones
- Add a cron to clean up sessions older than 30 days:
  ```bash
  0 3 * * * find /opt/sdlc-agent/sdlc-agent/sessions -name "*.json" -mtime +30 -delete
  ```
