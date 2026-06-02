"""Тесты /assets disk-usage и disk-cache cleanup endpoints."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import paths
from app.main import build_app


def test_disk_usage_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.paths.resolve_app_data", lambda: tmp_path)
    app = build_app()
    with TestClient(app) as client:
        r = client.get("/assets/disk-usage")
    assert r.status_code == 200
    assert r.json() == {"count": 0, "total_bytes": 0}


def test_disk_usage_counts_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.paths.resolve_app_data", lambda: tmp_path)
    app = build_app()
    with TestClient(app) as client:
        d = paths.asset_uploads_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "clip_a.mp4").write_bytes(b"x" * 100)
        (d / "frame_b.png").write_bytes(b"y" * 50)

        r = client.get("/assets/disk-usage")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["total_bytes"] == 150


def test_clear_disk_cache_removes_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.paths.resolve_app_data", lambda: tmp_path)
    app = build_app()
    with TestClient(app) as client:
        d = paths.asset_uploads_dir()
        d.mkdir(parents=True, exist_ok=True)
        f1 = d / "clip_a.mp4"
        f2 = d / "frame_b.png"
        f1.write_bytes(b"x" * 100)
        f2.write_bytes(b"y" * 50)

        r = client.delete("/assets/disk-cache")

    assert r.status_code == 200
    body = r.json()
    assert body["cleared_count"] == 2
    assert body["freed_bytes"] == 150
    assert not f1.exists()
    assert not f2.exists()


def test_clear_disk_cache_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.paths.resolve_app_data", lambda: tmp_path)
    app = build_app()
    with TestClient(app) as client:
        r = client.delete("/assets/disk-cache")
    assert r.status_code == 200
    assert r.json() == {"cleared_count": 0, "freed_bytes": 0}


def test_clear_disk_cache_preserves_subdirs(tmp_path: Path, monkeypatch):
    """Поддиректории и их содержимое не трогаем — только файлы верхнего уровня."""
    monkeypatch.setattr("app.paths.resolve_app_data", lambda: tmp_path)
    app = build_app()
    with TestClient(app) as client:
        d = paths.asset_uploads_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "clip_a.mp4").write_bytes(b"x")
        sub = d / "subdir"
        sub.mkdir()
        nested = sub / "keep.txt"
        nested.write_bytes(b"keep")

        r = client.delete("/assets/disk-cache")
    assert r.status_code == 200
    body = r.json()
    assert body["cleared_count"] == 1
    assert nested.exists()


def test_disk_usage_requires_auth(tmp_path: Path, monkeypatch):
    """Без X-Phygital-Sidecar-Token endpoint должен возвращать 401."""
    monkeypatch.setattr("app.paths.resolve_app_data", lambda: tmp_path)
    app = build_app()
    with TestClient(app) as client:
        # Удаляем токен, который conftest автоматически вставил
        client.headers.pop("X-Phygital-Sidecar-Token", None)
        r = client.get("/assets/disk-usage")
    assert r.status_code == 401
