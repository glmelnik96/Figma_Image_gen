#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_ROOT="$HOME/Library/Application Support/PhygitalStudio/sidecar-runtime"
RUNNER="$RUNTIME_ROOT/scripts/run_sidecar.sh"
LABEL="com.phygitalstudio.sidecar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/PhygitalStudio"
OUT_LOG="$LOG_DIR/sidecar.out.log"
ERR_LOG="$LOG_DIR/sidecar.err.log"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR" "$RUNTIME_ROOT"

# LaunchAgent launched outside interactive Terminal can hit macOS Desktop privacy
# restrictions when the repo lives under ~/Desktop. Run from App Support runtime.
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  "$ROOT/" "$RUNTIME_ROOT/"
chmod +x "$RUNNER"

free_port_8765() {
  local pids
  pids="$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "Stopping existing listener(s) on :8765: $pids"
    echo "$pids" | xargs kill >/dev/null 2>&1 || true
    sleep 1
    pids="$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$pids" ]; then
      echo "$pids" | xargs kill -9 >/dev/null 2>&1 || true
    fi
  fi
}

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/bash</string>
      <string>$RUNNER</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$RUNTIME_ROOT</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$OUT_LOG</string>
    <key>StandardErrorPath</key>
    <string>$ERR_LOG</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PYTHONUNBUFFERED</key>
      <string>1</string>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
  </dict>
</plist>
EOF

# Reset previous state and (re)start.
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
free_port_8765
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo ""
echo "Autostart installed: $PLIST"
echo "Runtime copy: $RUNTIME_ROOT"
echo "Service label: $LABEL"
echo "Logs:"
echo "  $OUT_LOG"
echo "  $ERR_LOG"
echo ""
echo "Sidecar should now stay online automatically."

