# Updating the Thrive SDLC agent, skill, and MCP

How to deploy changes to each moving part on the **ThriveERP-Agent** box, and
which of them need a service restart. Most don't — only the Python pipeline does.

Box layout:
- Pipeline (this repo): `/opt/sdlc-agent/sdlc-agent/` — runs as the `sdlc-api.service`
  systemd unit (Flask, `sdlc_api.py`), as root (`HOME=/root`).
- Skill: `sdlc-agent/skills/dolibarr-dev/`, symlinked into `/root/.claude/skills/`.
- MCP server: `Thrive-ERP/mcp-dolibarr` branch `ai`, cloned at `/opt/repos/mcp-dolibarr`,
  built to `build/index.js`; config `/etc/sdlc-agent/dolibarr-mcp.json`.
- MCP's PHP backend: the `aimodulebuilder` Dolibarr module (repo
  `Thrive-ERP/dolibarr_custom_aimodulebuilder`) at
  `/opt/repos/dolibarr/htdocs/custom/aimodulebuilder`, served at
  `http://127.0.0.1:8080/api/index.php/aimodulebuilder/...`.
- Live Dolibarr root: `DOL_HTDOCS=/opt/repos/dolibarr/htdocs`.

## Cheat sheet — what needs a restart

| You changed… | Deploy | Restart `sdlc-api`? |
|---|---|---|
| Skill `.md` / scripts | `git pull` | no (read per agent run) |
| Pipeline Python (`agents/`, `shared/`, `sdlc_api.py`) | `git pull` | **yes** |
| MCP TypeScript | `git pull && npm run build` in `/opt/repos/mcp-dolibarr` | no (spawned per run) |
| MCP config / `/etc/sdlc-agent/env` | edit file | **yes** |
| `aimodulebuilder` PHP module | `git pull` + `chown` (+ reactivate if schema) | no |

Restart when needed: `sudo systemctl restart sdlc-api.service`

---

## 1. Skill (`dolibarr-dev`)

Source of truth is this repo (`sdlc-agent/skills/dolibarr-dev/`). It's symlinked into
root's `~/.claude/skills/`, and the skill is read from disk on every agent run, so a
pull is enough — **no restart**.

```bash
# on your machine: edit skills/dolibarr-dev/SKILL.md (or scripts/), commit, push to main
# on the box:
cd /opt/sdlc-agent/sdlc-agent && git pull
```

- Verify the symlink: `ls -la /root/.claude/skills/dolibarr-dev`
  → should point at `/opt/sdlc-agent/sdlc-agent/skills/dolibarr-dev`.
  If missing: `ln -sfn /opt/sdlc-agent/sdlc-agent/skills/dolibarr-dev /root/.claude/skills/dolibarr-dev`
- Do NOT touch `LEARNINGS.local.md` or `.dolibarr-dev/` — untracked runtime memory,
  not part of the deploy.
- The `Skill` tool MUST stay in `DOLIBARR_DEV_ALLOWED_TOOLS` (default
  `"Bash Read Edit Write Grep Glob Skill mcp__dolibarr_expert"`), or the skill is inert.

## 2. MCP server (`dolibarr_expert` = `mcp-dolibarr`, branch `ai`)

A TypeScript server spawned fresh per agent run (stdio), so pull + rebuild — **no restart**.

```bash
cd /opt/repos/mcp-dolibarr
git pull
npm install       # only if dependencies changed
npm run build     # regenerates build/index.js (what dolibarr-mcp.json runs)
```

- Picked up on the next agent run automatically.
- Restart `sdlc-api` ONLY if you changed `/etc/sdlc-agent/env` or the config file.
- Smoke test:
  ```bash
  claude -p --mcp-config /etc/sdlc-agent/dolibarr-mcp.json \
    --allowedTools "mcp__dolibarr_expert" -- "list your mcp__dolibarr_expert tools"
  ```
- Config `/etc/sdlc-agent/dolibarr-mcp.json` — the server key MUST be `dolibarr_expert`
  (tools surface as `mcp__dolibarr_expert__*`). `DOLIBARR_URL` is the FULL path
  `http://127.0.0.1:8080/api/index.php`.
- NEVER blank out `DOLIBARR_DEV_MCP_CONFIG` in `/etc/sdlc-agent/env` — an empty value
  means the MCP silently doesn't attach and the agent hand-scaffolds with no error.

## 3. MCP PHP backend (`aimodulebuilder` module)

The MCP's `aimodulebuilder_*` tools call this Dolibarr module over REST. Update it when
the module builder's server-side behaviour changes.

```bash
cd /opt/repos/dolibarr/htdocs/custom/aimodulebuilder
TOKEN=<gh-token>   # private repo → inline auth required
git pull https://x-access-token:$TOKEN@github.com/Thrive-ERP/dolibarr_custom_aimodulebuilder.git main
chown -R www-data:www-data .
# only if you changed its DB schema/rights — reactivate to apply:
cd /opt/repos/dolibarr/htdocs
sudo -u www-data php -r 'require "master.inc.php"; dol_include_once("/aimodulebuilder/core/modules/modAIModuleBuilder.class.php"); $m=new modAIModuleBuilder($db); $m->remove(""); $m->init("");'
# verify the API is healthy:
curl -s -H "DOLAPIKEY: <admin-api-key>" http://127.0.0.1:8080/api/index.php/aimodulebuilder/status
```

Expect `{"success":true,"module":"aimodulebuilder","active":true,...}`.

---

## Recurring gotchas

- **Private-repo pull/clone** needs the inline `https://x-access-token:<TOKEN>@github.com/...`
  URL — the box git has no cached credential for these repos. Scrub the token from the
  remote afterwards (`git remote set-url origin https://github.com/<org>/<repo>.git`).
- **`www-data`-owned repo pulled as root** trips git "dubious ownership":
  `git config --global --add safe.directory <path>`.
- **Claude auth precedence:** `ANTHROPIC_API_KEY` > `CLAUDE_CODE_OAUTH_TOKEN` > `~/.claude`
  login. A stale `CLAUDE_CODE_OAUTH_TOKEN` in `/etc/sdlc-agent/env` shadows a working login
  and 401s the agents. `claude setup-token` mints a 1-year token.
- **Verifying MCP use:** don't count tool names in a session's `dev_raw_output` — that's the
  agent's prose summary, not the tool-call log (gives false zeros). Real proof is the
  generated files (native skeleton: `<module>index.php`, `.tx/`, `build/`, `COPYING`,
  `llx_<module>_<object>.sql`) and `.dolibarr-dev/BRAIN.md`. A clean MCP module has NO
  `uninstall.sql` and NO bare `llx_<module>.sql`, and `$table_element = '<module>_<object>'`.
