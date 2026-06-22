#!/usr/bin/env bash
# dol-log.sh — read-only access to the Dolibarr syslog file. Resolves the log
# path from conf/conf.php (dolibarr_main_data_root) + the SYSLOG_FILE const, so
# it works regardless of where the data dir lives. Use this to DEBUG what your
# hook/trigger/API code actually did at runtime.
#
# Usage:
#   dol-log.sh path             print resolved log path + current SYSLOG_LEVEL (warns if too low)
#   dol-log.sh tail [n]         show last n lines (default 80)
#   dol-log.sh follow [grep]    tail -f the log (optional case-insensitive grep filter)
#   dol-log.sh grep <pat> [n]   search the last n lines (default 200000) for a pattern
#
# WHY level matters: Dolibarr levels are LOG_DEBUG=7, LOG_INFO=6, LOG_WARNING=4,
# LOG_ERR=3. dol_syslog(...) defaults to LOG_INFO; many API/debug traces use
# LOG_DEBUG. If SYSLOG_LEVEL < the message level, the line is NEVER written.
# To see DEBUG traces, raise it: Home > Setup > Modules > Logs, or
#   dol-db.sh is read-only — set via UI, or UPDATE llx_const SET value='7' WHERE name='SYSLOG_LEVEL'.
# The log file can be huge (GBs): this script always tails, never cats.
set -u

HTDOCS="${DOL_HTDOCS:-/var/www/html/dolibarr-20/htdocs}"
CONF="$HTDOCS/conf/conf.php"
[ -f "$CONF" ] || { echo "ERROR: conf.php not found at $CONF (set DOL_HTDOCS)" >&2; exit 2; }

read_conf() { php -r "include '$CONF'; echo \$$1;" 2>/dev/null; }
DATA="$(read_conf dolibarr_main_data_root)"
[ -n "$DATA" ] || DATA="$HTDOCS/../documents"

# SYSLOG_FILE const may contain the literal token DOL_DATA_ROOT; substitute it.
DBH="$(read_conf dolibarr_main_db_host)"; DBN="$(read_conf dolibarr_main_db_name)"
DBU="$(read_conf dolibarr_main_db_user)"; DBP="$(read_conf dolibarr_main_db_pass)"
PFX="$(read_conf dolibarr_main_db_prefix)"; PFX="${PFX:-llx_}"
dbq() { mysql -h"$DBH" -u"$DBU" -p"$DBP" "$DBN" -N -e "$1" 2>/dev/null; }

SYSLOG_FILE="$(dbq "SELECT value FROM ${PFX}const WHERE name='SYSLOG_FILE' LIMIT 1;")"
LEVEL="$(dbq "SELECT value FROM ${PFX}const WHERE name='SYSLOG_LEVEL' LIMIT 1;")"
if [ -n "$SYSLOG_FILE" ]; then
  LOG="${SYSLOG_FILE/DOL_DATA_ROOT/$DATA}"
else
  LOG="$DATA/dolibarr.log"
fi

cmd="${1:-}"; shift || true
case "$cmd" in
  path)
    echo "log:   $LOG"
    [ -f "$LOG" ] && echo "size:  $(du -h "$LOG" 2>/dev/null | cut -f1)" || echo "size:  (file does not exist yet)"
    echo "level: ${LEVEL:-?} (7=DEBUG 6=INFO 4=WARNING 3=ERR)"
    if [ -n "$LEVEL" ] && [ "$LEVEL" -lt 7 ] 2>/dev/null; then
      echo "NOTE:  LOG_DEBUG traces are NOT written at level $LEVEL. Raise SYSLOG_LEVEL to 7 to see API/debug lines."
    fi
    ;;
  tail)
    N="${1:-80}"; [ -f "$LOG" ] || { echo "log not found: $LOG" >&2; exit 2; }
    tail -n "$N" "$LOG"
    ;;
  follow)
    G="${1:-}"; [ -f "$LOG" ] || { echo "log not found: $LOG" >&2; exit 2; }
    if [ -n "$G" ]; then tail -f "$LOG" | grep --line-buffered -i "$G"; else tail -f "$LOG"; fi
    ;;
  grep)
    PAT="${1:-}"; N="${2:-200000}"
    [ -n "$PAT" ] || { echo "usage: dol-log.sh grep <pattern> [n]" >&2; exit 2; }
    [ -f "$LOG" ] || { echo "log not found: $LOG" >&2; exit 2; }
    tail -n "$N" "$LOG" | grep -i "$PAT" | tail -n 100
    ;;
  *)
    grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
