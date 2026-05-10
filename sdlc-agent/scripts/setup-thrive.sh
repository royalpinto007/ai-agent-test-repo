#!/bin/bash
# Thrive-ERP setup — forks all Thrive-ERP repos to agent-accellier,
# clones them locally, and registers them with the SDLC API.
#
# Usage: bash scripts/setup-thrive.sh
# Requirements: GITHUB_TOKEN must be set (token for the agent-accellier account)

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── Config ────────────────────────────────────────────────────────────────────
SOURCE_ORG="Thrive-ERP"
FORK_ACCOUNT="agent-accellier"
REQUIREMENTS_REPO="thrive-requirements"
CLONE_DIR="/opt/repos"
API_URL="http://localhost:5001"
TOKEN="${GITHUB_TOKEN}"

[ -z "$TOKEN" ] && error "GITHUB_TOKEN is not set"

mkdir -p "$CLONE_DIR"

# ── Helper: GitHub API call ───────────────────────────────────────────────────
gh_api() {
  curl -s -H "Authorization: token $TOKEN" \
       -H "Accept: application/vnd.github+json" \
       "$@"
}

gh_post() {
  local url="$1"; shift
  curl -s -X POST -H "Authorization: token $TOKEN" \
       -H "Accept: application/vnd.github+json" \
       -H "Content-Type: application/json" \
       -d "$1" "$url"
}

# ── Detect test command from repo contents ────────────────────────────────────
detect_test_command() {
  local dir="$1"
  if [ -f "$dir/package.json" ]; then
    if grep -q '"test"' "$dir/package.json" 2>/dev/null; then
      echo '["npm","test"]'
    else
      echo '["npm","run","build"]'
    fi
  elif [ -f "$dir/requirements.txt" ] || [ -f "$dir/pyproject.toml" ]; then
    if [ -f "$dir/pytest.ini" ] || [ -f "$dir/setup.cfg" ] || grep -q "pytest" "$dir/requirements.txt" 2>/dev/null; then
      echo '["pytest"]'
    else
      echo '["python","-m","unittest"]'
    fi
  elif [ -f "$dir/go.mod" ]; then
    echo '["go","test","./..."]'
  elif [ -f "$dir/pom.xml" ]; then
    echo '["mvn","test"]'
  elif [ -f "$dir/Gemfile" ]; then
    echo '["bundle","exec","rspec"]'
  else
    echo '["echo","no test command detected"]'
  fi
}

# ── Detect main branch ────────────────────────────────────────────────────────
detect_main_branch() {
  local repo_name="$1"
  local branch
  branch=$(gh_api "https://api.github.com/repos/$FORK_ACCOUNT/$repo_name" | \
           python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('default_branch','main'))" 2>/dev/null)
  echo "${branch:-main}"
}

# ── Step 1: Clone thrive-requirements (the issue hub) ────────────────────────
echo ""
info "━━━ Cloning requirements repo ━━━"
REQS_DIR="$CLONE_DIR/$REQUIREMENTS_REPO"
if [ ! -d "$REQS_DIR" ]; then
  git clone "https://github.com/$SOURCE_ORG/$REQUIREMENTS_REPO.git" "$REQS_DIR"
  info "Cloned thrive-requirements"
else
  git -C "$REQS_DIR" pull -q
  info "thrive-requirements already cloned — pulled latest"
fi

# Register requirements repo with API
curl -s -X POST "$API_URL/repos" \
  -H "Content-Type: application/json" \
  -d "{
    \"owner\": \"$SOURCE_ORG\",
    \"repo\": \"$REQUIREMENTS_REPO\",
    \"repo_path\": \"$REQS_DIR\",
    \"test_command\": null,
    \"main_branch\": \"main\",
    \"requirements_repo\": true
  }" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  Registered:', d.get('registered','?'))"

# ── Step 2: Fetch all repos from Thrive-ERP org ──────────────────────────────
echo ""
info "━━━ Fetching Thrive-ERP repo list ━━━"

ALL_REPOS=()
PAGE=1
while true; do
  BATCH=$(gh_api "https://api.github.com/orgs/$SOURCE_ORG/repos?per_page=100&page=$PAGE&type=public" | \
          python3 -c "import sys,json; repos=json.load(sys.stdin); [print(r['name']) for r in repos if r['name'] != '$REQUIREMENTS_REPO']")
  [ -z "$BATCH" ] && break
  while IFS= read -r name; do
    ALL_REPOS+=("$name")
  done <<< "$BATCH"
  (( PAGE++ ))
done

info "Found ${#ALL_REPOS[@]} code repos to process"

# ── Step 3: Fork, clone, and register each repo ──────────────────────────────
echo ""
info "━━━ Forking, cloning, registering ━━━"

SUCCEEDED=0
FAILED=0

