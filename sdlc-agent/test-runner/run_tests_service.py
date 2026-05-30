"""
IOMAD test-runner service — runs on the IOMAD-LIVE box (10.68.103.136).

Given a Behat feature (Gherkin text), it:
  1. writes the feature into the local_pipelinetest suite with a unique tag
  2. runs Behat for just that tag (real Chrome via Selenium)
  3. collects screenshots (on-demand from /var/behatdata/shots + failure dumps)
  4. returns pass/fail + screenshots (base64) + output tail

Single concurrent run only (the Behat test site is shared). Listens on :8090.

Deploy: /opt/test-runner/run_tests_service.py, run as www-data via systemd.
See IOMAD_TEST_RUNNER.md for the wider design.
"""
import base64
import glob
import os
import re
import subprocess
import threading
import time

from flask import Flask, request, jsonify

app = Flask(__name__)

IOMAD_DIR    = "/var/www/html/iomad"
BEHAT_DIR    = f"{IOMAD_DIR}/local/pipelinetest/tests/behat"
BEHAT_CONFIG = "/var/behatdata/behatrun/behat/behat.yml"
SHOTS_DIR    = "/var/behatdata/shots"
FAILDUMP_DIR = "/var/behatdata/faildumps"
PHP          = "/usr/bin/php8.2"
RUN_TIMEOUT  = 900  # seconds

# Moodle's behat.yml enumerates specific feature FILES at init time, not dirs,
# so a brand-new .feature is NOT discovered without a slow re-init. Instead we
# overwrite this already-registered file with each run's content (behat reads
# file contents at run time) and restore the default afterwards.
REGISTERED_FEATURE = f"{BEHAT_DIR}/proof.feature"
DEFAULT_PROOF = (
    "@local @local_pipelinetest @javascript\n"
    "Feature: Pipeline screenshot proof\n"
    "  Scenario: Capture the IOMAD front page\n"
    "    Given I am on site homepage\n"
    '    Then I should see "Acceptance test site"\n'
    '    And I capture the screen as "homepage"\n'
)

_lock = threading.Lock()


def _collect_pngs(since_ts):
    """Base64 every PNG created at/after since_ts, from shots + faildumps."""
    paths = sorted(glob.glob(f"{SHOTS_DIR}/*.png")) + \
            sorted(glob.glob(f"{FAILDUMP_DIR}/**/*.png", recursive=True))
    shots = []
    for path in paths:
        try:
            if os.path.getmtime(path) >= since_ts - 1:
                with open(path, "rb") as fh:
                    shots.append({
                        "name": os.path.basename(path),
                        "kind": "ondemand" if SHOTS_DIR in path else "failure",
                        "b64": base64.b64encode(fh.read()).decode(),
                    })
        except OSError:
            pass
    return shots


@app.route("/health")
def health():
    return jsonify({"status": "ok", "busy": _lock.locked()})


@app.route("/run-tests", methods=["POST"])
def run_tests():
    data = request.get_json(silent=True) or {}
    feature = (data.get("feature") or "").strip()
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", data.get("name", "run"))[:40] or "run"

    if not feature:
        return jsonify({"error": "feature (gherkin text) is required"}), 400
    if "Feature:" not in feature:
        return jsonify({"error": "feature must contain a 'Feature:' line"}), 400

    if not _lock.acquire(blocking=False):
        return jsonify({"error": "another test run is in progress, retry shortly"}), 409

    try:
        run_id = f"{name}_{int(time.time())}"
        # drop any leading tag lines the caller included; we use the stable
        # component tag (proof.feature is the only feature carrying it, and the
        # lock serialises runs, so a per-run tag isn't needed — and dynamic tags
        # were found not to match reliably).
        lines = feature.splitlines()
        while lines and lines[0].lstrip().startswith("@"):
            lines.pop(0)
        full = "@local @local_pipelinetest @javascript\n" + "\n".join(lines).rstrip() + "\n"

        # overwrite the registered feature file (its path is in behat.yml)
        with open(REGISTERED_FEATURE, "w") as fh:
            fh.write(full)

        # clear prior on-demand shots so we return only this run's captures
        for p in glob.glob(f"{SHOTS_DIR}/*.png"):
            try:
                os.remove(p)
            except OSError:
                pass

        start = time.time()
        try:
            proc = subprocess.run(
                [PHP, "vendor/bin/behat", "--config", BEHAT_CONFIG, "--tags", "@local_pipelinetest"],
                cwd=IOMAD_DIR, capture_output=True, text=True, timeout=RUN_TIMEOUT,
            )
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return jsonify({"error": f"behat run exceeded {RUN_TIMEOUT}s"}), 504

        # parse "N scenario(s) (... passed/failed ...)"
        m = re.search(r"(\d+)\s+scenarios?\s*\(([^)]*)\)", out)
        detail = m.group(2) if m else ""
        passed = bool(m) and "passed" in detail and "failed" not in detail
        summary = m.group(0) if m else "no scenario summary found (likely an error before run)"

        return jsonify({
            "run_id": run_id,
            "passed": passed,
            "summary": summary,
            "screenshots": _collect_pngs(start),
            "output_tail": out[-3000:],
        })
    finally:
        # restore the registered feature to a known-good default
        try:
            with open(REGISTERED_FEATURE, "w") as fh:
                fh.write(DEFAULT_PROOF)
        except OSError:
            pass
        _lock.release()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090)
