#!/bin/bash
# Double-click to start the Phygital Studio sidecar.
# Creates the venv on first run, then launches the FastAPI server on 127.0.0.1:8765.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "First run: creating virtualenv and installing dependencies…"
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install -e .
fi

TOKEN_FILE="$HOME/Library/Application Support/PhygitalStudio/sidecar.token"
if [ -f "$TOKEN_FILE" ]; then
  echo ""
  echo "Sidecar token (paste into the Figma plugin ⚙ once):"
  echo "  $(cat "$TOKEN_FILE")"
  echo ""
fi

echo "Starting sidecar on http://localhost:8765  (Ctrl+C to stop)"
echo "(token prints above on next launch if the file didn't exist yet)"
exec ./.venv/bin/python -m app.main
