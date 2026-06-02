"""SessionBootstrap: проверяет состояние сессии при старте sidecar.

На startup:
  - если session.json есть и JWT доживёт >= jwt_min_ttl_sec → ok
  - если есть но мало TTL → попробовать refresh
  - если нет файла → ok=False, ждём POST /auth/recon
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from app.phygital_client.auth import RefreshError
from app.services.session_manager import SidecarSessionManager


@dataclass
class SessionInfo:
    ok: bool
    session_age_sec: int | None
    jwt_ttl_sec: int | None


class SessionBootstrap:
    def __init__(self, session_file: Path, jwt_min_ttl_sec: int = 900) -> None:
        self.session_file = session_file
        self.jwt_min_ttl_sec = jwt_min_ttl_sec
        self.manager = SidecarSessionManager(storage_path=session_file)
        self.session = None  # type: ignore[assignment]

    async def preflight(self) -> SessionInfo:
        s = self.manager.load()
        if s is None:
            return SessionInfo(ok=False, session_age_sec=None, jwt_ttl_sec=None)

        self.session = s

        ttl = s.jwt_ttl_seconds()
        age = None
        if s.captured_at:
            age = int((datetime.now(timezone.utc) - s.captured_at).total_seconds())

        if ttl is None:
            logger.warning("Session loaded but JWT TTL not readable")
            return SessionInfo(ok=False, session_age_sec=age, jwt_ttl_sec=None)

        if ttl < self.jwt_min_ttl_sec:
            logger.info(f"JWT TTL={ttl}s < min={self.jwt_min_ttl_sec}s, refreshing...")
            try:
                await self.manager.refresh(s)
                ttl = s.jwt_ttl_seconds()
                logger.info(f"Refresh OK, new TTL={ttl}s")
            except RefreshError as e:
                logger.error(f"Preflight refresh failed: {e}")
                return SessionInfo(ok=False, session_age_sec=age, jwt_ttl_sec=ttl)

        return SessionInfo(ok=True, session_age_sec=age, jwt_ttl_sec=ttl)

    def info(self) -> SessionInfo:
        """Текущее состояние БЕЗ refresh (для GET /health)."""
        if self.session is None:
            s = self.manager.load()
            if s is None:
                return SessionInfo(ok=False, session_age_sec=None, jwt_ttl_sec=None)
            self.session = s
        s = self.session
        ttl = s.jwt_ttl_seconds()
        age = None
        if s.captured_at:
            age = int((datetime.now(timezone.utc) - s.captured_at).total_seconds())
        ok = ttl is not None and ttl > 0
        return SessionInfo(ok=ok, session_age_sec=age, jwt_ttl_sec=ttl)
