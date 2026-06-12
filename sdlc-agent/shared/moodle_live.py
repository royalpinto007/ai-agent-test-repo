"""Read-only grounding against the live Moodle/IOMAD instance (IOMAD-LIVE, .136).

The BA agent runs on the agent box (.242); the running site is a separate box
(.136). To ground a BRD in what is *actually configured* (rather than generic
Moodle knowledge), this module SSHes to the live box and reads settings via
Moodle's own `admin/cli/cfg.php`. Everything here is best-effort: if SSH isn't
configured, the host is unreachable, or a setting doesn't exist, we return an
empty/partial result so the pipeline degrades gracefully to its old behaviour.

Enable by setting in /etc/sdlc-agent/env (on the agent box):
    MOODLE_LIVE_SSH=root@10.68.103.136     # ssh target (user@host)
    MOODLE_LIVE_WWWROOT=/var/www/html      # Moodle dirroot on the live box
    MOODLE_LIVE_SSH_KEY=/root/.ssh/id_iomad_live   # optional private key
    MOODLE_LIVE_PHP=php                    # optional, php binary on the live box
"""
import os
import re
import json
import logging
import subprocess

log = logging.getLogger("moodle_live")

# Settings always worth reading regardless of the requirement — cheap, and they
# anchor the model in the site's real auth/registration posture.
DEFAULT_SETTINGS = [("core", "auth"), ("core", "registerauth"), ("core", "release")]

_SAFE = re.compile(r"^[A-Za-z0-9_]+$")
_MAX_SETTINGS = 8
_SSH_TIMEOUT = 20


def is_enabled():
    return bool(os.environ.get("MOODLE_LIVE_SSH", "").strip())


def _ssh_base():
    target = os.environ["MOODLE_LIVE_SSH"].strip()
    key = os.environ.get("MOODLE_LIVE_SSH_KEY", "").strip()
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
           "-o", "ConnectTimeout=8"]
    if key:
        cmd += ["-i", key]
    cmd += [target]
    return cmd


def _sanitise(specs):
    """Keep only well-formed (component, name) pairs; dedupe, cap the count."""
    out, seen = [], set()
    for comp, name in specs:
        comp = (comp or "core").strip()
        name = (name or "").strip()
        if not _SAFE.match(comp) or not _SAFE.match(name):
            continue
        key = (comp, name)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= _MAX_SETTINGS:
            break
    return out


def read_cfg(specs):
    """Read [(component, name), ...] from the live site. Returns {(comp,name): value|None}.

    One SSH round-trip: a small remote loop runs cfg.php per setting. `core`
    components read global config; anything else reads plugin config.
    """
    specs = _sanitise(specs)
    if not specs or not is_enabled():
        return {}
    wwwroot = os.environ.get("MOODLE_LIVE_WWWROOT", "/var/www/html").strip()
    php = os.environ.get("MOODLE_LIVE_PHP", "php").strip()
    # Specs are sanitised to [A-Za-z0-9_], so embedding them in the remote
    # script is safe (no shell-meta possible).
    spec_words = " ".join(f"{c}:{n}" for c, n in specs)
    script = f"""cd {wwwroot} 2>/dev/null || exit 3
for spec in {spec_words}; do
  comp="${{spec%%:*}}"; name="${{spec#*:}}"
  if [ "$comp" = "core" ]; then
    v=$({php} admin/cli/cfg.php --name="$name" 2>/dev/null)
  else
    v=$({php} admin/cli/cfg.php --component="$comp" --name="$name" 2>/dev/null)
  fi
  printf '%s\\t%s\\t%s\\n' "$comp" "$name" "$v"
done
"""
    try:
        proc = subprocess.run(
            _ssh_base() + ["bash -s"],
            input=script, capture_output=True, text=True, timeout=_SSH_TIMEOUT,
        )
    except Exception as e:
        log.warning("moodle_live SSH failed: %s", e)
        return {}
    if proc.returncode != 0 and not proc.stdout.strip():
        log.warning("moodle_live cfg read failed (rc=%s): %s", proc.returncode, proc.stderr.strip()[:200])
        return {}
    result = {}
    for line in proc.stdout.splitlines():
        cols = line.split("\t")
        if len(cols) >= 3:
            comp, name, value = cols[0], cols[1], "\t".join(cols[2:]).strip()
            result[(comp, name)] = value if value != "" else None
    return result


def _pick_settings(requirement, ask):
    """Ask the model which live Moodle settings would ground this requirement.

    `ask` is the ask_claude callable (passed in to avoid an import cycle).
    Returns a list of (component, name) on top of the always-on defaults.
    """
    prompt = f"""A Business Analyst is about to write a requirements doc for a Moodle/IOMAD site.
Before doing so, we will read the CURRENT value of a few live settings to ground the doc in reality.

REQUIREMENT:
{requirement}

List up to 5 Moodle config settings whose current value would be most useful to know for THIS requirement.
Use real Moodle setting names. For a core/global setting use component "core"; for a plugin setting use the plugin's frankenstyle component (e.g. "auth_email", "tool_iomad").
Return ONLY a JSON array like: [{{"component":"core","name":"registerauth"}}, {{"component":"auth_email","name":"recaptcha"}}]
No prose, no markdown."""
    try:
        raw = ask(prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1] if "```" in raw[3:] else raw.strip("`")
            raw = re.sub(r"^json", "", raw.strip(), flags=re.IGNORECASE).strip()
        picked = json.loads(raw)
        extra = [(d.get("component", "core"), d.get("name", "")) for d in picked if isinstance(d, dict)]
    except Exception:
        extra = []
    return DEFAULT_SETTINGS + extra


def live_state_for(requirement, ask):
    """Return a formatted 'CURRENT LIVE SITE CONFIG' block for the BA prompt, or "".

    Best-effort and self-contained: returns "" if grounding is disabled, the box
    is unreachable, or nothing could be read — the caller falls back to ungrounded
    behaviour in that case.
    """
    if not is_enabled():
        return ""
    try:
        values = read_cfg(_pick_settings(requirement, ask))
    except Exception as e:
        log.warning("live_state_for failed: %s", e)
        return ""
    if not values:
        return ""
    lines = []
    for (comp, name), val in values.items():
        label = name if comp == "core" else f"{comp}/{name}"
        shown = "(not set)" if val is None else val
        lines.append(f"- {label} = {shown}")
    host = os.environ.get("MOODLE_LIVE_SSH", "").split("@")[-1]
    return (f"CURRENT LIVE SITE CONFIG (read live from IOMAD-LIVE {host} via "
            f"admin/cli/cfg.php — these are the ACTUAL current values, not defaults):\n"
            + "\n".join(lines))
