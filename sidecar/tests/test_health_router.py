"""Тест /health."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import build_app


def test_health_no_session(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.paths.resolve_app_data", lambda: tmp_path)
    app = build_app()
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True  # sidecar поднят
    assert body["session_age_sec"] is None
    assert body["jwt_ttl_sec"] is None
    assert body["active_jobs"] == 0
