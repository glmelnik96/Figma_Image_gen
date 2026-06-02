#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

pick_python() {
  for c in \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3.12 \
    /usr/local/bin/python3.11 \
    python3.12 \
    python3.11 \
    python3; do
    if command -v "$c" >/dev/null 2>&1; then
      "$(command -v "$c")" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
      if [ $? -eq 0 ]; then
        command -v "$c"
        return 0
      fi
    fi
  done
  return 1
}

PY_BIN="$(pick_python || true)"
if [ -z "${PY_BIN:-}" ]; then
  echo "ERROR: Python 3.11+ is required but not found in PATH." >&2
  exit 1
fi

venv_ok=0
if [ -x ".venv/bin/python" ]; then
  if ./.venv/bin/python - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
  then
    venv_ok=1
  fi
fi

if [ "$venv_ok" -ne 1 ]; then
  echo "Creating/recreating virtualenv with $(basename "$PY_BIN")..."
  rm -rf .venv
  "$PY_BIN" -m venv .venv
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install -e .
fi

exec ./.venv/bin/python -m app.main

