"""Lightweight, best-effort local linting for the Dev stage.

Goal: catch problems the Dev agent introduces (syntax errors, NEW coding-standard
violations) on the files it changed — without drowning in a repo's pre-existing
violations. So phpcs is compared before/after and we only flag a *regression*.

All checks degrade gracefully: if the relevant binary isn't configured/available
they return "no problem", so the pipeline behaves exactly as before until the
toolchain is installed on the box.

Env:
  PHP_BIN     php binary for `php -l` syntax checks (default "php"; skipped if absent)
  PHPCS_BIN   phpcs binary for coding-standard checks (skipped if unset/absent)
  PHPCS_STANDARD  standard name (default "moodle")
"""
import os
import json
import shutil
import tempfile
import subprocess

PHP_BIN = os.environ.get("PHP_BIN", "php")
PHPCS_BIN = os.environ.get("PHPCS_BIN", "").strip()
PHPCS_STANDARD = os.environ.get("PHPCS_STANDARD", "moodle").strip() or "moodle"


def _have(binpath):
    return bool(binpath) and (shutil.which(binpath) is not None or os.path.exists(binpath))


def php_syntax_error(content):
    """Return a syntax-error message for PHP `content`, or None if it's valid /
    php is unavailable."""
    if not _have(PHP_BIN):
        return None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".php", delete=False) as f:
            f.write(content); path = f.name
        try:
            r = subprocess.run([PHP_BIN, "-l", path], capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                msg = (r.stdout + r.stderr).strip().replace(path, "<file>")
                return msg[:300] or "php -l reported a syntax error"
        finally:
            os.unlink(path)
    except Exception:
        return None
    return None


def phpcs_error_count(content):
    """Count phpcs ERROR-level messages in `content`, or None if phpcs isn't
    configured/available (so callers treat it as 'can't tell')."""
    if not _have(PHPCS_BIN):
        return None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".php", delete=False) as f:
            f.write(content); path = f.name
        try:
            r = subprocess.run([PHPCS_BIN, f"--standard={PHPCS_STANDARD}", "--report=json", path],
                               capture_output=True, text=True, timeout=60)
            data = json.loads(r.stdout or "{}")
            return int(data.get("totals", {}).get("errors", 0))
        finally:
            os.unlink(path)
    except Exception:
        return None


def lint_changed(read_original, changed_files):
    """Check each changed file for problems the Dev change introduced.

    read_original(path) -> the file's content on the base branch (or None if new).
    The post-edit content is read from disk by the caller-provided reader is not
    needed here; we pass the new content via `changed_files` as {path: new_content}.

    Returns a list of (path, reason) for files that have a NEW syntax error or
    MORE phpcs errors than before. Empty list = nothing the change made worse.
    """
    problems = []
    for path, new_content in changed_files.items():
        if not path.endswith(".php"):
            continue
        syn = php_syntax_error(new_content)
        if syn:
            problems.append((path, f"PHP syntax error: {syn}"))
            continue  # phpcs is meaningless on unparseable code
        after = phpcs_error_count(new_content)
        if after is None:
            continue
        base = read_original(path)
        before = phpcs_error_count(base) if base is not None else 0
        if before is not None and after > before:
            problems.append((path, f"introduced {after - before} new coding-standard error(s) "
                                   f"(phpcs {PHPCS_STANDARD}: {before} -> {after})"))
    return problems
