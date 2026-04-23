"""GitHub OAuth + HttpOnly session cookie auth.

Auth is **enabled only when GITHUB_CLIENT_ID is set in the environment**. If it's
missing, the middleware passes everything through (dev-friendly default).

Env vars:
  GITHUB_CLIENT_ID         — from GitHub OAuth App (Settings → Developer settings → OAuth Apps)
  GITHUB_CLIENT_SECRET     — from the same OAuth App
  GITHUB_REDIRECT_URI      — e.g. http://localhost:5173/api/auth/github/callback
                             (must exactly match the Authorization callback URL on the OAuth App)
  ALLOWED_LOGINS           — comma-separated GitHub username allowlist (preferred; stable identifier)
  ALLOWED_EMAILS           — comma-separated email allowlist (used only if ALLOWED_LOGINS is empty)
                             empty + no ALLOWED_LOGINS = allow any GitHub user
  SESSION_SECRET           — HMAC key for signing session cookies (random ≥32 chars)
                             (falls back to backend/.secret.key contents if unset)
  COOKIE_SECURE            — "true"/"false"/"auto" (auto = on if redirect URI is https)
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
    return bool(os.environ.get("GITHUB_CLIENT_ID"))


def _secret() -> bytes:
    s = os.environ.get("SESSION_SECRET")
    if s:
        return s.encode()
    # Fall back to the Fernet key file if present (already machine-local, already a good random blob)
    key_path = Path(__file__).parent / ".secret.key"
    if key_path.exists():
        return key_path.read_bytes()
    raise RuntimeError("SESSION_SECRET (or backend/.secret.key) required when auth is enabled")


def allowed_logins() -> list[str]:
    raw = os.environ.get("ALLOWED_LOGINS", "")
    return [u.strip().lower() for u in raw.split(",") if u.strip()]


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
    return (os.environ.get("GITHUB_REDIRECT_URI") or "").startswith("https://")


def issue_session_cookie(resp: Response, login: str, email: Optional[str] = None) -> None:
    payload = {
        "login": login,
        "email": email or "",
        "exp": int(time.time()) + COOKIE_MAX_AGE,
        "iat": int(time.time()),
    }
    token = _sign(payload)
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
        return {"login": "local", "email": "local", "auth_disabled": True}
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return _verify(token)


def require_auth(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user


# ---------- GitHub OAuth HTTP helpers ----------

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


def build_github_consent_url(state: str, redirect_uri: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": os.environ["GITHUB_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
        "state": state,
        "allow_signup": "false",
    }
    return f"{GITHUB_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    with httpx.Client(timeout=15.0) as c:
        r = c.post(
            GITHUB_TOKEN_URL,
            data={
                "code": code,
                "client_id": os.environ["GITHUB_CLIENT_ID"],
                "client_secret": os.environ["GITHUB_CLIENT_SECRET"],
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        return r.json()


def fetch_user(access_token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=15.0) as c:
        r = c.get(GITHUB_USER_URL, headers=headers)
        r.raise_for_status()
        return r.json()


def fetch_primary_verified_email(access_token: str) -> Optional[str]:
    """Returns the user's primary verified email, or None if none exists."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=15.0) as c:
        r = c.get(GITHUB_EMAILS_URL, headers=headers)
        r.raise_for_status()
        emails = r.json() or []
    for e in emails:
        if e.get("primary") and e.get("verified"):
            return (e.get("email") or "").lower()
    # Fall back to any verified email
    for e in emails:
        if e.get("verified"):
            return (e.get("email") or "").lower()
    return None
