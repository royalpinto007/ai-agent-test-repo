import logging
import re
import subprocess
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

RESET_BUFFER_SECONDS = 30
MAX_RETRIES = 1


def _parse_reset_seconds(stderr: str) -> int | None:
    """Return seconds to wait until Claude's rate limit resets, or None if not a limit error."""
    text = stderr or ""

    m = re.search(r"reset[s]?\s*(?:at)?\s*[|:]?\s*(\d{10})", text, re.IGNORECASE)
    if m:
        reset_ts = int(m.group(1))
        return max(0, reset_ts - int(time.time()))

    if re.search(r"(usage limit reached|rate limit|too many requests)", text, re.IGNORECASE):
        m = re.search(r"reset[s]?\s*(?:at)?\s*(\d{1,2}):(\d{2})\s*(am|pm)?", text, re.IGNORECASE)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            ampm = (m.group(3) or "").lower()
            if ampm == "pm" and hour < 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
            now = datetime.now(timezone.utc).astimezone()
            reset = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if reset <= now:
                reset = reset.replace(day=reset.day + 1)
            return int((reset - now).total_seconds())
        return 3600

    return None


def ask_claude(prompt):
    attempts = 0
    while True:
        result = subprocess.run(
            ["claude", "-p", "--tools", ""],
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
            return output

        stderr = result.stderr.strip()
        wait_seconds = _parse_reset_seconds(stderr + " " + result.stdout)
        if wait_seconds is not None and attempts < MAX_RETRIES:
            sleep_for = wait_seconds + RESET_BUFFER_SECONDS
            log.warning(
                "Claude usage limit hit. Sleeping %ds (until reset + %ds buffer) before retry.",
                sleep_for,
                RESET_BUFFER_SECONDS,
            )
            time.sleep(sleep_for)
            attempts += 1
            continue

        raise RuntimeError(f"claude exited {result.returncode}: {stderr}")
