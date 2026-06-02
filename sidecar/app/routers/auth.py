"""Auth endpoints.

- POST /auth/login   — email/password sign-in (no browser), persists session.
- GET  /auth/status  — current session validity (mirrors /health session bits).
- POST /auth/logout  — drop the stored session.
- POST /auth/recon   — Playwright headed browser login (fallback).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from app import paths
from app.services.login import LoginError, signin
from app.services.playwright_recon import run_recon, ReconError

router = APIRouter()


class LoginBody(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


def _session_status(bs) -> dict:
    info = bs.info()
    return {
        "session_ok": info.ok,
        "session_age_sec": info.session_age_sec,
        "jwt_ttl_sec": info.jwt_ttl_sec,
    }


@router.post("/auth/login")
async def login(body: LoginBody, request: Request) -> dict:
    """Authenticate with Phygital+ via email/password and persist the session.

    On success the new session immediately becomes active for /jobs etc.
    """
    bs = request.app.state.session_bootstrap
    try:
        session = await signin(body.email.strip(), body.password)
    except LoginError as e:
        raise HTTPException(status_code=401, detail={"error": "login_failed", "message": str(e)})

    # Persist + activate. bs.manager.save stamps captured_at; bs.session makes
    # /health and the PhygitalClient factory pick it up without a restart.
    bs.manager.save(session)
    bs.session = session
    logger.info(f"Login OK for {body.email} (jwt_ttl={session.jwt_ttl_seconds()}s)")

    return {"ok": True, "email": body.email, **_session_status(bs)}


@router.get("/auth/status")
async def auth_status(request: Request) -> dict:
    return _session_status(request.app.state.session_bootstrap)


@router.post("/auth/logout")
async def logout(request: Request) -> dict:
    bs = request.app.state.session_bootstrap
    bs.session = None
    try:
        paths.session_file().unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"logout: could not remove session file: {e}")
    return {"ok": True, "session_ok": False}


@router.post("/auth/recon")
async def start_recon(request: Request) -> dict:
    state = request.app.state
    if getattr(state, "recon_task", None) and not state.recon_task.done():
        raise HTTPException(status_code=409, detail={"error": "recon_in_progress"})

    async def _do() -> None:
        try:
            await run_recon(
                user_data_dir=paths.user_data_dir(),
                session_file=paths.session_file(),
                timeout_sec=600,
            )
            # После успешного recon — обновить state.session_bootstrap.session
            bs = state.session_bootstrap
            bs.session = None  # форсим перечитать
            bs.info()
            logger.info("Recon finished, session updated")
        except ReconError as e:
            logger.error(f"Recon failed: {e}")
        except Exception:
            logger.exception("Recon crashed")

    state.recon_task = asyncio.create_task(_do())
    return {"started": True, "hint": "poll GET /health until session_age_sec is set"}
