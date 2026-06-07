#!/bin/bash
# Phygital Studio — single-click launcher (macOS).
#
# Это единственный скрипт, который пользователь должен дёргать вручную:
#   1. Двойной клик в Finder.
#   2. Скрипт идемпотентно ставит autostart (при первом запуске),
#      синкает runtime, кикстартит launchd-сервис.
#   3. Ждёт пока sidecar поднимется (/health отвечает).
#   4. Кладёт sidecar-токен в системный буфер обмена.
#   5. Показывает macOS-нотификацию с инструкцией следующего шага.
#
# Все последующие запуски Mac'а — sidecar поднимается сам через launchd,
# скрипт нужен только при первой установке и когда хочется явно
# перезапустить сервис после правок в `sidecar/`.

set -euo pipefail
cd "$(dirname "$0")"

ROOT="$(pwd)"
SIDECAR_DIR="$ROOT/sidecar"
LABEL="com.phygitalstudio.sidecar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
TOKEN_FILE="$HOME/Library/Application Support/PhygitalStudio/sidecar.token"
SERVICE_PORT="${SERVICE_PORT:-18765}"
ERR_LOG="$HOME/Library/Logs/PhygitalStudio/sidecar.err.log"

notify() {
  # display notification — best-effort; не падаем если accessibility не дала.
  osascript -e "display notification \"$1\" with title \"Phygital Studio\"" >/dev/null 2>&1 || true
}

alert() {
  osascript -e "display alert \"Phygital Studio\" message \"$1\"" >/dev/null 2>&1 || true
}

# --- Sanity checks ----------------------------------------------------------

if [ ! -d "$SIDECAR_DIR" ]; then
  echo "ERROR: $SIDECAR_DIR not found. Run this script from the repo root."
  alert "sidecar/ directory missing. Re-clone the repository."
  exit 1
fi

# --- Install autostart on first run, otherwise just restart -----------------

if [ ! -f "$PLIST" ]; then
  echo "First run detected — installing autostart launchd service…"
  notify "Installing autostart…"
  (cd "$SIDECAR_DIR" && SERVICE_PORT="$SERVICE_PORT" ./install_autostart.command)
else
  echo "Restarting existing autostart service…"
  notify "Restarting sidecar…"
  (cd "$SIDECAR_DIR" && SERVICE_PORT="$SERVICE_PORT" ./start.command)
fi

# --- Wait for /health -------------------------------------------------------

echo ""
echo "Waiting for sidecar at http://localhost:${SERVICE_PORT}/health …"
HEALTH=""
for _ in $(seq 1 40); do
  HEALTH="$(curl -fsS "http://localhost:${SERVICE_PORT}/health" 2>/dev/null || true)"
  if [ -n "$HEALTH" ]; then break; fi
  sleep 0.3
done

if [ -z "$HEALTH" ]; then
  echo ""
  echo "ERROR: sidecar did not respond within ~12s."
  if [ -f "$ERR_LOG" ]; then
    echo "Last error-log lines:"
    tail -n 30 "$ERR_LOG" || true
  fi
  alert "Sidecar failed to start. Check ~/Library/Logs/PhygitalStudio/sidecar.err.log"
  exit 1
fi

echo "Health: $HEALTH"

# --- Copy token to clipboard ------------------------------------------------

if [ ! -f "$TOKEN_FILE" ]; then
  echo "WARNING: token file not found at $TOKEN_FILE"
  alert "Sidecar is running but token file is missing. Restart the launcher."
  exit 1
fi

tr -d '\n' < "$TOKEN_FILE" | pbcopy 2>/dev/null || true
TOKEN_PREVIEW="$(head -c 10 "$TOKEN_FILE")…"

cat <<EOF

────────────────────────────────────────────────────────────────
  ✓ Sidecar is running on http://localhost:${SERVICE_PORT}
  ✓ Token copied to clipboard (${TOKEN_PREVIEW})

  Next steps in Figma (one-time):
    1. Plugins → Development → Import plugin from manifest…
       (pick figma-plugin/manifest.json from this repo)
    2. Plugins → Development → Cloud.ru Brand Generations
    3. Click ⚙ → Paste (token field already focused — Cmd+V works)
    4. Sign in with your Phygital+ email + password

  After that the plugin remembers everything. Just open it from
  Plugins → Development → Cloud.ru Brand Generations on each new Figma file.
────────────────────────────────────────────────────────────────

EOF

notify "Token copied. Open Figma → Cloud.ru Brand Generations → ⚙ → Paste."

# Foreground hold for 3 seconds so Terminal doesn't snap shut on the user.
sleep 2
