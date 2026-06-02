"""Тесты Settings."""
from __future__ import annotations

import pytest

from app.config import Settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.host == "127.0.0.1"
    assert s.port == 8765
    assert s.phygital_max_concurrent == 5
    assert s.log_level == "INFO"
    assert s.poll_interval_sec == 1.5
    assert s.jwt_min_ttl_sec == 900  # 15 min


def test_env_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PHYGITAL_MAX_CONCURRENT=10\nLOG_LEVEL=DEBUG\nPORT=9000\n",
        encoding="utf-8",
    )
    s = Settings(_env_file=str(env_file))
    assert s.phygital_max_concurrent == 10
    assert s.log_level == "DEBUG"
    assert s.port == 9000


def test_env_var_override(monkeypatch):
    monkeypatch.setenv("PHYGITAL_MAX_CONCURRENT", "7")
    s = Settings(_env_file=None)
    assert s.phygital_max_concurrent == 7
