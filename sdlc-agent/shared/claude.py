import logging
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

RESET_BUFFER_SECONDS = 30
MAX_RETRIES = 1
# Above this, don't block the request waiting for the limit to reset (a usage-limit
# window can be hours). Surface a ClaudeUsageLimitError so the caller can post a
# clear "try again after the reset" comment instead of hanging.
MAX_BLOCKING_WAIT_SECONDS = 300


class ClaudeUsageLimitError(RuntimeError):
    """Raised when Claude's usage/rate limit is hit and we won't keep waiting.

    Carries how long until reset so callers can tell the user when to retry.
    """

    def __init__(self, wait_seconds, raw_stderr=""):
        self.wait_seconds = max(0, int(wait_seconds or 0))
        self.raw_stderr = raw_stderr
        super().__init__(self.user_message)

    @property
    def reset_at_str(self):
        reset = datetime.now(timezone.utc).astimezone() + timedelta(seconds=self.wait_seconds)
        return reset.strftime("%-I:%M %p on %b %-d")

    @property
    def _hours(self):
        return max(1, round(self.wait_seconds / 3600)) if self.wait_seconds >= 1800 else None

    @property
    def reset_clause(self):
        if self.wait_seconds <= 0:
            return "Please try again later."
        if self._hours:
            window = f"about {self._hours}h"
        else:
            window = f"about {max(1, round(self.wait_seconds / 60))} min"
        return (f"Limits reset in {window} (around {self.reset_at_str}). "
                f"This step will resume automatically after the reset — no action needed.")

    @property
    def user_message(self):
        return f"Claude usage limit reached. {self.reset_clause}"

    def comment_body(self, stage=None):
        where = f" at the **{stage}** step" if stage else ""
        return (f"⏳ **Claude usage limit reached.**\n\n"
                f"The pipeline paused{where} because the account's Claude usage limit is "
                f"currently exhausted. {self.reset_clause}\n\n"
                f"_No work was lost — the pipeline will pick this step back up on its own._")

# Optional model override. Set CLAUDE_MODEL in the environment (e.g. in
# /etc/sdlc-agent/env) to pin a specific model — e.g. "haiku" for a lighter,
# cheaper pipeline. If unset, the claude CLI uses the account default.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "").strip()


def _claude_cmd():
    cmd = ["claude", "-p", "--tools", ""]
    if CLAUDE_MODEL:
        cmd += ["--model", CLAUDE_MODEL]
    return cmd


# Agentic (tool-enabled) invocation — used by the Dolibarr/Thrive Dev path so the
# dolibarr-dev skill can scan code, read/edit files, and drive the live install
# via its MCP server instead of having whole files pasted into the prompt. Gated
# per-repo in the Dev agent; the default text-mode path above is unchanged.
#
# Allowed tools and the MCP-server config are configurable via env so the box can
# tune them without a code change. Defaults match what the dolibarr-dev skill needs.
AGENTIC_ALLOWED_TOOLS = os.environ.get(
    "DOLIBARR_DEV_ALLOWED_TOOLS",
    "Bash Read Edit Write Grep Glob mcp__dolibarr_expert",
).strip()
AGENTIC_MCP_CONFIG = os.environ.get("DOLIBARR_DEV_MCP_CONFIG", "").strip()
AGENTIC_TIMEOUT = int(os.environ.get("DOLIBARR_DEV_TIMEOUT", "0") or "0")
# Headless permission posture. The skill needs Bash (its scan/db/log scripts) and
# the MCP, which a non-interactive `claude -p` can only use under an explicit
# permission mode. This defaults to "acceptEdits" (auto-applies file edits only);
# to let the skill run its shell helpers unattended, the box operator opts in by
# setting DOLIBARR_DEV_PERMISSION_MODE=bypassPermissions in /etc/sdlc-agent/env.
# Kept as an env knob on purpose: enabling arbitrary command execution is the
# operator's call, not a default baked into the code.
AGENTIC_PERMISSION_MODE = os.environ.get("DOLIBARR_DEV_PERMISSION_MODE", "acceptEdits").strip()


def _claude_agentic_cmd(cwd, allowed_tools=None, mcp_config=None, extra_dirs=None):
    cmd = ["claude", "-p"]
    if AGENTIC_PERMISSION_MODE:
        cmd += ["--permission-mode", AGENTIC_PERMISSION_MODE]
    if CLAUDE_MODEL:
        cmd += ["--model", CLAUDE_MODEL]
    tools = (allowed_tools if allowed_tools is not None else AGENTIC_ALLOWED_TOOLS).strip()
    if tools:
        cmd += ["--allowedTools", tools]
    # Allow tool access to the working dir (the checked-out module) plus any extra
    # dirs (e.g. the Dolibarr root so the skill's scripts can read core).
    for d in [cwd, *(extra_dirs or [])]:
        if d:
            cmd += ["--add-dir", d]
    mcp = mcp_config if mcp_config is not None else AGENTIC_MCP_CONFIG
    if mcp:
        cmd += ["--mcp-config", mcp]
    return cmd

_TOOL_CALL_BLOCK = re.compile(
    r"<function_calls>.*?</function_calls>\s*",
    re.DOTALL | re.IGNORECASE,
)


