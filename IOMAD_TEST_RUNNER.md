# IOMAD Test Runner — Real Browser Screenshots for the Pipeline

How the IOMAD test instance produces **real screenshots and pass/fail evidence** by driving the actual application with Behat + Selenium + headless Chrome — and the design for wiring it into the SDLC agent pipeline.

Status: **infrastructure proven and working.** Pipeline wiring is the remaining build (see end).

---

## The test instance

| | |
|---|---|
| Container | `IOMAD-LIVE` @ **10.68.103.136** (LXD, 8 GB / 4 CPU / ~40 GB disk) |
| Stack | Ubuntu 24.04, PHP 8.2, MariaDB 10.11, Apache |
| App | IOMAD (Moodle 4.3.12, branch `acorn_iomad_403`) at `http://10.68.103.136` |
| DB | `iomad` / user `iomaduser` (local-only) |
| Admin login | `admin` / `AdminPass#2026` |
| moodledata | `/var/moodledata` |
| Code | `/var/www/html/iomad` (cloned from `Health-and-Safety-Solution/iomad` + 19 plugin submodules) |

### Behat / browser-automation layer

| | |
|---|---|
| Behat config | added to `config.php`: `behat_wwwroot=http://10.68.103.136:8000`, `behat_prefix=beh_`, `behat_dataroot=/var/behatdata` |
| Browser profile | headless Chrome via Selenium (`--no-sandbox --headless=new --disable-dev-shm-usage`) — in `$CFG->behat_profiles` |
| Selenium | `/opt/selenium/selenium-server.jar` (v4, auto-manages chromedriver), port 4444 |
| Test-site PHP server | `php -S 10.68.103.136:8000 -t /var/www/html/iomad` |
| Behat run config | `/var/behatdata/behatrun/behat/behat.yml` |
| Failure screenshots | auto-dumped to `/var/behatdata/faildumps/<timestamp>/` (PNG + HTML) |
| On-demand screenshots | `/var/behatdata/shots/<name>.png` via the custom step below |

### Custom helper plugin: `local_pipelinetest`

Installed at `/var/www/html/iomad/local/pipelinetest`. Provides a Behat step to capture a screenshot at **any** point in a passing scenario (core only screenshots on failure):

```gherkin
And I capture the screen as "some-name"
```
→ writes `/var/behatdata/shots/some-name.png`.

---

## Plugins set aside to get a clean install + test env

IOMAD's forked components collide with Moodle core in a clean install / test harness (duplicate identifiers). These were moved to `/root/iomad-disabled/` (recoverable) and logged in `/root/iomad-disabled/STRIPPED.txt`:

| Plugin / path | Problem |
|---------------|---------|
| `blocks/iomad_comments` | Block title collides with core `comments` block |
| `local/iomad_actionlist` | Broken `db/install.xml` — `forms_equipments.date_removal` invalid column type |
| `auth/iomadsaml2/tests/behat` | Behat context class misnamed (`behat_auth_saml2` vs expected `behat_auth_iomadsaml2`) |
| `admin/tool/iomadpolicy/tests/behat` | Duplicate Behat step definition vs core `tool_policy` (`the following policies exist`) |

**These are real defects worth raising with the IOMAD maintainers** — they break clean installs and any automated testing. The first two block installation entirely; the last two block Behat. Production presumably never re-runs these (it grew via upgrades), which is why it doesn't hit them.

---

## Running a test manually (the proven flow)

```bash
# 1. ensure services are up
pgrep -f selenium-server >/dev/null || \
  java -jar /opt/selenium/selenium-server.jar standalone --port 4444 >/var/behatdata/selenium.log 2>&1 &
curl -s -o /dev/null -w "%{http_code}\n" http://10.68.103.136:8000/ || \
  sudo -u www-data php8.2 -S 10.68.103.136:8000 -t /var/www/html/iomad >/var/behatdata/phpserver.log 2>&1 &

# 2. run a feature (by tag, name, or path)
cd /var/www/html/iomad
sudo -u www-data php8.2 vendor/bin/behat \
  --config /var/behatdata/behatrun/behat/behat.yml \
  --tags=@local_pipelinetest

# 3. collect evidence
ls /var/behatdata/shots/        # on-demand screenshots
ls /var/behatdata/faildumps/    # failure screenshots + HTML
```

