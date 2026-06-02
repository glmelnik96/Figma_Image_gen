#!/bin/bash
set -euo pipefail

LABEL="com.phygitalstudio.sidecar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
RUNTIME_ROOT="$HOME/Library/Application Support/PhygitalStudio/sidecar-runtime"

launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST"
rm -rf "$RUNTIME_ROOT"

echo "Autostart removed for $LABEL"