def _strip_tool_calls(text: str) -> str:
    """Remove any leaked tool-call XML from agent output."""
    return _TOOL_CALL_BLOCK.sub("", text).strip()


def _parse_reset_seconds(stderr: str) -> int | None:
    """Return seconds to wait until Claude's rate limit resets, or None if not a limit error."""
    text = stderr or ""

    m = re.search(r"reset[s]?\s*(?:at)?\s*[|:]?\s*(\d{10})", text, re.IGNORECASE)
    if m:
        reset_ts = int(m.group(1))
        return max(0, reset_ts - int(time.time()))

    # Match the real Claude CLI limit phrasings, including "You've hit your
    # session limit · resets 1:50pm (UTC)" which previously slipped through to a
    # generic error instead of the graceful auto-resume.
    if re.search(r"(usage limit|session limit|rate limit|too many requests|limit reached)", text, re.IGNORECASE):
        m = re.search(r"reset[s]?\s*(?:at)?\s*(\d{1,2}):(\d{2})\s*(am|pm)?", text, re.IGNORECASE)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            ampm = (m.group(3) or "").lower()
            if ampm == "pm" and hour < 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
            # The CLI states the reset in UTC ("(UTC)"); honour that when present
            # so we don't mis-compute on a non-UTC box.
            now = datetime.now(timezone.utc) if "utc" in text.lower() else datetime.now(timezone.utc).astimezone()
            reset = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if reset <= now:
                reset += timedelta(days=1)
            return int((reset - now).total_seconds())
        return 3600

    return None


def _run_claude(cmd, prompt, cwd=None, timeout=None):
    """Run a `claude` CLI invocation with the usage-limit retry/raise handling
    shared by the text-mode and agentic paths. Returns raw stdout (stripped)."""
    attempts = 0
    while True:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout or None,
        )
        if result.returncode == 0:
            return result.stdout.strip()

        stderr = result.stderr.strip()
        wait_seconds = _parse_reset_seconds(stderr + " " + result.stdout)
        if wait_seconds is not None:
            if wait_seconds <= MAX_BLOCKING_WAIT_SECONDS and attempts < MAX_RETRIES:
                sleep_for = wait_seconds + RESET_BUFFER_SECONDS
                log.warning(
                    "Claude rate limit hit. Sleeping %ds (until reset + %ds buffer) before retry.",
                    sleep_for, RESET_BUFFER_SECONDS,
                )
                time.sleep(sleep_for)
                attempts += 1
                continue
            log.warning("Claude usage limit reached; reset in ~%ds. Not blocking.", wait_seconds)
            raise ClaudeUsageLimitError(wait_seconds, raw_stderr=stderr)

        detail = stderr or (result.stdout or "").strip()[:800] or "(no output on stderr or stdout)"
        log.error("claude exited %s: %s", result.returncode, detail)
        raise RuntimeError(f"claude exited {result.returncode}: {detail}")


def ask_claude_agentic(prompt, cwd, allowed_tools=None, mcp_config=None, extra_dirs=None, timeout=None):
    """Tool-enabled, single-turn agentic run. Claude works in `cwd` (a checked-out
    module/repo), using the dolibarr-dev skill, file tools, and its MCP server, and
    edits files in place. Returns the final assistant text (e.g. a PR description /
    summary trailer); file changes are read from the working tree by the caller."""
    cmd = _claude_agentic_cmd(cwd, allowed_tools=allowed_tools, mcp_config=mcp_config, extra_dirs=extra_dirs)
    output = _run_claude(cmd, prompt, cwd=cwd, timeout=timeout or (AGENTIC_TIMEOUT or None))
    return _strip_tool_calls(output)


def ask_claude(prompt):
    attempts = 0
    while True:
        result = subprocess.run(
            _claude_cmd(),
            input=prompt,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            if output.startswith("```"):
                lines = output.splitlines()
                lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                output = "\n".join(lines)
            return _strip_tool_calls(output)

        stderr = result.stderr.strip()
        wait_seconds = _parse_reset_seconds(stderr + " " + result.stdout)
        if wait_seconds is not None:
            # Short, transient throttle: wait it out once, then retry.
            if wait_seconds <= MAX_BLOCKING_WAIT_SECONDS and attempts < MAX_RETRIES:
                sleep_for = wait_seconds + RESET_BUFFER_SECONDS
                log.warning(
                    "Claude rate limit hit. Sleeping %ds (until reset + %ds buffer) before retry.",
                    sleep_for,
                    RESET_BUFFER_SECONDS,
                )
                time.sleep(sleep_for)
                attempts += 1
                continue
            # Long usage-limit window (hours) or retries exhausted: don't block the
            # request — surface a typed error so the caller can post a clear comment.
            log.warning("Claude usage limit reached; reset in ~%ds. Not blocking.", wait_seconds)
            raise ClaudeUsageLimitError(wait_seconds, raw_stderr=stderr)

        # stderr is often empty on a non-zero exit; the real reason (oversized
        # input, an API error, a CLI message) usually lands on stdout. Surface
        # whichever we have so the failure isn't an opaque "claude exited 1:".
        detail = stderr or (result.stdout or "").strip()[:800] or "(no output on stderr or stdout)"
        log.error("claude exited %s: %s", result.returncode, detail)
        raise RuntimeError(f"claude exited {result.returncode}: {detail}")
