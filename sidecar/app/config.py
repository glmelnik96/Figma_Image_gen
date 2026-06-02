"""Sidecar settings via pydantic-settings + .env."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    host: str = "127.0.0.1"
    port: int = 8765

    phygital_max_concurrent: int = Field(5, ge=1, le=20)
    # Per-node лимит для тяжёлых видео-нод (74, 100, 121, 124).
    phygital_max_concurrent_video: int = Field(2, ge=1, le=10)
    poll_interval_sec: float = 1.5
    jwt_min_ttl_sec: int = 900  # preflight refresh порог

    download_timeout_sec: float = 300.0
    download_retries: int = 3

    log_level: str = "INFO"
    log_rotation_mb: int = 10
    log_retain: int = 5
