"""Google OAuth + HttpOnly session cookie auth.

Auth is **enabled only when GOOGLE_CLIENT_ID is set in the environment**. If it's
missing, the middleware passes everything through (dev-friendly default).

Env vars:
  GOOGLE_CLIENT_ID         — from Google Cloud Console OAuth client
  GOOGLE_CLIENT_SECRET     — from Google Cloud Console OAuth client
  GOOGLE_REDIRECT_URI      — e.g. http://localhost:5173/api/auth/google/callback
                             (must exactly match a redirect URI registered for the OAuth client)
  ALLOWED_EMAILS           — comma-separated allowlist; empty = allow any verified Google email
  SESSION_SECRET           — HMAC key for signing session cookies (random ≥32 chars)
                             (falls back to backend/.secret.key contents if unset)
  COOKIE_SECURE            — "true"/"false"/"auto" (auto = off in dev, on in prod detection)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import HTTPException, Request, Response


COOKIE_NAME = "dash_session"
STATE_COOKIE = "oauth_state"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def auth_enabled() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID"))


def _secret() -> bytes:
    s = os.environ.get("SESSION_SECRET")
    if s:
        return s.encode()
    # Fall back to the Fernet key file if present (already machine-local, already a good random blob)
    key_path = Path(__file__).parent / ".secret.key"
    if key_path.exists():
        return key_path.read_bytes()
    raise RuntimeError("SESSION_SECRET (or backend/.secret.key) required when auth is enabled")


def allowed_emails() -> list[str]:
    raw = os.environ.get("ALLOWED_EMAILS", "")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


# ---------- Signed session cookie ----------

def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64u_decode(s: str) -> bytes:
    padded = s + "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(padded)


def _sign(payload: dict) -> str:
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    b = _b64u_encode(data)
    sig = hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()
    return f"{b}.{sig}"


def _verify(token: str) -> Optional[dict]:
    try:
        b, sig = token.split(".", 1)
        expected = hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        data = json.loads(_b64u_decode(b))
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        return data
    except Exception:
        return None


def _cookie_secure_flag() -> bool:
    mode = os.environ.get("COOKIE_SECURE", "auto").lower()
    if mode == "true":
        return True
    if mode == "false":
        return False
    # auto: on if redirect URI is https, off otherwise
    return (os.environ.get("GOOGLE_REDIRECT_URI") or "").startswith("https://")


def issue_session_cookie(resp: Response, email: str) -> None:
    token = _sign({"email": email, "exp": int(time.time()) + COOKIE_MAX_AGE, "iat": int(time.time())})
    resp.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=_cookie_secure_flag(),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(resp: Response) -> None:
    resp.delete_cookie(COOKIE_NAME, path="/")


# ---------- Request helpers ----------

def current_user(request: Request) -> Optional[dict]:
    if not auth_enabled():
        return {"email": "local", "auth_disabled": True}
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return _verify(token)


def require_auth(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user


# ---------- Google OAuth HTTP helpers ----------

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def build_google_consent_url(state: str, redirect_uri: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
        "access_type": "online",
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    with httpx.Client(timeout=15.0) as c:
        r = c.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        r.raise_for_status()
        return r.json()


def fetch_userinfo(access_token: str) -> dict:
    with httpx.Client(timeout=15.0) as c:
        r = c.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        r.raise_for_status()
        return r.json()
