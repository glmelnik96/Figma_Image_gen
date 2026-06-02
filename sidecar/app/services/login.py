"""Email/password sign-in to Phygital+ (SuperTokens, header auth-mode).

Lets the Figma plugin authenticate without a browser. Reproduces the exact
request the Phygital web app makes (verified against recon HAR):

    POST {API_BASE}/auth/signin
    rid: thirdpartyemailpassword
    st-auth-mode: header
    fdi-version: 1.17
    body: {"formFields":[{"id":"email","value":...},{"id":"password","value":...}]}

On success SuperTokens returns the new tokens in *response headers*
(st-access-token / st-refresh-token / front-token) and HTTP 200 with
body {"status":"OK","user":{...}}. We assemble those into a Session
identical in shape to what the recon dump / refresh flow produces, so the
rest of the sidecar (PhygitalClient, refresh, JobRunner) works unchanged.

This module lives in services/ (not phygital_client/) on purpose:
phygital_client/ is vendored from Phygital-bot and overwritten by
scripts/sync_from_bot.py, so sidecar-only code must not live there.
"""
from __future__ import annotations

import ssl
import time

import httpx
import truststore

from app.phygital_client.api import API_BASE, BROWSER_UA, ORIGIN
from app.phygital_client.session import (
    ACCESS_COOKIE,
    FRONT_TOKEN_COOKIE,
    LAST_UPDATE_COOKIE,
    REFRESH_COOKIE,
    Session,
)

_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

SIGNIN_URL = f"{API_BASE}/auth/signin"
COOKIE_DOMAIN = "app.phygital.plus"

# /auth/signin auto-creates an account for unknown emails. If the returned
# account was created within this window, treat it as an accidental sign-up
# (typo'd email) rather than a real sign-in and reject it.
SIGNUP_REJECT_WINDOW_SEC = 120

# SuperTokens status strings that mean "credentials/flow problem" rather than
# transport failure. Mapped to user-facing messages.
_STATUS_MESSAGES = {
    "WRONG_CREDENTIALS_ERROR": "Wrong email or password.",
    "FIELD_ERROR": "Invalid email or password format.",
    "SIGN_IN_NOT_ALLOWED": "Sign-in is not allowed for this account.",
    "EMAIL_VERIFICATION_REQUIRED": "Email verification required.",
}


class LoginError(Exception):
    """Sign-in failed — wrong credentials or unexpected response."""


def _cookie(name: str, value: str) -> dict[str, str]:
    return {"name": name, "value": value, "domain": COOKIE_DOMAIN, "path": "/"}


async def signin(email: str, password: str, *, timeout: float = 30.0) -> Session:
    """Perform email/password sign-in and return a ready-to-use Session.

    Raises LoginError on bad credentials or malformed response.
    """
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "*/*",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Origin": ORIGIN,
        "Referer": f"{ORIGIN}/",
        "rid": "thirdpartyemailpassword",
        "st-auth-mode": "header",
        "fdi-version": "1.17",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }
    body = {
        "formFields": [
            {"id": "email", "value": email},
            {"id": "password", "value": password},
        ]
    }

    async with httpx.AsyncClient(
        timeout=timeout, http2=True, follow_redirects=False, verify=_SSL_CTX
    ) as client:
        try:
            resp = await client.post(SIGNIN_URL, headers=headers, json=body)
        except httpx.HTTPError as e:
            raise LoginError(f"Network error reaching Phygital: {e}") from e

    if resp.status_code != 200:
        raise LoginError(f"Sign-in HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
    except Exception as e:
        raise LoginError(f"Sign-in returned non-JSON response: {e}") from e

    status = (data.get("status") or "").upper()
    if status != "OK":
        # SuperTokens returns 200 with a status field on credential errors.
        msg = _STATUS_MESSAGES.get(status)
        if not msg and status == "FIELD_ERROR":
            fields = data.get("formFields") or []
            msg = "; ".join(f.get("error", "") for f in fields) or "Field error."
        raise LoginError(msg or f"Sign-in rejected: {status or data}")

    # Phygital's /auth/signin is sign-in-OR-sign-up: an unknown email silently
    # creates a brand-new (empty, no credits) account and returns OK. For a
    # team tool everyone already has a paid account, so a "successful" login
    # into a freshly-minted account almost always means a typo'd email. Detect
    # it via user.timeJoined (original account creation time) and refuse, so we
    # don't switch the user onto a useless account without telling them.
    user = data.get("user") or {}
    time_joined = user.get("timeJoined")
    if isinstance(time_joined, (int, float)):
        age_sec = (time.time() * 1000 - time_joined) / 1000
        if age_sec < SIGNUP_REJECT_WINDOW_SEC:
            raise LoginError(
                "No Phygital+ account exists for this email (a new empty account "
                "would be created). Double-check the email, or sign up on the website first."
            )

    access = resp.headers.get("st-access-token")
    refresh = resp.headers.get("st-refresh-token")
    front = resp.headers.get("front-token")
    if not access or not refresh:
        raise LoginError("Sign-in OK but tokens missing from response headers.")

    cookies = [
        _cookie(ACCESS_COOKIE, access),
        _cookie(REFRESH_COOKIE, refresh),
        _cookie(LAST_UPDATE_COOKIE, str(int(time.time() * 1000))),
    ]
    if front:
        cookies.append(_cookie(FRONT_TOKEN_COOKIE, front))

    # Carry any sticky LB cookie the backend set (improves refresh routing).
    for name, value in resp.cookies.items():
        if name.startswith("STICKY_SESSION_"):
            cookies.append(_cookie(name, value))

    return Session(cookies=cookies)
