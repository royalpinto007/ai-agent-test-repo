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
