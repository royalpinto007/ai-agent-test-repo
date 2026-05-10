#!/bin/bash
# SDLC Agent — full server setup
# Run as root on Ubuntu 24.04
# Usage: bash setup.sh

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
section() { echo -e "\n${GREEN}━━━ $1 ━━━${NC}"; }

# ── Collect config upfront ────────────────────────────────────────────────────
section "Configuration"

read -p "GitHub Personal Access Token (repo scope): " GITHUB_TOKEN
[ -z "$GITHUB_TOKEN" ] && error "GITHUB_TOKEN is required"

read -p "Domain or server IP (e.g. sdlc.example.com or 10.68.103.135): " SERVER_HOST
[ -z "$SERVER_HOST" ] && error "SERVER_HOST is required"

read -p "Slack channel for notifications (leave blank to skip, e.g. #deployments): " SLACK_CHANNEL

read -p "Webhook secret for GitHub (leave blank to generate one): " WEBHOOK_SECRET
[ -z "$WEBHOOK_SECRET" ] && WEBHOOK_SECRET=$(openssl rand -hex 32) && info "Generated webhook secret: $WEBHOOK_SECRET"

INSTALL_DIR="/opt/sdlc-agent"
REPOS_DIR="/opt/repos"
ENV_FILE="/etc/sdlc-agent/env"
SERVICE_USER=${SUDO_USER:-root}

# ── System packages ───────────────────────────────────────────────────────────
section "System packages"
apt-get update -qq
apt-get install -y -qq \
  git curl unzip nginx certbot python3-certbot-nginx \
  python3 python3-pip python3-venv \
  openssl build-essential

# ── Node.js 20 ────────────────────────────────────────────────────────────────
section "Node.js 20"
if ! command -v node &>/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi
info "Node $(node --version), npm $(npm --version)"

# ── Claude Code CLI ───────────────────────────────────────────────────────────
section "Claude Code CLI"
if ! command -v claude &>/dev/null; then
  npm install -g @anthropic-ai/claude-code
  info "Installed claude $(claude --version 2>/dev/null || echo '')"
else
  info "Claude Code already installed"
fi

# ── n8n ───────────────────────────────────────────────────────────────────────
section "n8n"
if ! command -v n8n &>/dev/null; then
  npm install -g n8n
fi
info "n8n installed"

# ── Clone SDLC agent repo ─────────────────────────────────────────────────────
section "Clone SDLC agent"
if [ ! -d "$INSTALL_DIR" ]; then
  git clone https://github.com/royalpinto007/ai-agent-test-repo.git "$INSTALL_DIR"
else
  info "Already cloned — pulling latest"
  git -C "$INSTALL_DIR" pull
fi

# ── Python venv ───────────────────────────────────────────────────────────────
section "Python dependencies"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/sdlc-agent/requirements.txt"
info "Python deps installed"

# ── Repos directory ───────────────────────────────────────────────────────────
section "Repos directory"
mkdir -p "$REPOS_DIR"
info "Target repos go in $REPOS_DIR — clone them manually after setup"

# ── Environment file ──────────────────────────────────────────────────────────
section "Environment file"
mkdir -p /etc/sdlc-agent
cat > "$ENV_FILE" << ENVEOF
GITHUB_TOKEN=${GITHUB_TOKEN}
WEBHOOK_SECRET=${WEBHOOK_SECRET}
SLACK_CHANNEL=${SLACK_CHANNEL}
ENVEOF
chmod 600 "$ENV_FILE"
info "Written to $ENV_FILE"

# ── Systemd: sdlc-api ─────────────────────────────────────────────────────────
section "Systemd service: sdlc-api"
cat > /etc/systemd/system/sdlc-api.service << SVCEOF
[Unit]
Description=SDLC Agent API
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}/sdlc-agent
EnvironmentFile=${ENV_FILE}
ExecStart=${INSTALL_DIR}/venv/bin/python sdlc_api.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

# ── Systemd: n8n ──────────────────────────────────────────────────────────────
section "Systemd service: n8n"
cat > /etc/systemd/system/n8n.service << SVCEOF
[Unit]
Description=n8n Workflow Automation
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
EnvironmentFile=${ENV_FILE}
Environment=N8N_PORT=5678
Environment=N8N_PROTOCOL=http
Environment=WEBHOOK_URL=https://${SERVER_HOST}
ExecStart=/usr/bin/n8n start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable sdlc-api n8n
systemctl start sdlc-api n8n
info "Services started"

