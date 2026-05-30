# IOMAD-LIVE — Test Instance Setup Runbook

Complete, ordered steps to build the IOMAD test instance with Behat + Selenium + headless Chrome for real browser screenshots — from a bare Ubuntu container. Every step here was executed for real; the **gotchas** boxes are the actual problems we hit and how we fixed them.

Companion doc: [IOMAD_TEST_RUNNER.md](IOMAD_TEST_RUNNER.md) (architecture + pipeline-wiring design).

---

## Target

| | |
|---|---|
| Container | `IOMAD-LIVE` @ `10.68.103.136` (LXD; **8 GB RAM / 4 CPU / ~40 GB disk**) |
| OS | Ubuntu 24.04 |
| App | IOMAD = Moodle **4.3.12**, branch `acorn_iomad_403` → needs **PHP 8.0–8.2** (NOT 8.3) |
| Source | `Health-and-Safety-Solution/iomad` (+ 19 plugin **submodules**) |

> Replace `10.68.103.136` with your container IP and `<GITHUB_TOKEN>` with a token that has read access to the org. **Do not commit a real token.**

---

## Step 1 — LAMP stack with PHP 8.2

Ubuntu 24.04 ships PHP 8.3, which Moodle 4.3 doesn't support — install 8.2 from the ondrej PPA.

```bash
apt update && apt upgrade -y
apt install -y software-properties-common
add-apt-repository -y ppa:ondrej/php
apt update

apt install -y apache2 mariadb-server git unzip \
  php8.2 libapache2-mod-php8.2 php8.2-cli \
  php8.2-mysql php8.2-curl php8.2-gd php8.2-intl php8.2-mbstring \
  php8.2-xml php8.2-zip php8.2-soap php8.2-bcmath php8.2-opcache php8.2-exif

update-alternatives --set php /usr/bin/php8.2
a2dismod php8.3 2>/dev/null; a2enmod php8.2 2>/dev/null
a2enmod rewrite
systemctl restart apache2

php -v        # must show 8.2.x
mysql --version
```

---

## Step 2 — Database

```bash
mysql <<'SQL'
CREATE DATABASE iomad DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'iomaduser'@'localhost' IDENTIFIED BY '<DB_PASSWORD>';
GRANT ALL PRIVILEGES ON iomad.* TO 'iomaduser'@'localhost';
FLUSH PRIVILEGES;
SQL
```
(Local-only DB; change the password if you like — remember it for Step 6.)

---

## Step 3 — Clone IOMAD + submodules

The IOMAD repo references ~19 plugins as **git submodules**, all private. A plain shallow clone leaves them empty (causes "Missing version.php" later).

```bash
cd /var/www/html
rm -f index.html
git clone --depth=1 --branch acorn_iomad_403 \
  https://<GITHUB_TOKEN>@github.com/Health-and-Safety-Solution/iomad.git iomad

# moodledata must be OUTSIDE the web root
mkdir -p /var/moodledata

# fetch the private submodules (inject token inline; allow root over the tree)
git config --global --add safe.directory '*'
cd /var/www/html/iomad
git -c url."https://<GITHUB_TOKEN>@github.com/".insteadOf="https://github.com/" \
  submodule update --init --recursive --jobs 4

chown -R www-data:www-data /var/www/html/iomad /var/moodledata
chmod -R 0755 /var/www/html/iomad
chmod -R 0770 /var/moodledata
```

> **Gotcha — dubious ownership:** if `git submodule` errors with "detected dubious ownership", run `git config --global --add safe.directory '*'` first (above), because the tree is owned by `www-data` but git runs as root.

---

## Step 4 — Apache vhost

```bash
cat > /etc/apache2/sites-available/iomad.conf <<'EOF'
<VirtualHost *:80>
    DocumentRoot /var/www/html/iomad
    <Directory /var/www/html/iomad>
        Options FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
    ErrorLog ${APACHE_LOG_DIR}/iomad_error.log
    CustomLog ${APACHE_LOG_DIR}/iomad_access.log combined
</VirtualHost>
EOF
a2dissite 000-default.conf
a2ensite iomad.conf
systemctl reload apache2
```

---

## Step 5 — PHP settings Moodle requires

```bash
for INI in /etc/php/8.2/cli/php.ini /etc/php/8.2/apache2/php.ini; do
  sed -i 's/^;\?max_input_vars.*/max_input_vars = 5000/' "$INI"
  sed -i 's/^post_max_size.*/post_max_size = 100M/' "$INI"
  sed -i 's/^upload_max_filesize.*/upload_max_filesize = 100M/' "$INI"
  sed -i 's/^;\?max_input_time.*/max_input_time = 600/' "$INI"
done
systemctl reload apache2
php8.2 -i | grep max_input_vars   # must show 5000
```