A passing run looks like `1 scenario (1 passed)` and drops PNGs in `/var/behatdata/shots/`.

### After adding/removing a plugin or feature
Behat must be re-initialised so suites/contexts regenerate:
```bash
cd /var/www/html/iomad
sudo -u www-data php8.2 admin/tool/behat/cli/init.php
```

### Key environment fixes applied (for rebuilds)
- PHP: `max_input_vars = 5000`, `post_max_size=100M`, `upload_max_filesize=100M`, `max_input_time=600` (both CLI + Apache `php.ini`)
- Composer needs a home for `www-data`: `/var/www/.config/composer` + `/var/www/.cache/composer` owned by `www-data`
- `git config --global --add safe.directory '*'` (submodule operations as root over a www-data-owned tree)

---

## Pipeline wiring — the remaining build

Goal: turn QA's "Not verifiable" rows into **real Pass/Fail + screenshots** by running Behat for each PR.

### Architecture

```
Dev agent produces code change + PR (on the IOMAD agent box, 10.68.103.242)
        │
        ▼  (new pipeline stage)
Test runner on the IOMAD-LIVE box (10.68.103.136):
  1. install the PR's plugin code into /var/www/html/iomad (git fetch + checkout the branch
     into the right plugin dir; run upgrade.php; behat init)
  2. Dev agent writes a focused .feature from the BA test cases
     (use local_pipelinetest's "I capture the screen as" at key steps)
  3. run Behat for that feature
  4. collect /var/behatdata/shots/*.png + faildumps + pass/fail summary
        │
        ▼
Screenshots attached to the GitHub issue (GitHub API supports image upload via a
  comment with an uploaded asset, or push to a static path and link)
        │
        ▼
QA stage reads the real results → Test Report rows become Pass/Fail with image evidence
```

### Components to build

1. **`/run-tests` endpoint** (a small Flask service on `10.68.103.136`, mirroring the sdlc-agent pattern):
   - input: `{ owner, repo, branch, feature_text, plugin_path }`
   - installs the branch, writes `feature_text` into `local/pipelinetest/tests/behat/<id>.feature`, runs Behat, returns `{ passed, failed, screenshots: [paths], summary }`
   - returns screenshot bytes (base64) or a URL

2. **PR-install script** — fetch the PR branch, place it at the correct plugin path, `upgrade.php --non-interactive`, `behat init`. Reset between runs (drop `beh_` prefix tables / re-init).

3. **Focused-feature generation** — the Dev (or a new Test) agent converts BA/SA test cases into a Behat `.feature`, inserting `I capture the screen as "..."` at the points worth showing. Focused scenarios avoid most core-vs-fork step collisions.

4. **n8n node + GitHub delivery** — call `/run-tests` after Dev, upload screenshots to the issue, feed results into the QA prompt (the QA `Test Report` section already exists — wire real results in instead of "Not verifiable").

### Honest scope / caveats
- ~2–4 days of plumbing; most is one-time (install script + endpoint).
- The 4 stripped plugins can't be tested until their defects are fixed upstream.
- The Behat **test site is isolated** (separate DB/dataroot) — scenarios must create their own companies/users/courses via Behat generator steps (IOMAD provides some; complex multi-tenant setups need step work).
- Resource: Behat + Chrome + the running app fit in 8 GB for single runs; concurrent runs would need more.

### Services as systemd (for a permanent setup)
Currently Selenium and the :8000 server are started manually in the background. For production, wrap both as systemd units so they survive reboots and the runner can rely on them.
