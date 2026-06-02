"""Одноразовый диагностический скрипт: GET /api/v2/tasks/queue-position/<id>.

Не трогает sidecar, читает session.json напрямую.

  python -m scripts.debug_task 7087216
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from app.phygital_client.api import PhygitalClient
from app.phygital_client.session import SessionManager


def _session_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA not set (запускай на Windows)")
    return Path(local) / "PhygitalStudio" / "session.json"


async def main(task_id: int) -> int:
    path = _session_path()
    if not path.exists():
        print(f"session.json не найден: {path}")
        return 2
    session = SessionManager.from_recon_dump(path)
    if not session.access_token:
        print("нет access_token в session.json — нужен auth login")
        return 2

    async with PhygitalClient(session) as client:
        data = await client.task_status(task_id)
    print(json.dumps(data, indent=2, ensure_ascii=False)[:4000])
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m scripts.debug_task <task_id>")
        sys.exit(2)
    sys.exit(asyncio.run(main(int(sys.argv[1]))))
