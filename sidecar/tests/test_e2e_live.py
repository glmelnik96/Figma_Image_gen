"""End-to-end live test.

ТРЕБОВАНИЯ ДЛЯ ЗАПУСКА:
  1. Sidecar поднят: `python -m app.main` в отдельном терминале.
  2. Валидная Phygital-сессия в %LOCALAPPDATA%\\PhygitalStudio\\session.json.
     (Получить через `python -m scripts.cli auth login` -- откроет браузер.)

ЗАПУСК:
  pytest -m live tests/test_e2e_live.py -v -s

В CI пропускается -- нужен живой Phygital backend.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

BASE = "http://127.0.0.1:8765"


@pytest.mark.live
async def test_image_gen_end_to_end():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        # 1. health -- есть сессия?
        h = (await c.get("/health")).json()
        assert h["ok"], "sidecar /health failed"
        assert h["session_age_sec"] is not None, "no Phygital session -- run `cli auth login` first"
        assert h["jwt_ttl_sec"] and h["jwt_ttl_sec"] > 0, f"JWT expired (ttl={h['jwt_ttl_sec']})"

        # 2. nodes -- Nano Banana доступна?
        nodes = (await c.get("/nodes")).json()["nodes"]
        assert any(n["id"] == 94 for n in nodes), "Nano Banana (94) not in /nodes"

        # 3. submit
        r = await c.post("/jobs", json={
            "node_id": 94,
            "params": {"prompt": "minimalist test image, single white circle on black background"},
        })
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]
        print(f"\n  job_id={job_id}")

        # 4. poll
        last = None
        j = None
        for _ in range(80):  # ~120s
            await asyncio.sleep(1.5)
            j = (await c.get(f"/jobs/{job_id}")).json()
            if j["status"] != last:
                print(f"  [{j['status']}]")
                last = j["status"]
            if j["status"] in ("completed", "failed", "canceled"):
                break

        assert j is not None
        assert j["status"] == "completed", f"job ended with status={j['status']} error={j.get('error')}"
        assert j["result_paths"], "no result_paths"

        # 5. download
        d = await c.get(f"/jobs/{job_id}/download")
        assert d.status_code == 200, d.text
        assert d.headers["content-type"].startswith("image/"), d.headers["content-type"]
        assert len(d.content) > 10_000, f"image too small: {len(d.content)} bytes"
        print(f"  downloaded {len(d.content)} bytes, content-type={d.headers['content-type']}")
