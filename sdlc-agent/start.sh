#!/bin/bash
# Start the SDLC API server
# Run this before starting n8n

cd "$(dirname "$0")"

source ../venv/bin/activate

# GitHub token with repo scope — required for PR and issue creation
export GITHUB_TOKEN="${GITHUB_TOKEN:-}"

if [ -z "$GITHUB_TOKEN" ]; then
  echo "WARNING: GITHUB_TOKEN not set — PR and issue creation will fail"
  echo "Run: export GITHUB_TOKEN=your_token_here"
fi

echo "Starting SDLC API on port 5001..."
echo "Registered repos:"
python3 -c "import json; [print(f'  - {k}') for k in json.load(open('repos.json'))]" 2>/dev/null || echo "  (none — add via POST /repos)"
echo ""
python sdlc_api.py
