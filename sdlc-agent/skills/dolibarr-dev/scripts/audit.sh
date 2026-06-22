#!/usr/bin/env bash
# audit.sh — audit a custom module before confirming it "done":
#   1) security  — flag risky patterns (SQLi / XSS / CSRF / access / unsafe calls)
#   2) deadcode  — list functions/methods defined in the module that look UNUSED
#   3) files     — list module files that nothing else references (candidate dead files)
#
# Usage:
#   audit.sh security [module]    scan module PHP for risky patterns (advisory, manual review)
#   audit.sh deadcode [module]    list defined funcs/methods with no caller in the codebase
#   audit.sh files    [module]    list .php/.tpl files not referenced anywhere else
#   audit.sh all      [module]    run all three
#
# module defaults to the basename of $PWD if it's under htdocs/custom; else pass it.
# root defaults to $DOL_HTDOCS or /var/www/html/dolibarr-20/htdocs
#
# These are GREP HEURISTICS, not a compiler. deadcode/files WILL produce false
# positives for code called dynamically by core: hook method points
# (doActions, formObjectOptions, addMoreActionsButtons, printCommonFooter,
# getNomUrl, printFieldListValue, ...), trigger runTrigger(), REST API methods,
# __construct/__get/__call magic, and callbacks. Verify each candidate before
# deleting. The point is to make you LOOK at every line, not to auto-delete.
set -u

ROOT="${DOL_HTDOCS:-/var/www/html/dolibarr-20/htdocs}"
CUSTOM="$ROOT/custom"

resolve_module() {
  local m="${1:-}"
  if [ -z "$m" ]; then
    case "$PWD" in "$CUSTOM"/*) m="$(basename "$PWD")";; esac
  fi
  [ -n "$m" ] || { echo "ERROR: pass a module name (or run from inside htdocs/custom/<module>)" >&2; exit 2; }
  [ -d "$CUSTOM/$m" ] || { echo "ERROR: module dir not found: $CUSTOM/$m" >&2; exit 2; }
  echo "$m"
}

# core hook method points + framework overrides that core calls by name (variable
# dispatch), so a missing static caller does NOT mean they are dead.
DISPATCHED='^(runTrigger|getName|getDesc|doActions|doMassActions|formObjectOptions|formConfirm|addMoreActionsButtons|addMoreMassActions|printCommonFooter|printTopRightMenu|printLeftBlock|getNomUrl|printFieldListValue|printFieldListTitle|printFieldListOption|printFieldListWhere|printFieldListFrom|printFieldListJoin|searchFormReplace|completeTabsHead|restrictedArea|showInputField|showOutputField|__construct|__get|__set|__call|__isset|init|remove|create|update|delete|fetch|fetchAll|index|_load_tables|_init)$'

sec_scan() {
  local M="$1" D="$CUSTOM/$M"
  echo "## SECURITY scan of custom/$M (advisory — review each hit)"
  echo
  echo "### [HIGH] Raw superglobals (use GETPOST(\$key,\$filter) which sanitizes):"
  grep -rnE '\$_(GET|POST|REQUEST|COOKIE)\[' --include='*.php' "$D" 2>/dev/null | grep -v '\$_SESSION' | head -40 || true
  echo
  echo "### [HIGH] Dangerous execution sinks:"
  grep -rnE '\b(eval|exec|shell_exec|system|passthru|popen|proc_open|assert)\s*\(' --include='*.php' "$D" 2>/dev/null | head -20 || true
  echo
  echo "### [HIGH] TLS verification disabled:"
  grep -rnE 'CURLOPT_SSL_VERIFY(PEER|HOST).*(false|, *0)|verify(_peer|peer) *=> *false' --include='*.php' "$D" 2>/dev/null | head -20 || true
  echo
  echo "### [MED] SQL built with a variable but no escape()/(int) on the same line (review for injection):"
  grep -rnE "(query|->query)\(.*\.\s*\\\$" --include='*.php' "$D" 2>/dev/null | grep -vE "escape\(|\(int\)|\(float\)|idate\(|getEntity\(|MAIN_DB_PREFIX|->id\b|::[A-Z_]+_CODE" | head -30 || true
  echo
  echo "### [MED] Output of a variable without dol_escape_htmltag()/dol_htmlentities() (possible XSS):"
  grep -rnE "(print|echo)\s+'.*'\s*\.\s*\\\$[a-zA-Z_>]+" --include='*.php' "$D" 2>/dev/null | grep -vE "dol_escape_htmltag\(|dol_htmlentities\(|dol_string_nohtmltag\(|price\(|newToken\(|->trans\(|dol_buildpath\(|\(int\)|\(float\)" | head -30 || true
  echo
  echo "### [MED] Forms vs CSRF tokens (every <form> needs a newToken() hidden input):"
  local forms tokens
  forms=$(grep -rohE "<form\b" --include='*.php' "$D" 2>/dev/null | wc -l | tr -d ' ')
  tokens=$(grep -rohE "newToken\(\)" --include='*.php' "$D" 2>/dev/null | wc -l | tr -d ' ')
  echo "  <form> tags: $forms    newToken() calls: $tokens"
  [ "$forms" -gt "$tokens" ] 2>/dev/null && echo "  ⚠ more forms than tokens — confirm each POST form carries a token." || echo "  ok (>= one token per form; still confirm placement)."
  echo
  echo "### [MED] Admin/setup pages — confirm an access gate is present:"
  for f in "$D"/admin/*.php; do
    [ -f "$f" ] || continue
    if grep -qE 'accessforbidden|\$user->admin|hasRight\(|restrictedArea\(' "$f"; then
      echo "  ok    ${f#$ROOT/}"
    else
      echo "  ⚠ MISSING gate: ${f#$ROOT/}"
    fi
  done
  echo
  echo "### [LOW] GETPOST without an explicit filter (defaults exist but be explicit: 'int','alpha','aZ09','restricthtml','nohtml'):"
  grep -rnE "GETPOST\(\s*'[^']+'\s*\)" --include='*.php' "$D" 2>/dev/null | head -20 || true
}

deadcode_scan() {
  local M="$1" D="$CUSTOM/$M"
  echo "## DEADCODE candidates in custom/$M"
  echo "## (functions/methods with <=1 occurrence of their name across htdocs = defined but never called)"
  echo "## Tags: [core-dispatch?] = name matches a core-called method, likely a FALSE positive."
  echo
  # collect "name|file:line" of every function/method definition in the module
  grep -rnoE 'function\s+&?\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\(' --include='*.php' "$D" 2>/dev/null \
    | sed -E 's/(function)\s+&?\s*([a-zA-Z_][a-zA-Z0-9_]*).*/\2|/' \
    | while IFS='|' read -r loc name; do
        [ -n "$name" ] || continue
        # total occurrences of the bare name as a call/reference across the whole htdocs
        local refs
        refs=$(grep -rohE "\b${name}\s*\(" --include='*.php' "$ROOT" 2>/dev/null | wc -l | tr -d ' ')
        if [ "$refs" -le 1 ] 2>/dev/null; then
          if echo "$name" | grep -qE "$DISPATCHED"; then
            printf '  [core-dispatch?] %-34s %s\n' "$name()" "$loc"
          else
            printf '  [UNUSED?]        %-34s %s\n' "$name()" "$loc"
          fi
        fi
      done
  echo
  echo "→ Review every [UNUSED?]: wire it into a caller, or DELETE it (no unused code stays)."
  echo "→ [core-dispatch?] entries are usually called by core by name — confirm, don't blindly cut."
}

