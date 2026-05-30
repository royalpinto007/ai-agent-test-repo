"""Client for the IOMAD test-runner service (runs on the IOMAD-LIVE box).

The runner takes a Behat feature, runs it through real Chrome via Selenium,
and returns pass/fail + screenshots (base64). Endpoint is configured via
TEST_RUNNER_URL (default points at the IOMAD-LIVE container).
"""
import json
import os
import urllib.request
import urllib.error

TEST_RUNNER_URL = os.environ.get("TEST_RUNNER_URL", "http://10.68.103.136:8090")


def runner_available():
    """True if the test-runner /health responds ok."""
    try:
        with urllib.request.urlopen(f"{TEST_RUNNER_URL}/health", timeout=5) as resp:
            return json.loads(resp.read()).get("status") == "ok"
    except Exception:
        return False


def run_behat_feature(feature_text, name="run", timeout=900):
    """POST a Gherkin feature to the runner. Returns the parsed JSON result:
    { passed, summary, screenshots: [{name, kind, b64}], output_tail } or
    { error } on failure."""
    payload = json.dumps({"name": name, "feature": feature_text}).encode()
    req = urllib.request.Request(
        f"{TEST_RUNNER_URL}/run-tests",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": f"runner HTTP {e.code}"}
    except Exception as e:
        return {"error": f"runner unreachable: {e}"}
