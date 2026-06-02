"""Тесты /nodes router (включая /nodes/video)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import build_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.paths.resolve_app_data", lambda: tmp_path)
    app = build_app()
    with TestClient(app) as c:
        c.app.state.job_runner.schedule = MagicMock()
        yield c


def test_get_nodes_lists_registered(client):
    r = client.get("/nodes")
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    ids = {n["id"] for n in nodes}
    assert 94 in ids


def test_get_nodes_video_returns_matrix(client):
    r = client.get("/nodes/video")
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    ids = {n["node_id"] for n in nodes}
    assert ids == {74, 100, 121, 124}
    by_id = {n["node_id"]: n for n in nodes}
    assert "init_img" in by_id[74]["slots"]
    assert by_id[74]["slots"]["init_img"] == "array"
    assert by_id[100]["slots"]["start_img"] == "scalar"
    assert "char_video_prompt" in by_id[124]["scenarios"]