files_scan() {
  local M="$1" D="$CUSTOM/$M"
  echo "## Candidate UNREFERENCED files in custom/$M (no other file mentions the basename by literal path)"
  echo "## EXPECTED to appear (Dolibarr loads these by naming convention, not by include):"
  echo "##   core/modules/mod*.class.php, core/triggers/interface_*.class.php,"
  echo "##   class/actions_*.class.php, index.php, admin/setup.php, sql/*, *.lang"
  echo "## Also false-positive: files included via a DYNAMIC path (e.g. 'setup_'.\$ref.'.php')."
  echo "## A real dead file = a .php/.tpl.php that is NONE of the above and still listed."
  echo
  find "$D" -type f \( -name '*.php' -o -name '*.tpl.php' \) 2>/dev/null | sort | while read -r f; do
    base="$(basename "$f")"
    # grep for the literal basename (escape regex metachars like the dots)
    pat="$(printf '%s' "$base" | sed 's/[.[\*^$]/\\&/g')"
    refs=$(grep -rohE "$pat" --include='*.php' "$ROOT" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$refs" -eq 0 ] 2>/dev/null; then
      printf '  [unreferenced?] %s\n' "${f#$ROOT/}"
    fi
  done
}

cmd="${1:-}"; shift || true
case "$cmd" in
  security) M="$(resolve_module "${1:-}")" || exit $?; sec_scan "$M" ;;
  deadcode) M="$(resolve_module "${1:-}")" || exit $?; deadcode_scan "$M" ;;
  files)    M="$(resolve_module "${1:-}")" || exit $?; files_scan "$M" ;;
  all)      M="$(resolve_module "${1:-}")" || exit $?; sec_scan "$M"; echo; deadcode_scan "$M"; echo; files_scan "$M" ;;
  *) grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