for REPO_NAME in "${ALL_REPOS[@]}"; do
  echo ""
  echo "  → $REPO_NAME"

  # Fork if not already forked
  FORK_CHECK=$(gh_api "https://api.github.com/repos/$FORK_ACCOUNT/$REPO_NAME" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('full_name',''))" 2>/dev/null)
  if [ -z "$FORK_CHECK" ]; then
    info "  Forking $SOURCE_ORG/$REPO_NAME → $FORK_ACCOUNT"
    gh_post "https://api.github.com/repos/$SOURCE_ORG/$REPO_NAME/forks" \
      "{\"organization\":\"$FORK_ACCOUNT\"}" > /dev/null
    sleep 2  # GitHub needs a moment to create the fork
  else
    info "  Fork already exists: $FORK_CHECK"
  fi

  # Clone the fork
  LOCAL_DIR="$CLONE_DIR/$REPO_NAME"
  if [ ! -d "$LOCAL_DIR" ]; then
    if git clone "https://github.com/$FORK_ACCOUNT/$REPO_NAME.git" "$LOCAL_DIR" 2>/dev/null; then
      info "  Cloned to $LOCAL_DIR"
    else
      warn "  Clone failed for $REPO_NAME — fork may still be creating, retry later"
      (( FAILED++ ))
      continue
    fi
  else
    git -C "$LOCAL_DIR" pull -q 2>/dev/null || true
    info "  Already cloned — pulled latest"
  fi

  # Add upstream remote (for future sync)
  if ! git -C "$LOCAL_DIR" remote | grep -q upstream 2>/dev/null; then
    git -C "$LOCAL_DIR" remote add upstream "https://github.com/$SOURCE_ORG/$REPO_NAME.git" 2>/dev/null || true
  fi

  # Detect test command and main branch
  TEST_CMD=$(detect_test_command "$LOCAL_DIR")
  MAIN_BRANCH=$(detect_main_branch "$REPO_NAME")

  # Register with API
  RESULT=$(curl -s -X POST "$API_URL/repos" \
    -H "Content-Type: application/json" \
    -d "{
      \"owner\": \"$FORK_ACCOUNT\",
      \"repo\": \"$REPO_NAME\",
      \"repo_path\": \"$LOCAL_DIR\",
      \"test_command\": $TEST_CMD,
      \"main_branch\": \"$MAIN_BRANCH\"
    }")
  REGISTERED=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('registered') or d.get('message','?'))" 2>/dev/null)
  info "  Registered: $REGISTERED (test: $TEST_CMD, branch: $MAIN_BRANCH)"
  (( SUCCEEDED++ ))
done

# ── Step 4: Set upstream sync cron ───────────────────────────────────────────
echo ""
info "━━━ Setting up upstream sync cron ━━━"

SYNC_SCRIPT="/opt/sdlc-agent/scripts/sync-forks.sh"
mkdir -p "$(dirname "$SYNC_SCRIPT")"
cat > "$SYNC_SCRIPT" << SYNCEOF
#!/bin/bash
# Sync all forks with upstream Thrive-ERP repos
for DIR in $CLONE_DIR/*/; do
  if git -C "\$DIR" remote | grep -q upstream 2>/dev/null; then
    git -C "\$DIR" fetch upstream -q 2>/dev/null
    BRANCH=\$(git -C "\$DIR" symbolic-ref --short HEAD 2>/dev/null)
    git -C "\$DIR" merge upstream/\$BRANCH --ff-only -q 2>/dev/null || true
  fi
done
SYNCEOF
chmod +x "$SYNC_SCRIPT"

# Run daily at 2am
(crontab -l 2>/dev/null | grep -v "sync-forks"; echo "0 2 * * * $SYNC_SCRIPT") | crontab -
info "Fork sync cron set (daily at 2am)"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━ Done ━━━${NC}"
echo ""
echo "  Requirements repo : $SOURCE_ORG/$REQUIREMENTS_REPO → $REQS_DIR"
echo "  Code repos        : $SUCCEEDED registered, $FAILED failed"
echo "  Forks             : github.com/$FORK_ACCOUNT/*"
echo "  Upstream sync     : daily at 2am via cron"
echo ""
echo "Verify with:"
echo "  curl http://localhost:5001/repos | python3 -m json.tool"
echo ""

if [ "$FAILED" -gt 0 ]; then
  warn "$FAILED repos failed (forks still creating). Run this script again in 60s to retry."
fi

# ── Step 5: Add GitHub webhook instructions ───────────────────────────────────
echo "━━━ GitHub webhook ━━━"
echo ""
echo "Add ONE webhook to: https://github.com/$SOURCE_ORG/$REQUIREMENTS_REPO/settings/hooks"
echo ""
echo "  Payload URL  : https://YOUR_SERVER/webhook/sdlc-start"
echo "  Content type : application/json"
echo "  Secret       : (value of WEBHOOK_SECRET from /etc/sdlc-agent/env)"
echo "  Events       : Issues, Issue comments"
echo ""
echo "That's it — all 31 repos are handled by the single requirements webhook."