> **Gotcha:** the installer aborts with `max_input_vars must be at least 5000` if you skip this.

---

## Step 6 — Write config.php (file install)

```bash
sudo -u www-data php8.2 /var/www/html/iomad/admin/cli/install.php \
  --lang=en \
  --wwwroot=http://10.68.103.136 \
  --dataroot=/var/moodledata \
  --dbtype=mariadb --dbhost=localhost --dbname=iomad \
  --dbuser=iomaduser --dbpass='<DB_PASSWORD>' \
  --fullname="Acorn IOMAD Test" --shortname="iomad-test" \
  --adminuser=admin --adminpass='<ADMIN_PASSWORD>' --adminemail=admin@example.com \
  --non-interactive --agree-license
```
This writes `config.php`. If it complains `config.php already exists`, that's fine — proceed to Step 7 (it just means the file part is done).

---

## Step 7 — Install the database (+ strip defective plugins)

```bash
sudo -u www-data php8.2 /var/www/html/iomad/admin/cli/install_database.php \
  --lang=en --adminuser=admin --adminpass='<ADMIN_PASSWORD>' \
  --adminemail=admin@example.com --fullname="Acorn IOMAD Test" \
  --shortname="iomad-test" --agree-license
```

> **Gotchas — IOMAD fork-vs-core collisions.** A clean install trips on defects in forked plugins (production never re-validates them). Set each blocker aside (kept, not deleted) and re-run after **resetting the DB**:
>
> ```bash
> # reset DB between attempts:
> mysql -e "DROP DATABASE iomad; CREATE DATABASE iomad DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL PRIVILEGES ON iomad.* TO 'iomaduser'@'localhost'; FLUSH PRIVILEGES;"
> ```
>
> Plugins we had to set aside to complete the install + Behat:
>
> | Path | Error |
> |------|-------|
> | `blocks/iomad_comments` | title collides with core `comments` block |
> | `local/iomad_actionlist` | broken `install.xml` — `forms_equipments.date_removal` invalid type |
> | `auth/iomadsaml2/tests/behat` | Behat context misnamed (`behat_auth_saml2`) |
> | `admin/tool/iomadpolicy/tests/behat` | duplicate Behat step vs core `tool_policy` |
>
> Move pattern: `mkdir -p /root/iomad-disabled/<dir> && mv /var/www/html/iomad/<path> /root/iomad-disabled/<path>`. These are real upstream defects — flag to the IOMAD maintainers.

Success = `Installation completed successfully.` The site is then live at `http://10.68.103.136` (admin / `<ADMIN_PASSWORD>`).

---

## Step 8 — Behat browser stack

```bash
# Composer
cd /tmp
php -r "copy('https://getcomposer.org/installer','composer-setup.php');"
php composer-setup.php --install-dir=/usr/local/bin --filename=composer
rm composer-setup.php

# Java + Chrome
apt install -y default-jre
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb
apt install -y /tmp/chrome.deb

# Selenium 4 standalone (auto-manages chromedriver)
mkdir -p /opt/selenium
SEL_URL=$(curl -s https://api.github.com/repos/SeleniumHQ/selenium/releases/latest \
  | grep -o 'https://[^"]*selenium-server-[0-9.]*\.jar' | head -1)
wget -q "$SEL_URL" -O /opt/selenium/selenium-server.jar

# composer needs a home for www-data
mkdir -p /var/www/.config/composer /var/www/.cache/composer
chown -R www-data:www-data /var/www/.config /var/www/.cache
```

---

## Step 9 — Behat config in config.php

Add **before** the `lib/setup.php` include in `/var/www/html/iomad/config.php`:

```php
// --- Behat test environment (isolated test site) ---
$CFG->behat_wwwroot  = 'http://10.68.103.136:8000';
$CFG->behat_prefix   = 'beh_';
$CFG->behat_dataroot = '/var/behatdata';
$CFG->behat_faildump_path = '/var/behatdata/faildumps';
$CFG->behat_profiles = [
  'default' => [
    'browser' => 'chrome',
    'wd_host' => 'http://localhost:4444/wd/hub',
    'capabilities' => [
      'extra_capabilities' => [
        'goog:chromeOptions' => [
          'args' => ['--no-sandbox','--headless=new','--disable-dev-shm-usage','--disable-gpu','--window-size=1920,1080'],
        ],
      ],
    ],
  ],
];
```

```bash
mkdir -p /var/behatdata
chown -R www-data:www-data /var/behatdata
chmod -R 0777 /var/behatdata
```

> `behat_prefix` (`beh_`) and `behat_dataroot` are **separate** from the live site — Behat runs an isolated test site and never touches your installed data. `--no-sandbox` is mandatory for Chrome running as root in a container.

---

## Step 10 — Initialise Behat

