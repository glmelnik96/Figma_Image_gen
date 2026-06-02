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

launchctl kickstart -k "gui/$(id -u)/$LABEL"
echo "Runtime synced and service restarted."

