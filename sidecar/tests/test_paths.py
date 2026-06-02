"""Тесты cross-platform path resolver."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.paths import (
    APP_NAME,
    resolve_app_data,
    downloads_dir,
    uploads_dir,
    user_data_dir,
    logs_dir,
    session_file,
    jobs_jsonl,
    ensure_dirs,
)


def test_app_name_is_phygital_studio():
    assert APP_NAME == "PhygitalStudio"


@patch.dict(os.environ, {"LOCALAPPDATA": "C:/fake/LocalAppData"})
def test_resolve_app_data_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    p = resolve_app_data()
    assert p == Path("C:/fake/LocalAppData/PhygitalStudio")


def test_resolve_app_data_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: Path("/Users/test"))
    p = resolve_app_data()
    assert p == Path("/Users/test/Library/Application Support/PhygitalStudio")


def test_resolve_app_data_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", lambda: Path("/home/test"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    p = resolve_app_data()
    assert p == Path("/home/test/.local/share/PhygitalStudio")


def test_subpaths_are_under_app_data(tmp_path, monkeypatch):
    monkeypatch.setattr("app.paths.resolve_app_data", lambda: tmp_path)
    assert downloads_dir() == tmp_path / "downloads"
    assert uploads_dir() == tmp_path / "uploads"
    assert user_data_dir() == tmp_path / "user_data"
    assert logs_dir() == tmp_path / "logs"
    assert session_file() == tmp_path / "session.json"
    assert jobs_jsonl() == tmp_path / "jobs.jsonl"


def test_ensure_dirs_creates_all(tmp_path, monkeypatch):
    monkeypatch.setattr("app.paths.resolve_app_data", lambda: tmp_path)
    ensure_dirs()
    assert (tmp_path / "downloads").is_dir()
    assert (tmp_path / "uploads").is_dir()
    assert (tmp_path / "user_data").is_dir()
    assert (tmp_path / "logs").is_dir()


def test_ensure_dirs_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.paths.resolve_app_data", lambda: tmp_path)
    ensure_dirs()
    ensure_dirs()  # should not raise
    assert (tmp_path / "downloads").is_dir()