```bash
cd /var/www/html/iomad
composer install --no-interaction --no-progress
chown -R www-data:www-data /var/www/html/iomad
sudo -u www-data php8.2 admin/tool/behat/cli/init.php
```
Ends with: `Acceptance tests environment enabled ... vendor/bin/behat --config /var/behatdata/behatrun/behat/behat.yml`.

> **Gotcha:** after installing/removing ANY plugin you must re-run `admin/tool/behat/cli/init.php` (not just `util.php --enable`), or Behat errors with "test environment was initialised for a different version".

---

## Step 11 — Screenshot-on-demand helper plugin

Core Behat only screenshots on *failure*. This adds a step to capture during *passing* tests.

```bash
PLUGDIR=/var/www/html/iomad/local/pipelinetest
mkdir -p $PLUGDIR/tests/behat $PLUGDIR/lang/en

cat > $PLUGDIR/version.php <<'EOF'
<?php
defined('MOODLE_INTERNAL') || die();
$plugin->component = 'local_pipelinetest';
$plugin->version   = 2026013000;
$plugin->requires  = 2023100900;
$plugin->maturity  = MATURITY_STABLE;
$plugin->release   = '1.0';
EOF

cat > $PLUGDIR/lang/en/local_pipelinetest.php <<'EOF'
<?php
$string['pluginname'] = 'Pipeline Test Helper';
EOF

cat > $PLUGDIR/tests/behat/behat_local_pipelinetest.php <<'EOF'
<?php
require_once(__DIR__ . '/../../../../lib/behat/behat_base.php');

class behat_local_pipelinetest extends behat_base {
    /**
     * @Then /^I capture the screen as "([^"]*)"$/
     */
    public function i_capture_the_screen_as($name) {
        $dir = '/var/behatdata/shots';
        if (!is_dir($dir)) { mkdir($dir, 0777, true); }
        $png = $this->getSession()->getScreenshot();
        $safe = preg_replace('/[^a-zA-Z0-9_-]/', '_', $name);
        file_put_contents($dir . '/' . $safe . '.png', $png);
    }
}
EOF

chown -R www-data:www-data $PLUGDIR

# install plugin, then re-init behat
cd /var/www/html/iomad
sudo -u www-data php8.2 admin/cli/upgrade.php --non-interactive
sudo -u www-data php8.2 admin/tool/behat/cli/init.php
```

Usage in any scenario: `And I capture the screen as "step-name"` → `/var/behatdata/shots/step-name.png`.

---

## Step 12 — systemd services (reboot-proof)

```bash
cat > /etc/systemd/system/selenium.service <<'EOF'
[Unit]
Description=Selenium Standalone (Behat browser driver)
After=network.target
[Service]
Type=simple
ExecStart=/usr/bin/java -jar /opt/selenium/selenium-server.jar standalone --port 4444
Restart=on-failure
RestartSec=5
User=root
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/behat-webserver.service <<'EOF'
[Unit]
Description=Behat test-site PHP server (port 8000)
After=network.target
[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/html/iomad
ExecStart=/usr/bin/php8.2 -S 10.68.103.136:8000 -t /var/www/html/iomad
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now selenium.service behat-webserver.service
```

Verify:
```bash
systemctl is-active selenium.service behat-webserver.service   # active active
curl -s http://localhost:4444/status | grep -o '"ready":[^,]*'  # ready:true
curl -s -o /dev/null -w "%{http_code}\n" http://10.68.103.136:8000/   # 303
```

---

## Step 13 — Run a test

```bash
cd /var/www/html/iomad
sudo -u www-data php8.2 vendor/bin/behat \
  --config /var/behatdata/behatrun/behat/behat.yml \
  --tags=@local_pipelinetest

ls /var/behatdata/shots/      # on-demand screenshots
ls /var/behatdata/faildumps/  # failure screenshots + HTML
```
Expected: `1 scenario (1 passed)` + `homepage.png` in `shots/`.

Run any feature by tag (`--tags=@x`), scenario name (`--name="..."`), or path.

---

## Reference

- **Admin:** `admin` / `<ADMIN_PASSWORD>` at `http://10.68.103.136`
- **DB:** `iomad` / `iomaduser` / (password set in Step 2) — local only
- **Disabled plugins:** `/root/iomad-disabled/` + `STRIPPED.txt` (4 entries — see Step 7)
- **Behat config:** `/var/behatdata/behatrun/behat/behat.yml`
- **Screenshots:** `/var/behatdata/shots/` (on demand), `/var/behatdata/faildumps/` (on failure)
- **Services:** `selenium.service`, `behat-webserver.service`
- **After any plugin change:** re-run `admin/tool/behat/cli/init.php`

### Security note
The GitHub token used for cloning must be kept out of this file (placeholder `<GITHUB_TOKEN>`). Use a token scoped to `repo` only. The DB and admin passwords here are for a local, non-public test box — change them for any exposed deployment.
