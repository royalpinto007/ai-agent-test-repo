# Wiring `dolibarr-dev` into the SDLC Dev agent (Thrive)

The Dev stage runs **text-mode** by default (`claude -p --tools ""`: files pasted
in, SEARCH/REPLACE blocks parsed out). For the **Thrive (Dolibarr)** code repo it
instead runs an **agentic** Claude that loads this skill and edits the live module
directly with tools + the `dolibarr_expert` MCP. This is opt-in **per repo** — the
Moodle/IOMAD (acorn) repos are untouched and keep the text path.

## Code (already in the repo, deploys via `git pull`)
- `agents/dev/agent.py` — dispatches to `_run_agentic()` when the target repo is
  agentic; derives changed files from `git status`, lints, tests, commits, PRs.
- `shared/claude.py` — `ask_claude_agentic()` builds the `claude -p` command with
  tools, `--add-dir`, `--mcp-config`, and the permission mode.
- `agents/dev/prompts.py` — `agentic_implementation_prompt` / `agentic_retry_prompt`.
- `skills/dolibarr-dev/` — this skill (SKILL.md, scripts, LEARNINGS.md).

## Box changes required (Thrive box only)

1. **Pull + restart** (standard deploy):
   ```bash
   cd /opt/sdlc-agent && git pull && sudo systemctl restart sdlc-api
   ```

2. **Install the skill** so the `claude` CLI discovers it (run as the same user the
   service uses — root on these boxes). Symlink so future `git pull`s update it:
   ```bash
   mkdir -p ~/.claude/skills
   ln -sfn /opt/sdlc-agent/sdlc-agent/skills/dolibarr-dev ~/.claude/skills/dolibarr-dev
   ```

3. **Mark the Thrive code repo agentic** in `repos.json` (the code repo entry the
   PM/Dev target — NOT the requirements repo). Add:
   ```json
   "Thrive-ERP/<thrive-code-repo>": {
     "repo_path": "/var/www/.../htdocs/custom/<module>",
     "main_branch": "main",
     "test_command": ["…phpunit…"],
     "dev_mode": "agentic",
     "skill": "dolibarr-dev",
     "dol_htdocs": "/var/www/.../htdocs",
     "mcp_config": "/etc/sdlc-agent/dolibarr-mcp.json"
   }
   ```
   - `repo_path` should be the module dir inside the **live** htdocs so edits are
     live immediately and the skill's `dol-db.sh`/`dol-log.sh` hit the same install.
   - `dol_htdocs` is added to `--add-dir` so the skill can read Dolibarr core.
   - `mcp_config` points at the `dolibarr_expert` MCP server definition.

4. **Env** (`/etc/sdlc-agent/env`) — optional knobs (sensible defaults exist):
   ```
   # MCP config (or set per-repo "mcp_config" as above)
   DOLIBARR_DEV_MCP_CONFIG=/etc/sdlc-agent/dolibarr-mcp.json
   # Tools the agent may use (default below). `Skill` is REQUIRED — without it the
   # model cannot invoke the dolibarr-dev skill and silently falls back to plain edits.
   DOLIBARR_DEV_ALLOWED_TOOLS=Bash Read Edit Write Grep Glob Skill mcp__dolibarr_expert
   # Headless permission posture. Default acceptEdits + the Bash allowlist runs the
   # skill's scripts without prompting. Set to bypassPermissions ONLY if you want
   # fully-unattended arbitrary command execution (operator's explicit choice).
   DOLIBARR_DEV_PERMISSION_MODE=acceptEdits
   # Optional wall-clock cap (seconds) for one agentic run; 0 = no limit.
   DOLIBARR_DEV_TIMEOUT=0
   ```

5. **MCP server** — `dolibarr-mcp.json` must define the `dolibarr_expert` server
   (the `amb_*` / business-flow tools). The skill degrades gracefully if a tool is
   missing (e.g. `amb_*` → hand-scaffold fallback), but the live-verify steps need it.

## Verifying the wiring on the box
- Quick check the CLI accepts the flags: `claude -p --permission-mode acceptEdits
  --allowedTools "Bash Read" --add-dir "$PWD" -- "echo skill-check"` (should run).
- Confirm the skill resolves: in the repo dir, `claude` → `/dolibarr-dev` lists it.
- Then run a real issue through the pipeline and watch the Dev stage open a PR.