# ── nginx ─────────────────────────────────────────────────────────────────────
section "nginx"
cat > /etc/nginx/sites-available/sdlc << NGINXEOF
server {
    listen 80;
    server_name ${SERVER_HOST};

    location / {
        proxy_pass http://localhost:5678;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_cache_bypass \$http_upgrade;
        proxy_read_timeout 1800;
    }

    location /api/ {
        rewrite ^/api/(.*)$ /\$1 break;
        proxy_pass http://localhost:5001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 1800;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/sdlc /etc/nginx/sites-enabled/sdlc
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
info "nginx configured"

# ── HTTPS (only if SERVER_HOST is a real domain, not an IP) ───────────────────
if [[ "$SERVER_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  warn "SERVER_HOST looks like an IP — skipping certbot (HTTPS needs a domain)"
else
  section "HTTPS (certbot)"
  certbot --nginx -d "$SERVER_HOST" --non-interactive --agree-tos -m "admin@${SERVER_HOST}" || \
    warn "certbot failed — run manually: certbot --nginx -d ${SERVER_HOST}"
fi

# ── Make scripts executable ───────────────────────────────────────────────────
chmod +x "$INSTALL_DIR/sdlc-agent/scripts/"*.sh 2>/dev/null || true

# ── Sessions cleanup cron ─────────────────────────────────────────────────────
section "Cron: session cleanup"
(crontab -l 2>/dev/null; echo "0 3 * * * find ${INSTALL_DIR}/sdlc-agent/sessions -name '*.json' -mtime +30 -delete") | crontab -
info "Cron added: sessions older than 30 days deleted nightly"

# ── Done ──────────────────────────────────────────────────────────────────────
section "Setup complete"

echo ""
echo -e "${GREEN}✅ Installation done.${NC}"
echo ""
echo "━━━ Next steps (do these in order) ━━━"
echo ""
echo "1. AUTHENTICATE CLAUDE CODE (required — opens a browser URL):"
echo "   claude"
echo "   → Open the URL it prints, log in, paste the code back."
echo "   → Auth is stored in ~/.claude/ and persists across reboots."
echo ""
echo "2. CLONE YOUR TARGET REPOS into $REPOS_DIR:"
echo "   git clone https://github.com/your-org/your-repo.git $REPOS_DIR/your-repo"
echo ""
echo "3. REGISTER REPOS with the API:"
echo "   curl -s http://localhost:5001/repos"
echo "   curl -X POST http://localhost:5001/repos \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"owner\":\"your-org\",\"repo\":\"your-repo\",\"repo_path\":\"$REPOS_DIR/your-repo\",\"test_command\":[\"npm\",\"test\"],\"main_branch\":\"main\"}'"
echo ""
echo "4. OPEN n8n at http://${SERVER_HOST} and:"
echo "   a. Import sdlc-agent/n8n-workflow-1-start.json"
echo "   b. Import sdlc-agent/n8n-workflow-2-approval.json"
echo "   c. Add GitHub credential (Settings → Credentials → GitHub API)"
echo "   d. Apply credential to every GitHub node in both workflows"
echo "   e. Activate both workflows (green toggle)"
echo ""
echo "5. ADD GITHUB WEBHOOK to each repo:"
echo "   Payload URL : https://${SERVER_HOST}/webhook/sdlc-start"
echo "   Content type: application/json"
echo "   Secret      : ${WEBHOOK_SECRET}"
echo "   Events      : Issues, Issue comments"
echo ""
echo "6. VERIFY everything:"
echo "   curl http://localhost:5001/repos          # API up"
echo "   curl http://localhost:5678/healthz         # n8n up"
echo "   claude -p 'say hello'                      # Claude CLI working"
echo ""
echo "━━━ Useful commands ━━━"
echo "  systemctl status sdlc-api         # API status"
echo "  systemctl status n8n              # n8n status"
echo "  journalctl -u sdlc-api -f         # API logs"
echo "  journalctl -u n8n -f              # n8n logs"
echo "  systemctl restart sdlc-api        # restart after code changes"
echo ""
echo -e "Webhook secret (save this): ${YELLOW}${WEBHOOK_SECRET}${NC}"
echo ""
echo "━━━ Thrive-ERP setup (optional) ━━━"
echo ""
echo "If you are setting this up for Thrive-ERP / agent-accellier, run:"
echo "  GITHUB_TOKEN=\$GITHUB_TOKEN bash ${INSTALL_DIR}/sdlc-agent/scripts/setup-thrive.sh"
echo ""
echo "This will fork all 31 Thrive-ERP repos to agent-accellier, clone them,"
echo "register them with the API, and set up daily upstream sync."
