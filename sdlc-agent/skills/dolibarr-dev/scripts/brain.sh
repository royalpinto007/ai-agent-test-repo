#!/usr/bin/env bash
# brain.sh — per-module "BRAIN": a durable record of WHAT each module's users
# demanded, WHY it was built that way, which scenarios were considered, and
# whether the user ended up satisfied. The brain lives INSIDE the module
# (htdocs/custom/<module>/.dolibarr-dev/BRAIN.md) so it travels with the code and
# git history, and a later session can continue WITHOUT re-deriving intent or
# repeating a missed scenario (the "multiple boxes" lesson).
#
# Read it FIRST (Step 0). Update it at PLAN time and BEFORE confirming "done".
# It is a record of INTENT — always verify a claim here against the live code
# before acting on it.
#
# Usage:
#   brain.sh path [module]    print the brain file path (resolves module from $PWD)
#   brain.sh show [module]    print the brain (or tell you to init it)
#   brain.sh init [module]    create the brain from a template if missing (NEVER overwrites)
#   brain.sh list             list every custom module and whether it already has a brain
#
# module defaults to the basename of $PWD when under htdocs/custom; else pass it.
# root defaults to $DOL_HTDOCS or /var/www/html/dolibarr-20/htdocs
set -u

ROOT="${DOL_HTDOCS:-/var/www/html/dolibarr-20/htdocs}"
CUSTOM="$ROOT/custom"
BRAIN_REL=".dolibarr-dev/BRAIN.md"

resolve_module() {
  local m="${1:-}"
  if [ -z "$m" ]; then
    case "$PWD" in "$CUSTOM"/*) m="$(basename "$PWD")";; esac
  fi
  [ -n "$m" ] || { echo "ERROR: pass a module name (or run from inside htdocs/custom/<module>)" >&2; exit 2; }
  [ -d "$CUSTOM/$m" ] || { echo "ERROR: module dir not found: $CUSTOM/$m" >&2; exit 2; }
  echo "$m"
}

brain_path() { echo "$CUSTOM/$1/$BRAIN_REL"; }

write_template() {
  local m="$1" f="$2" today
  today="$(date +%F)"
  mkdir -p "$(dirname "$f")"
  cat > "$f" <<EOF
# $m — module brain

> Per-module memory for the dolibarr-dev skill. Records WHAT users demanded, WHY
> it was built this way, which scenarios were considered, and whether the user is
> satisfied — so a later session continues without re-deriving intent or repeating
> a missed scenario. READ this first; UPDATE it at plan time and before confirming.
> Everything here is INTENT — verify against the live code before acting on it.

## Purpose
<!-- One paragraph: what this module is for, which business role/flow it serves. -->
TODO: describe the module's purpose.

## Architecture & durable decisions
<!-- The design choices a newcomer must know, each with WHY. -->
- TODO: e.g. "Abstract base + factory so a new provider is one subclass + a logo file."

## Requirements log
<!-- Newest first. One block per distinct user demand. -->

### $today — TODO short title of the demand
- **Demand (user's words):** TODO
- **Persona / flow:** TODO (sales / finance / warehouse / logistics; which document/step)
- **Decision (what we built + which mechanism + WHY):** TODO (hook/trigger/extrafield/table/const + reason)
- **Scenarios considered:**
  - Handled: TODO
  - Deferred (revisit): TODO
  - Out of scope (why): TODO
- **Files touched:** TODO
- **Status:** built | verified | user-confirmed-satisfied | open
- **Follow-ups / open questions:** TODO

## Known gaps / deferred scenarios
<!-- The "multiple boxes" backlog: things knowingly not done yet, so they aren't forgotten. -->
- TODO
EOF
}

cmd="${1:-}"; shift || true
case "$cmd" in
  path)
    M="$(resolve_module "${1:-}")" || exit $?
    brain_path "$M"
    ;;
  show)
    M="$(resolve_module "${1:-}")" || exit $?
    F="$(brain_path "$M")"
    if [ -f "$F" ]; then
      echo "## brain: ${F#$ROOT/}"
      echo
      cat "$F"
    else
      echo "No brain yet for '$M'."
      echo "Create it:  bash \$0 init $M   (then edit ${F#$ROOT/})"
    fi
    ;;
  init)
    M="$(resolve_module "${1:-}")" || exit $?
    F="$(brain_path "$M")"
    if [ -f "$F" ]; then
      echo "Brain already exists (not overwritten): ${F#$ROOT/}"
      exit 0
    fi
    write_template "$M" "$F"
    echo "Created brain template: ${F#$ROOT/}"
    echo "Now fill in Purpose / Architecture / the first Requirements-log entry."
    ;;
  list)
    echo "## Custom modules and their brain status:"
    if [ -d "$CUSTOM" ]; then
      for d in "$CUSTOM"/*/; do
        [ -d "$d" ] || continue
        m="$(basename "$d")"
        if [ -f "$d$BRAIN_REL" ]; then
          printf '  [brain]    %s\n' "$m"
        else
          printf '  [no brain] %s\n' "$m"
        fi
      done
    else
      echo "  (no custom/ dir at $CUSTOM)"
    fi
    ;;
  *)
    grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
