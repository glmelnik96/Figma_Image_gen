#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_ROOT="$HOME/Library/Application Support/PhygitalStudio/sidecar-runtime"
LABEL="com.phygitalstudio.sidecar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ ! -f "$PLIST" ]; then
  echo "Autostart is not installed. Run ./install_autostart.command first."
  exit 1
fi

mkdir -p "$RUNTIME_ROOT"
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  "$ROOT/" "$RUNTIME_ROOT/"

PIDS="$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  echo "Stopping existing listener(s) on :8765: $PIDS"
  echo "$PIDS" | xargs kill >/dev/null 2>&1 || true
  sleep 1
fi

launchctl kickstart -k "gui/$(id -u)/$LABEL"
echo "Runtime synced and service restarted."

