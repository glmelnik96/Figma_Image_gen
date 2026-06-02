#!/bin/bash
# Convenience launcher for local sidecar.
# - If launchd autostart is installed, this just (re)starts that single service.
# - Otherwise it runs sidecar in the current terminal (foreground debug mode).
set -euo pipefail
cd "$(dirname "$0")"

LABEL="com.phygitalstudio.sidecar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
TOKEN_FILE="$HOME/Library/Application Support/PhygitalStudio/sidecar.token"
RUNTIME_ROOT="$HOME/Library/Application Support/PhygitalStudio/sidecar-runtime"

if [ -f "$PLIST" ]; then
  if [ -d "$RUNTIME_ROOT" ]; then
    rsync -a --delete \
      --exclude ".git" \
      --exclude ".venv" \
      --exclude "__pycache__" \
      --exclude "*.pyc" \
      "$(pwd)/" "$RUNTIME_ROOT/"
  fi
  launchctl bootstrap "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
  PIDS="$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$PIDS" ]; then
    echo "Stopping existing listener(s) on :8765: $PIDS"
    echo "$PIDS" | xargs kill >/dev/null 2>&1 || true
    sleep 1
  fi
  launchctl kickstart -k "gui/$(id -u)/$LABEL"
  echo "Launchd service restarted: $LABEL"
  if [ -f "$TOKEN_FILE" ]; then
    echo ""
    echo "Sidecar token:"
    echo "  $(cat "$TOKEN_FILE")"
  fi
  echo ""
  echo "Health probe:"
  curl -s http://localhost:8765/health || true
  echo ""
  exit 0
fi

echo "Autostart is not installed yet."
echo "Install once with: ./install_autostart.command"
echo ""

if [ ! -d ".venv" ]; then
  echo "First run: creating virtualenv and installing dependencies…"
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install -e .
fi

if [ -f "$TOKEN_FILE" ]; then
  echo ""
  echo "Sidecar token:"
  echo "  $(cat "$TOKEN_FILE")"
  echo ""
fi

echo "Starting sidecar in foreground on http://localhost:8765 (Ctrl+C to stop)"
exec ./scripts/run_sidecar.sh
