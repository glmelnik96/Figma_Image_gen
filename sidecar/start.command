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
SERVICE_PORT="${SERVICE_PORT:-18765}"

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
  launchctl kickstart -k "gui/$(id -u)/$LABEL"
  echo "Launchd service restarted: $LABEL"
  if [ -f "$TOKEN_FILE" ]; then
    echo ""
    echo "Sidecar token:"
    echo "  $(cat "$TOKEN_FILE")"
  fi
  echo ""
  echo "Health probe:"
  HEALTH=""
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    HEALTH="$(curl -fsS "http://localhost:${SERVICE_PORT}/health" 2>/dev/null || true)"
    if [ -n "$HEALTH" ]; then
      echo "$HEALTH"
      break
    fi
    sleep 0.4
  done
  if [ -z "$HEALTH" ]; then
    echo "health check failed (service may still be starting)"
  fi
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

echo "Starting sidecar in foreground on http://localhost:${SERVICE_PORT} (Ctrl+C to stop)"
exec ./scripts/run_sidecar.sh
