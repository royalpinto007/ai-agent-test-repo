#!/usr/bin/env bash
# dol-db.sh — read-only access to the Dolibarr database. Credentials are parsed
# from conf/conf.php (never hard-coded). Use this to inspect schema and config
# before/while developing.
#
# Usage:
#   dol-db.sh modules            list enabled modules (MAIN_MODULE_* = 1)
#   dol-db.sh const <like>       show consts whose name matches LIKE pattern (e.g. DOLIBARRBOAT%)
#   dol-db.sh tables [like]      list tables (optional LIKE on name, e.g. %facture%)
#   dol-db.sh describe <table>   show columns of a table (prefix optional; llx_ auto-added)
#   dol-db.sh query "<SQL>"      run a read-only SELECT/SHOW/DESCRIBE (mutations blocked)
#
# conf.php location defaults to $DOL_HTDOCS/conf/conf.php
# ($DOL_HTDOCS defaults to /var/www/html/dolibarr-20/htdocs)
set -u

HTDOCS="${DOL_HTDOCS:-/var/www/html/dolibarr-20/htdocs}"
CONF="$HTDOCS/conf/conf.php"
[ -f "$CONF" ] || { echo "ERROR: conf.php not found at $CONF (set DOL_HTDOCS)" >&2; exit 2; }

read_conf() { php -r "include '$CONF'; echo \$$1;" 2>/dev/null; }
DBH="$(read_conf dolibarr_main_db_host)"
DBN="$(read_conf dolibarr_main_db_name)"
DBU="$(read_conf dolibarr_main_db_user)"
DBP="$(read_conf dolibarr_main_db_pass)"
PFX="$(read_conf dolibarr_main_db_prefix)"
PFX="${PFX:-llx_}"

run() { mysql -h"$DBH" -u"$DBU" -p"$DBP" "$DBN" -N -e "$1" 2>/dev/null; }

cmd="${1:-}"; shift || true
case "$cmd" in
  modules)
    run "SELECT name FROM ${PFX}const WHERE name LIKE 'MAIN_MODULE_%' AND value='1' ORDER BY name;"
    ;;
  const)
    LIKE="${1:-%}"
    run "SELECT name, LEFT(value,200) FROM ${PFX}const WHERE name LIKE '$LIKE' ORDER BY name;"
    ;;
  tables)
    LIKE="${1:-}"
    if [ -n "$LIKE" ]; then run "SHOW TABLES LIKE '$LIKE';"; else run "SHOW TABLES;"; fi
    ;;
  describe)
    T="${1:-}"; [ -n "$T" ] || { echo "usage: dol-db.sh describe <table>" >&2; exit 2; }
    case "$T" in ${PFX}*) : ;; *) T="${PFX}${T}";; esac
    run "DESCRIBE $T;"
    ;;
  query)
    SQL="${1:-}"; [ -n "$SQL" ] || { echo "usage: dol-db.sh query \"<SQL>\"" >&2; exit 2; }
    if echo "$SQL" | grep -qiE '\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|GRANT)\b'; then
      echo "BLOCKED: only read-only SELECT/SHOW/DESCRIBE allowed." >&2; exit 3
    fi
    run "$SQL"
    ;;
  *)
    grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
