"""Тесты SessionBootstrap (без сети — мокаем refresh)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services.session_bootstrap import SessionBootstrap
from app.phygital_client.session import Session


def _write_session_file(path: Path, *, access_token: str = "test.jwt.token") -> None:
    cookies = [
        {"name": "st-access-token", "value": access_token},
        {"name": "st-refresh-token", "value": "refresh"},
    ]
    path.write_text(
        json.dumps({"cookies": cookies, "captured_at": "2026-05-21T10:00:00+00:00"}),
        encoding="utf-8",
    )


async def test_no_session_file_returns_null(tmp_path: Path):
    bs = SessionBootstrap(session_file=tmp_path / "session.json", jwt_min_ttl_sec=900)
    info = await bs.preflight()
    assert info.session_age_sec is None
    assert info.jwt_ttl_sec is None
    assert info.ok is False


async def test_existing_session_with_valid_jwt(tmp_path: Path, monkeypatch):
    sf = tmp_path / "session.json"
    # JWT с exp в будущем — собираем фейковый
    import base64, json as _json, time
    payload = _json.dumps({"exp": int(time.time()) + 3600}).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    fake_jwt = f"header.{payload_b64}.sig"
    _write_session_file(sf, access_token=fake_jwt)

    bs = SessionBootstrap(session_file=sf, jwt_min_ttl_sec=900)
    info = await bs.preflight()
    assert info.ok is True
    assert info.jwt_ttl_sec is not None and info.jwt_ttl_sec > 3000


async def test_short_ttl_triggers_refresh(tmp_path: Path):
    sf = tmp_path / "session.json"
    import base64, json as _json, time
    # JWT с exp через 5 минут — меньше jwt_min_ttl_sec=900s
    payload = _json.dumps({"exp": int(time.time()) + 300}).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    fake_jwt = f"header.{payload_b64}.sig"
    _write_session_file(sf, access_token=fake_jwt)

    bs = SessionBootstrap(session_file=sf, jwt_min_ttl_sec=900)
    # Мокаем refresh, чтобы не ходить в сеть
    bs.manager.refresh = AsyncMock(side_effect=lambda s: s)
    info = await bs.preflight()
    bs.manager.refresh.assert_called_once()
