#!/usr/bin/env bash
# scan-code.sh — extract hook contexts, hook method points, and trigger action
# codes from a Dolibarr codebase. Use this to discover the EXACT names that
# already exist in the code instead of guessing them.
#
# Usage:
#   scan-code.sh hooks    [root]            list hook contexts + method points (with counts)
#   scan-code.sh triggers [root] [filter]   list trigger action codes (optional substring filter, e.g. BILL)
#   scan-code.sh find     <keyword> [root]  show file:line where a context/method/trigger code is used
#   scan-code.sh modules  [root]            list custom modules + their descriptor classes
#   scan-code.sh find-api <symbol> [root]   find where a function/class/method is DEFINED + sample usages
#                                           (use before writing logic, to reuse the Dolibarr-native API)
#   scan-code.sh funcs    [module]          INVENTORY every function/method already written in a module
#                                           (REUSE FIRST: scan & record what exists before writing new code;
#                                            copy/modify an existing one instead of reinventing)
#
# root defaults to $DOL_HTDOCS or /var/www/html/dolibarr-20/htdocs
# NB: no `set -e`/`pipefail` — recursive grep can exit non-zero on unreadable
# files even when it found matches; we want partial results, not an abort.
set -u

DEFAULT_ROOT="${DOL_HTDOCS:-/var/www/html/dolibarr-20/htdocs}"

cmd="${1:-}"; shift || true

resolve_root() {
  local r="${1:-$DEFAULT_ROOT}"
  [ -d "$r" ] || { echo "ERROR: htdocs root not found: $r" >&2; exit 2; }
  echo "$r"
}

case "$cmd" in
  hooks)
    ROOT="$(resolve_root "${1:-}")"
    echo "## Hook CONTEXTS (initHooks(array('...'))) — used by pages; register these in your module descriptor module_parts['hooks']"
    grep -rohE "initHooks\(\s*array\(([^)]*)\)" --include='*.php' "$ROOT" 2>/dev/null \
      | grep -oE "'[a-zA-Z0-9_]+'" | tr -d "'" | sort | uniq -c | sort -rn | head -60
    echo
    echo "## Hook METHOD points (executeHooks('method',...)) — implement these in your actions_<module>.class.php"
    grep -rohE "executeHooks\(\s*'([a-zA-Z0-9_]+)'" --include='*.php' "$ROOT" 2>/dev/null \
      | sed -E "s/.*'([a-zA-Z0-9_]+)'/\1/" | sort | uniq -c | sort -rn | head -60
    ;;
  triggers)
    ROOT="$(resolve_root "${1:-}")"; FILTER="${2:-}"
    echo "## Trigger ACTION CODES (call_trigger('CODE')) — handle these in your interface_NN_modX_Y.class.php runTrigger() switch"
    codes=$(grep -rohE "call_trigger\(\s*[\"']([A-Z0-9_]+)[\"']" --include='*.php' "$ROOT" 2>/dev/null \
      | sed -E "s/.*[\"']([A-Z0-9_]+)[\"'].*/\1/" | sort -u)
    if [ -n "$FILTER" ]; then
      echo "(filtered by: $FILTER)"
      echo "$codes" | grep -i "$FILTER" || echo "(no codes match '$FILTER')"
    else
      echo "$codes"
      echo "---"
      echo "total distinct codes: $(echo "$codes" | grep -c .)"
    fi
    ;;
  find)
    KW="${1:-}"; [ -n "$KW" ] || { echo "usage: scan-code.sh find <keyword> [root]" >&2; exit 2; }
    ROOT="$(resolve_root "${2:-}")"
    echo "## Occurrences of '$KW' in hook/trigger call sites:"
    grep -rnE "executeHooks\([^)]*$KW|initHooks\([^)]*$KW|call_trigger\([^)]*$KW" --include='*.php' "$ROOT" 2>/dev/null | head -60 || true
    ;;
  find-api)
    NAME="${1:-}"; [ -n "$NAME" ] || { echo "usage: scan-code.sh find-api <symbol> [root]" >&2; exit 2; }
    ROOT="$(resolve_root "${2:-}")"
    echo "## DEFINITIONS of '$NAME' (function / class / method) — reuse these instead of reinventing:"
    grep -rnE "(function|class|interface|trait)\s+$NAME\b" --include='*.php' "$ROOT" 2>/dev/null | head -25
    echo
    echo "## Sample USAGES of '$NAME' (how Dolibarr core calls it):"
    grep -rnE "\b$NAME\s*\(" --include='*.php' "$ROOT" 2>/dev/null | grep -vE "function\s+$NAME" | head -25
    ;;
  funcs)
    MOD="${1:-}"
    ROOT="$DEFAULT_ROOT"
    if [ -z "$MOD" ]; then
      case "$PWD" in "$ROOT"/custom/*) MOD="$(basename "$PWD")";; esac
    fi
    [ -n "$MOD" ] || { echo "usage: scan-code.sh funcs <module> (or run from inside htdocs/custom/<module>)" >&2; exit 2; }
    D="$ROOT/custom/$MOD"
    [ -d "$D" ] || { echo "ERROR: module dir not found: $D" >&2; exit 2; }
    echo "## Functions/methods ALREADY WRITTEN in custom/$MOD — reuse/copy/modify these before writing new code:"
    grep -rnE '^\s*(public|private|protected|static|abstract|final|\s)*\s*function\s+&?\s*[a-zA-Z_]' --include='*.php' "$D" 2>/dev/null \
      | sed -E "s#^$ROOT/##" \
      | sed -E 's/\s*\{?\s*$//' \
      | sed -E 's/^([^:]+:[0-9]+):\s*/\1\t/' \
      | sort
    echo
    echo "## Classes defined in custom/$MOD:"
    grep -rnE '^\s*(abstract\s+|final\s+)?class\s+[A-Za-z_]' --include='*.php' "$D" 2>/dev/null | sed -E "s#^$ROOT/##" | sort
    ;;
  modules)
    ROOT="$(resolve_root "${1:-}")"
    echo "## Custom modules under $ROOT/custom:"
    if [ -d "$ROOT/custom" ]; then
      find "$ROOT/custom" -maxdepth 3 -path '*/core/modules/mod*.class.php' 2>/dev/null | sort | while read -r f; do
        rel="${f#$ROOT/}"; echo "  $rel"
      done
    else
      echo "  (no custom/ dir)"
    fi
    ;;
  *)
    grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
