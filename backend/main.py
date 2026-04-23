import json
import os
import secrets
import time
from typing import Any, Dict, List, Optional

import httpx
import re
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

import auth as auth_module
import models
import schemas
from crypto import encrypt, decrypt
from database import Base, engine, get_db, SessionLocal

Base.metadata.create_all(bind=engine)


def _migrate_schema() -> None:
    """Add columns that were introduced after initial DB creation."""
    insp = inspect(engine)
    with engine.begin() as conn:
        if "providers" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("providers")}
            if "variables" not in cols:
                conn.execute(text("ALTER TABLE providers ADD COLUMN variables TEXT DEFAULT '{}'"))
            if "oauth_client_id" not in cols:
                conn.execute(text("ALTER TABLE providers ADD COLUMN oauth_client_id TEXT DEFAULT ''"))
            if "oauth_token_url" not in cols:
                conn.execute(text("ALTER TABLE providers ADD COLUMN oauth_token_url TEXT DEFAULT ''"))
            if "oauth_scope" not in cols:
                conn.execute(text("ALTER TABLE providers ADD COLUMN oauth_scope TEXT DEFAULT ''"))
            if "oauth_auth_style" not in cols:
                conn.execute(text("ALTER TABLE providers ADD COLUMN oauth_auth_style TEXT DEFAULT 'body'"))
            # LLM/AI cleanup (one-shot). Drop legacy LLM providers (cascades to endpoints).
            conn.execute(text("DELETE FROM providers WHERE kind = 'llm'"))
            # Try to drop the legacy LLM-only columns. SQLite ≥3.35 supports
            # ALTER TABLE … DROP COLUMN; older builds just get skipped.
            for col in ("default_model", "models"):
                if col in cols:
                    try:
                        conn.execute(text(f"ALTER TABLE providers DROP COLUMN {col}"))
                    except Exception:
                        pass
        if "history" in insp.get_table_names():
            conn.execute(text("DELETE FROM history WHERE kind = 'llm'"))
        # Old chat tables are gone from the ORM — drop them so they stop showing up.
        conn.execute(text("DROP TABLE IF EXISTS chat_messages"))
        conn.execute(text("DROP TABLE IF EXISTS chat_sessions"))
        if "endpoints" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("endpoints")}
            if "api_key_encrypted" not in cols:
                conn.execute(text("ALTER TABLE endpoints ADD COLUMN api_key_encrypted TEXT DEFAULT ''"))
            if "auth_mode" not in cols:
                conn.execute(text("ALTER TABLE endpoints ADD COLUMN auth_mode TEXT DEFAULT 'inherit'"))


_migrate_schema()


def _mask_key(encrypted: str) -> str:
    if not encrypted:
        return ""
    try:
        key = decrypt(encrypted)
    except Exception:
        return ""
    if len(key) <= 8:
        return "●●●●●●"
    return f"{key[:4]}…{key[-4:]}"


def _parse_variables(raw: Optional[str]) -> Dict[str, str]:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        if isinstance(val, dict):
            return {str(k): str(v) for k, v in val.items()}
    except Exception:
        pass
    return {}


_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


def _subst_str(s: str, vars: Dict[str, str]) -> str:
    if not s or not vars or "{{" not in s:
        return s
    return _VAR_RE.sub(lambda m: vars.get(m.group(1), m.group(0)), s)


def _subst_any(value, vars: Dict[str, str]):
    if not vars:
        return value
    if isinstance(value, str):
        return _subst_str(value, vars)
    if isinstance(value, list):
        return [_subst_any(x, vars) for x in value]
    if isinstance(value, dict):
        return {k: _subst_any(v, vars) for k, v in value.items()}
    return value

app = FastAPI(title="API Dashboard", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    """
    If GITHUB_CLIENT_ID is set, gate every /api/* route behind a valid session cookie.
    Exceptions: /health, /api/auth/*. Non-API paths (the frontend) are always served
    so the login page can render.
    """
    path = request.url.path
    if not auth_module.auth_enabled():
        return await call_next(request)
    if path == "/health" or path.startswith("/api/auth/"):
        return await call_next(request)
    if path.startswith("/api/"):
        user = auth_module.current_user(request)
        if not user:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return await call_next(request)


# ---------- Auth endpoints ----------

def _redirect_uri(request: Request) -> str:
    env = os.environ.get("GITHUB_REDIRECT_URI")
    if env:
        return env
    # Fallback: derive from incoming request. In production set the env var explicitly.
    return str(request.base_url).rstrip("/") + "/api/auth/github/callback"


@app.get("/api/auth/status")
def auth_status():
    return {"enabled": auth_module.auth_enabled()}


@app.get("/api/auth/me")
def auth_me(request: Request):
    user = auth_module.current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user


@app.get("/api/auth/github/start")
def auth_github_start(request: Request):
    if not auth_module.auth_enabled():
        raise HTTPException(400, "Auth is not configured (set GITHUB_CLIENT_ID)")
    state = secrets.token_urlsafe(24)
    redirect_uri = _redirect_uri(request)
    url = auth_module.build_github_consent_url(state, redirect_uri)
    resp = RedirectResponse(url)
    resp.set_cookie(auth_module.STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", path="/")
    return resp


@app.get("/api/auth/github/callback")
def auth_github_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if not auth_module.auth_enabled():
        raise HTTPException(400, "Auth is not configured")
    if error:
        raise HTTPException(400, f"OAuth error: {error}")
    if not code or not state:
        raise HTTPException(400, "Missing code or state")
    cookie_state = request.cookies.get(auth_module.STATE_COOKIE)
    if not cookie_state or not secrets.compare_digest(cookie_state, state):
        raise HTTPException(400, "State mismatch — possible CSRF")

    redirect_uri = _redirect_uri(request)
    try:
        tokens = auth_module.exchange_code_for_token(code, redirect_uri)
        access_token = tokens.get("access_token")
        if not access_token:
            raise HTTPException(502, f"GitHub token exchange failed: {tokens.get('error_description') or tokens}")
        user = auth_module.fetch_user(access_token)
        email = auth_module.fetch_primary_verified_email(access_token)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"GitHub token exchange failed: {exc}")

    login = (user.get("login") or "").lower()
    if not login:
        raise HTTPException(502, "GitHub did not return a login")

    allow_logins = auth_module.allowed_logins()
    allow_emails = auth_module.allowed_emails()
    if allow_logins:
        if login not in allow_logins:
            raise HTTPException(403, f"@{login} is not on the allowlist")
    elif allow_emails:
        if not email or email not in allow_emails:
            raise HTTPException(403, f"{email or '(no verified email)'} is not on the allowlist")
    # else: both empty → accept any GitHub user

    # Redirect back to the frontend root (works for both dev and prod)
    dest = os.environ.get("POST_LOGIN_REDIRECT", "/")
    resp = RedirectResponse(dest)
    auth_module.issue_session_cookie(resp, login, email)
    resp.delete_cookie(auth_module.STATE_COOKIE, path="/")
    return resp


@app.post("/api/auth/logout")
def auth_logout():
    resp = JSONResponse({"ok": True})
    auth_module.clear_session_cookie(resp)
    return resp


def _provider_to_out(p: models.Provider) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "kind": p.kind,
        "base_url": p.base_url,
        "auth_type": p.auth_type,
        "auth_header_name": p.auth_header_name,
        "auth_prefix": p.auth_prefix,
        "auth_query_param": p.auth_query_param,
        "extra_headers": p.extra_headers or "{}",
        "variables": getattr(p, "variables", None) or "{}",
        "oauth_client_id": getattr(p, "oauth_client_id", "") or "",
        "oauth_token_url": getattr(p, "oauth_token_url", "") or "",
        "oauth_scope": getattr(p, "oauth_scope", "") or "",
        "oauth_auth_style": getattr(p, "oauth_auth_style", "body") or "body",
        "enabled": p.enabled,
        "notes": p.notes or "",
        "has_api_key": bool(p.api_key_encrypted),
        "api_key_preview": _mask_key(p.api_key_encrypted or ""),
        "endpoints": [
            {
                "id": e.id,
                "provider_id": e.provider_id,
                "name": e.name,
                "method": e.method,
                "path": e.path,
                "description": e.description or "",
                "auth_mode": getattr(e, "auth_mode", "inherit") or "inherit",
                "has_api_key": bool(getattr(e, "api_key_encrypted", "") or ""),
                "api_key_preview": _mask_key(getattr(e, "api_key_encrypted", "") or ""),
            }
            for e in p.endpoints
        ],
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/providers", response_model=List[schemas.ProviderOut])
def list_providers(db: Session = Depends(get_db)):
    return [_provider_to_out(p) for p in db.query(models.Provider).order_by(models.Provider.name).all()]


@app.post("/api/providers", response_model=schemas.ProviderOut)
def create_provider(payload: schemas.ProviderCreate, db: Session = Depends(get_db)):
    if db.query(models.Provider).filter(models.Provider.name == payload.name).first():
        raise HTTPException(400, f"Provider '{payload.name}' already exists")
    provider = models.Provider(
        name=payload.name,
        kind=payload.kind,
        base_url=payload.base_url,
        auth_type=payload.auth_type,
        auth_header_name=payload.auth_header_name,
        auth_prefix=payload.auth_prefix,
        auth_query_param=payload.auth_query_param,
        extra_headers=payload.extra_headers or "{}",
        variables=payload.variables or "{}",
        oauth_client_id=payload.oauth_client_id,
        oauth_token_url=payload.oauth_token_url,
        oauth_scope=payload.oauth_scope,
        oauth_auth_style=payload.oauth_auth_style or "body",
        enabled=payload.enabled,
        notes=payload.notes,
        api_key_encrypted=encrypt(payload.api_key.strip()) if payload.api_key else "",
    )
    for e in payload.endpoints:
        data = e.model_dump()
        api_key = data.pop("api_key", None)
        ep = models.Endpoint(**data)
        if api_key:
            ep.api_key_encrypted = encrypt(api_key.strip())
        provider.endpoints.append(ep)
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return _provider_to_out(provider)


@app.get("/api/providers/{provider_id}", response_model=schemas.ProviderOut)
def get_provider(provider_id: int, db: Session = Depends(get_db)):
    p = db.get(models.Provider, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    return _provider_to_out(p)


@app.patch("/api/providers/{provider_id}", response_model=schemas.ProviderOut)
def update_provider(provider_id: int, payload: schemas.ProviderUpdate, db: Session = Depends(get_db)):
    p = db.get(models.Provider, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    data = payload.model_dump(exclude_unset=True)
    if "api_key" in data:
        new_key = data.pop("api_key")
        if new_key is None or new_key == "":
            p.api_key_encrypted = ""
        else:
            p.api_key_encrypted = encrypt(new_key.strip())
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _provider_to_out(p)


@app.post("/api/providers/{provider_id}/ping")
def ping_provider(provider_id: int, db: Session = Depends(get_db)):
    p = db.get(models.Provider, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    headers: dict = {}
    params: dict = {}
    try:
        extra = json.loads(p.extra_headers or "{}")
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k.startswith("hmac_") or k.startswith("jwt_"):
                    continue
                headers[k] = str(v)
    except Exception:
        pass

    vars = _parse_variables(getattr(p, "variables", None))
    base = _subst_str((p.base_url or "").rstrip("/"), vars)
    headers = {k: _subst_str(str(v), vars) for k, v in headers.items()}
    _build_auth(p, headers, params, method="GET", url=base)
    # Best-effort probe: first endpoint if configured, otherwise the base URL.
    ep = p.endpoints[0] if p.endpoints else None
    if ep:
        path = ep.path
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{base}{'' if path.startswith('/') or not path else '/'}{path}" if base else path
        method = (ep.method or "GET").upper()
    else:
        url = base
        method = "GET"
    if not url:
        return {"ok": False, "status_code": 0, "message": "No URL to probe"}
    url = _subst_str(url, vars)
    start = time.time()
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            r = client.request(method, url, headers=headers, params=params)
    except httpx.HTTPError as exc:
        return {"ok": False, "status_code": 0, "latency_ms": int((time.time() - start) * 1000), "message": str(exc), "url": url}
    msg = "OK" if r.is_success else f"{r.status_code} {r.reason_phrase}"
    return {
        "ok": r.is_success,
        "status_code": r.status_code,
        "latency_ms": int((time.time() - start) * 1000),
        "message": msg,
        "url": url,
    }


@app.delete("/api/providers/{provider_id}")
def delete_provider(provider_id: int, db: Session = Depends(get_db)):
    p = db.get(models.Provider, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    db.delete(p)
    db.commit()
    return {"ok": True}


def _endpoint_to_out(e: models.Endpoint) -> dict:
    return {
        "id": e.id,
        "provider_id": e.provider_id,
        "name": e.name,
        "method": e.method,
        "path": e.path,
        "description": e.description or "",
        "auth_mode": getattr(e, "auth_mode", "inherit") or "inherit",
        "has_api_key": bool(getattr(e, "api_key_encrypted", "") or ""),
        "api_key_preview": _mask_key(getattr(e, "api_key_encrypted", "") or ""),
    }


@app.post("/api/providers/{provider_id}/endpoints", response_model=schemas.EndpointOut)
def add_endpoint(provider_id: int, payload: schemas.EndpointCreate, db: Session = Depends(get_db)):
    p = db.get(models.Provider, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    data = payload.model_dump()
    api_key = data.pop("api_key", None)
    e = models.Endpoint(provider_id=provider_id, **data)
    if api_key:
        e.api_key_encrypted = encrypt(api_key.strip())
    db.add(e)
    db.commit()
    db.refresh(e)
    return _endpoint_to_out(e)


@app.patch("/api/endpoints/{endpoint_id}", response_model=schemas.EndpointOut)
def update_endpoint(endpoint_id: int, payload: schemas.EndpointCreate, db: Session = Depends(get_db)):
    e = db.get(models.Endpoint, endpoint_id)
    if not e:
        raise HTTPException(404, "Endpoint not found")
    data = payload.model_dump()
    api_key = data.pop("api_key", None)
    for k, v in data.items():
        setattr(e, k, v)
    if api_key is not None:
        if api_key == "":
            e.api_key_encrypted = ""
        else:
            e.api_key_encrypted = encrypt(api_key.strip())
    db.commit()
    db.refresh(e)
    return _endpoint_to_out(e)


@app.delete("/api/endpoints/{endpoint_id}")
def delete_endpoint(endpoint_id: int, db: Session = Depends(get_db)):
    e = db.get(models.Endpoint, endpoint_id)
    if not e:
        raise HTTPException(404, "Endpoint not found")
    db.delete(e)
    db.commit()
    return {"ok": True}


def _history_to_out(h: models.HistoryEntry) -> dict:
    def _safe_json(raw: str) -> dict:
        try:
            val = json.loads(raw or "{}")
            return val if isinstance(val, dict) else {"value": val}
        except Exception:
            return {}
    return {
        "id": h.id,
        "kind": h.kind,
        "provider_id": h.provider_id,
        "provider_name": h.provider_name or "",
        "label": h.label or "",
        "status_code": h.status_code or 0,
        "ok": bool(h.ok),
        "latency_ms": h.latency_ms or 0,
        "created_at": (h.created_at.isoformat() if h.created_at else ""),
        "request": _safe_json(h.request_json),
        "response": _safe_json(h.response_json),
    }


def _preset_to_out(p: models.RequestPreset) -> dict:
    def _json_or(d, default):
        try: return json.loads(d) if d else default
        except Exception: return default
    body = None
    if p.body_json:
        try: body = json.loads(p.body_json)
        except Exception: body = p.body_json
    return {
        "id": p.id,
        "name": p.name,
        "provider_id": p.provider_id,
        "endpoint_id": p.endpoint_id,
        "method": p.method or "GET",
        "url": p.url or "",
        "path": p.path or "",
        "headers": _json_or(p.headers_json, {}),
        "query": _json_or(p.query_json, {}),
        "body": body,
        "body_type": p.body_type or "json",
        "notes": p.notes or "",
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "updated_at": p.updated_at.isoformat() if p.updated_at else "",
    }


@app.get("/api/presets", response_model=List[schemas.PresetOut])
def list_presets(db: Session = Depends(get_db)):
    rows = db.query(models.RequestPreset).order_by(models.RequestPreset.updated_at.desc()).all()
    return [_preset_to_out(p) for p in rows]


@app.post("/api/presets", response_model=schemas.PresetOut)
def create_preset(payload: schemas.PresetCreate, db: Session = Depends(get_db)):
    p = models.RequestPreset(
        name=payload.name,
        provider_id=payload.provider_id,
        endpoint_id=payload.endpoint_id,
        method=(payload.method or "GET").upper(),
        url=payload.url or "",
        path=payload.path or "",
        headers_json=json.dumps(payload.headers or {}),
        query_json=json.dumps(payload.query or {}),
        body_json=json.dumps(payload.body) if payload.body is not None else "",
        body_type=payload.body_type or "json",
        notes=payload.notes or "",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _preset_to_out(p)


@app.patch("/api/presets/{preset_id}", response_model=schemas.PresetOut)
def update_preset(preset_id: int, payload: schemas.PresetUpdate, db: Session = Depends(get_db)):
    p = db.get(models.RequestPreset, preset_id)
    if not p:
        raise HTTPException(404, "Preset not found")
    data = payload.model_dump(exclude_unset=True)
    if "headers" in data: p.headers_json = json.dumps(data.pop("headers") or {})
    if "query" in data: p.query_json = json.dumps(data.pop("query") or {})
    if "body" in data:
        body = data.pop("body")
        p.body_json = json.dumps(body) if body is not None else ""
    if "method" in data and data["method"]: p.method = data["method"].upper()
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _preset_to_out(p)


@app.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: int, db: Session = Depends(get_db)):
    p = db.get(models.RequestPreset, preset_id)
    if not p:
        raise HTTPException(404, "Preset not found")
    db.delete(p)
    db.commit()
    return {"ok": True}


@app.get("/api/history", response_model=List[schemas.HistoryOut])
def list_history(
    limit: int = 200,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.HistoryEntry).order_by(models.HistoryEntry.created_at.desc())
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            (models.HistoryEntry.provider_name.ilike(like))
            | (models.HistoryEntry.label.ilike(like))
            | (models.HistoryEntry.request_json.ilike(like))
            | (models.HistoryEntry.response_json.ilike(like))
        )
    return [_history_to_out(h) for h in query.limit(max(1, min(limit, 1000))).all()]


@app.delete("/api/history/{history_id}")
def delete_history_item(history_id: int, db: Session = Depends(get_db)):
    h = db.get(models.HistoryEntry, history_id)
    if not h:
        raise HTTPException(404, "History entry not found")
    db.delete(h)
    db.commit()
    return {"ok": True}


@app.delete("/api/history")
def clear_history(db: Session = Depends(get_db)):
    db.query(models.HistoryEntry).delete()
    db.commit()
    return {"ok": True}


def _build_auth(
    provider: models.Provider,
    headers: dict,
    params: dict,
    endpoint: Optional[models.Endpoint] = None,
    *,
    method: str = "GET",
    url: str = "",
    body_bytes: bytes = b"",
) -> None:
    mode = (getattr(endpoint, "auth_mode", None) or "inherit") if endpoint else "inherit"
    if mode == "none":
        return
    if provider.auth_type == "none":
        return
    if mode == "override":
        key_enc = getattr(endpoint, "api_key_encrypted", "") or ""
    else:
        key_enc = provider.api_key_encrypted
    if not key_enc:
        return
    key = decrypt(key_enc)
    if provider.auth_type == "bearer":
        prefix = (provider.auth_prefix or "Bearer").strip()
        headers["Authorization"] = f"{prefix} {key}" if prefix else key
    elif provider.auth_type == "header":
        name = provider.auth_header_name or "Authorization"
        prefix = (provider.auth_prefix or "").strip()
        headers[name] = f"{prefix} {key}" if prefix else key
    elif provider.auth_type == "query":
        params[provider.auth_query_param or "api_key"] = key
    elif provider.auth_type == "basic":
        import base64 as _b64
        # key is stored as "user:pass"
        headers["Authorization"] = "Basic " + _b64.b64encode(key.encode()).decode()
    elif provider.auth_type == "oauth2_cc":
        token = _oauth_cc_token(provider, client_secret=key)
        headers["Authorization"] = f"Bearer {token}"
    elif provider.auth_type == "hmac":
        _apply_hmac(provider, headers, key, method=method, url=url, body=body_bytes)
    elif provider.auth_type == "jwt_hs":
        _apply_jwt_hs(provider, headers, key)


def _apply_hmac(provider, headers, secret, *, method, url, body):
    """
    HMAC-SHA256 signing. Canonical string: {method}\\n{path}\\n{body_sha256_hex}\\n{timestamp}
    Inserts: X-Timestamp, X-Signature (or configured names via extra_headers keys "hmac_ts_header" / "hmac_sig_header").
    Configurable via provider.notes? No — use extra_headers for override keys.
    """
    import hashlib, hmac as _hmac, time as _time
    from urllib.parse import urlsplit
    try:
        extra = json.loads(provider.extra_headers or "{}")
    except Exception:
        extra = {}
    ts_header = extra.get("hmac_ts_header", "X-Timestamp")
    sig_header = extra.get("hmac_sig_header", "X-Signature")
    sig_prefix = extra.get("hmac_sig_prefix", "")
    path = urlsplit(url).path or "/"
    ts = str(int(_time.time()))
    body_hash = hashlib.sha256(body or b"").hexdigest()
    canonical = f"{method.upper()}\n{path}\n{body_hash}\n{ts}"
    sig = _hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    headers[ts_header] = ts
    headers[sig_header] = f"{sig_prefix}{sig}" if sig_prefix else sig


def _apply_jwt_hs(provider, headers, secret):
    """HS256 JWT. Claims defined in extra_headers['jwt_claims'] (dict) — standard claims like iss, sub, aud, exp_seconds."""
    import hashlib, hmac as _hmac, base64, time as _time
    try:
        extra = json.loads(provider.extra_headers or "{}")
    except Exception:
        extra = {}
    claims = dict(extra.get("jwt_claims") or {})
    exp_seconds = int(extra.get("jwt_exp_seconds", 300))
    now = int(_time.time())
    claims.setdefault("iat", now)
    claims["exp"] = now + exp_seconds
    header_part = {"alg": "HS256", "typ": "JWT"}

    def _b64(d):
        return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).rstrip(b"=").decode()

    h = _b64(header_part)
    p = _b64(claims)
    signing_input = f"{h}.{p}".encode()
    sig = _hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    token = f"{h}.{p}.{sig_b64}"
    prefix = (provider.auth_prefix or "Bearer").strip()
    name = provider.auth_header_name or "Authorization"
    headers[name] = f"{prefix} {token}" if prefix else token


# In-memory OAuth 2.0 client-credentials token cache, keyed by provider.id.
# Value: {"access_token": str, "expires_at": float epoch seconds}.
# Restart drops the cache; tokens refetch on next request — acceptable tradeoff.
_oauth_cc_cache: Dict[int, Dict[str, Any]] = {}


def _oauth_cc_token(provider, *, client_secret: str) -> str:
    """Fetch (and cache) an OAuth 2.0 client-credentials access token.

    Refreshes 30s before expiry to avoid edge-of-expiry 401s.
    Raises HTTPException(502) if the token endpoint returns anything unusable.
    """
    import time as _time
    now = _time.time()
    cached = _oauth_cc_cache.get(provider.id)
    if cached and cached["expires_at"] - 30 > now:
        return cached["access_token"]

    token_url = (provider.oauth_token_url or "").strip()
    if not token_url:
        raise HTTPException(400, "OAuth provider missing token URL")
    client_id = (provider.oauth_client_id or "").strip()
    if not client_id:
        raise HTTPException(400, "OAuth provider missing client_id")

    data = {"grant_type": "client_credentials"}
    if provider.oauth_scope:
        data["scope"] = provider.oauth_scope
    auth = None
    if (provider.oauth_auth_style or "body") == "basic":
        auth = (client_id, client_secret)
    else:
        data["client_id"] = client_id
        data["client_secret"] = client_secret

    try:
        with httpx.Client(timeout=15.0) as cli:
            resp = cli.post(token_url, data=data, auth=auth, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"OAuth token fetch failed: {e}")
    if resp.status_code >= 400:
        raise HTTPException(502, f"OAuth token endpoint returned {resp.status_code}: {resp.text[:300]}")
    try:
        payload = resp.json()
    except Exception:
        raise HTTPException(502, "OAuth token endpoint returned non-JSON response")
    token = payload.get("access_token")
    if not token:
        raise HTTPException(502, f"OAuth token response missing access_token: {payload}")
    try:
        expires_in = int(payload.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires_in = 3600
    _oauth_cc_cache[provider.id] = {
        "access_token": token,
        "expires_at": now + max(60, expires_in),
    }
    return token


def _log_history(
    db: Session,
    *,
    kind: str,
    provider: Optional[models.Provider],
    label: str,
    request_dict: dict,
    response: schemas.InvokeResponse,
) -> None:
    try:
        entry = models.HistoryEntry(
            kind=kind,
            provider_id=provider.id if provider else None,
            provider_name=provider.name if provider else "",
            label=label or "",
            status_code=response.status_code,
            ok=response.ok,
            latency_ms=response.latency_ms,
            request_json=json.dumps(request_dict, default=str),
            response_json=json.dumps(response.model_dump(), default=str),
        )
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()


def _mask_headers(headers: dict) -> dict:
    masked = {}
    sensitive = {"authorization", "x-api-key", "api-key", "x-auth-token"}
    for k, v in headers.items():
        if k.lower() in sensitive and v:
            parts = str(v).split(" ", 1)
            if len(parts) == 2 and len(parts[1]) > 8:
                masked[k] = f"{parts[0]} {parts[1][:4]}…{parts[1][-4:]}"
            elif len(str(v)) > 8:
                masked[k] = f"{str(v)[:4]}…{str(v)[-4:]}"
            else:
                masked[k] = "●●●●"
        else:
            masked[k] = str(v)
    return masked


def _parse_response(r: httpx.Response) -> schemas.InvokeResponse:
    ct = r.headers.get("content-type", "")
    body: object
    try:
        if "application/json" in ct:
            body = r.json()
        else:
            text = r.text
            body = text[:200_000]
    except Exception:
        body = r.text[:200_000]
    return schemas.InvokeResponse(
        ok=r.is_success,
        status_code=r.status_code,
        latency_ms=0,
        headers=dict(r.headers),
        body=body,
    )


@app.post("/api/invoke/http", response_model=schemas.InvokeResponse)
def invoke_http(payload: schemas.HTTPInvokeRequest, db: Session = Depends(get_db)):
    headers = {k: v for k, v in payload.headers.items()}
    params = {k: v for k, v in payload.query.items()}
    url: str = ""
    method: str = (payload.method or "").upper()
    provider: Optional[models.Provider] = None
    endpoint: Optional[models.Endpoint] = None

    if payload.endpoint_id:
        endpoint = db.get(models.Endpoint, payload.endpoint_id)
        if not endpoint:
            raise HTTPException(400, "Endpoint not found")
        provider = endpoint.provider
        if not provider or not provider.enabled:
            raise HTTPException(400, "Provider for endpoint is disabled")
        method = method or (endpoint.method or "GET").upper()
        path = endpoint.path or ""
        base = (provider.base_url or "").rstrip("/")
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{base}{'' if path.startswith('/') or not path else '/'}{path}" if base else path
    elif payload.provider_id:
        provider = db.get(models.Provider, payload.provider_id)
        if not provider or not provider.enabled:
            raise HTTPException(400, "Provider not found or disabled")
        base = (provider.base_url or "").rstrip("/")
        path = payload.path or payload.url or ""
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{base}{'' if path.startswith('/') or not path else '/'}{path}" if base else path
    else:
        if not payload.url:
            raise HTTPException(400, "url is required when no provider/endpoint is selected")
        url = payload.url

    if provider:
        try:
            extra = json.loads(provider.extra_headers or "{}")
            if isinstance(extra, dict):
                for k, v in extra.items():
                    # Skip internal auth-helper config keys, not HTTP headers
                    if k.startswith("hmac_") or k.startswith("jwt_"):
                        continue
                    headers.setdefault(k, str(v))
        except Exception:
            pass

    # Variable substitution FIRST — signatures must be computed over final values
    vars = _parse_variables(getattr(provider, "variables", None)) if provider else {}
    if vars:
        url = _subst_str(url, vars)
        headers = {k: _subst_str(str(v), vars) for k, v in headers.items()}
        params = {k: _subst_str(str(v), vars) for k, v in params.items()}

    if not url:
        raise HTTPException(400, "Could not resolve a URL")
    if not method:
        method = "GET"

    body_substituted = _subst_any(payload.body, vars) if vars else payload.body

    # Compute the exact body bytes httpx will send, so HMAC signs what the server receives
    body_bytes = b""
    if body_substituted is not None and method not in {"GET", "HEAD"}:
        try:
            if payload.body_type == "json":
                body_bytes = json.dumps(body_substituted).encode()
            elif payload.body_type == "form":
                from urllib.parse import urlencode
                if isinstance(body_substituted, dict):
                    body_bytes = urlencode(body_substituted, doseq=True).encode()
                else:
                    body_bytes = str(body_substituted).encode()
            else:
                body_bytes = str(body_substituted).encode()
        except Exception:
            body_bytes = b""

    if provider:
        _build_auth(provider, headers, params, endpoint=endpoint, method=method or "GET", url=url, body_bytes=body_bytes)

    req_kwargs: dict = {"headers": headers, "params": params}
    if body_substituted is not None and method not in {"GET", "HEAD"}:
        if payload.body_type == "json":
            req_kwargs["json"] = body_substituted
        elif payload.body_type == "form":
            req_kwargs["data"] = body_substituted
        else:
            req_kwargs["content"] = str(body_substituted)

    echo = schemas.RequestEcho(
        method=method, url=url,
        headers=_mask_headers(headers), query=params,
        body=body_substituted if method not in {"GET", "HEAD"} else None,
    )

    http_label = f"{method} {url}"
    start = time.time()
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            r = client.request(method, url, **req_kwargs)
    except httpx.HTTPError as exc:
        err_out = schemas.InvokeResponse(
            ok=False, status_code=0, latency_ms=int((time.time() - start) * 1000),
            headers={}, body=None, error=str(exc), request=echo,
        )
        _log_history(
            db, kind="http", provider=provider, label=http_label,
            request_dict=echo.model_dump(), response=err_out,
        )
        return err_out
    latency = int((time.time() - start) * 1000)
    out = _parse_response(r)
    out.latency_ms = latency
    out.request = echo
    _log_history(
        db, kind="http", provider=provider, label=http_label,
        request_dict=echo.model_dump(), response=out,
    )
    return out


@app.post("/api/invoke/graphql", response_model=schemas.InvokeResponse)
def invoke_graphql(payload: schemas.GraphQLInvokeRequest, db: Session = Depends(get_db)):
    provider = db.get(models.Provider, payload.provider_id)
    if not provider or not provider.enabled:
        raise HTTPException(400, "Provider not found or disabled")
    if provider.kind != "graphql":
        raise HTTPException(400, f"Provider '{provider.name}' is not a GraphQL provider")

    vars = _parse_variables(getattr(provider, "variables", None))
    url = _subst_str((provider.base_url or "").strip(), vars)
    if not url:
        raise HTTPException(400, "Provider has no base URL configured")

    body_obj: Dict[str, Any] = {"query": payload.query}
    if payload.variables:
        body_obj["variables"] = payload.variables
    if payload.operation_name:
        body_obj["operationName"] = payload.operation_name

    headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        extra = json.loads(provider.extra_headers or "{}")
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k.startswith("hmac_") or k.startswith("jwt_"):
                    continue
                headers.setdefault(k, str(v))
    except Exception:
        pass
    headers = {k: _subst_str(str(v), vars) for k, v in headers.items()}

    body_bytes = json.dumps(body_obj).encode()
    _build_auth(provider, headers, {}, method="POST", url=url, body_bytes=body_bytes)

    echo = schemas.RequestEcho(
        method="POST", url=url,
        headers=_mask_headers(headers), query={},
        body=body_obj,
    )

    # Label the history row with the operation name or the first line of the query
    op = payload.operation_name or (payload.query.strip().split("\n", 1)[0][:80] if payload.query else "")
    label = f"{provider.name} · {op}" if op else provider.name

    start = time.time()
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as cli:
            r = cli.post(url, headers=headers, json=body_obj)
    except httpx.HTTPError as exc:
        err_out = schemas.InvokeResponse(
            ok=False, status_code=0, latency_ms=int((time.time() - start) * 1000),
            headers={}, body=None, error=str(exc), request=echo,
        )
        _log_history(
            db, kind="graphql", provider=provider, label=label,
            request_dict=echo.model_dump(), response=err_out,
        )
        return err_out
    latency = int((time.time() - start) * 1000)
    out = _parse_response(r)
    out.latency_ms = latency
    out.request = echo
    # GraphQL 200 with { "errors": [...] } is still a functional error — surface that.
    if out.ok and isinstance(out.body, dict) and out.body.get("errors"):
        out.error = "; ".join(str(e.get("message", e)) for e in out.body["errors"][:3])
    _log_history(
        db, kind="graphql", provider=provider, label=label,
        request_dict=echo.model_dump(), response=out,
    )
    return out



# ---------- Export / Import ----------

@app.get("/api/config/export")
def export_config(include_keys: bool = True, db: Session = Depends(get_db)):
    out = {"version": 1, "providers": []}
    for p in db.query(models.Provider).all():
        prov = {
            "name": p.name,
            "kind": p.kind,
            "base_url": p.base_url,
            "auth_type": p.auth_type,
            "auth_header_name": p.auth_header_name,
            "auth_prefix": p.auth_prefix,
            "auth_query_param": p.auth_query_param,
            "extra_headers": p.extra_headers or "{}",
            "variables": getattr(p, "variables", None) or "{}",
            "enabled": p.enabled,
            "notes": p.notes or "",
            "endpoints": [
                {
                    "name": e.name, "method": e.method, "path": e.path,
                    "description": e.description or "",
                    "auth_mode": getattr(e, "auth_mode", "inherit") or "inherit",
                    **({"api_key": decrypt(getattr(e, "api_key_encrypted", "") or "")} if include_keys and getattr(e, "api_key_encrypted", None) else {}),
                }
                for e in p.endpoints
            ],
        }
        if include_keys and p.api_key_encrypted:
            try:
                prov["api_key"] = decrypt(p.api_key_encrypted)
            except Exception:
                pass
        out["providers"].append(prov)
    return out


def _import_openapi(spec: dict) -> dict:
    servers = spec.get("servers") or []
    base_url = (servers[0].get("url") if servers and isinstance(servers[0], dict) else "") or ""
    info = spec.get("info") or {}
    name = info.get("title") or "OpenAPI import"
    endpoints = []
    paths = spec.get("paths") or {}
    for path, ops in paths.items():
        if not isinstance(ops, dict):
            continue
        for method, op in ops.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
                continue
            label = (op.get("summary") if isinstance(op, dict) else None) or f"{method.upper()} {path}"
            endpoints.append({
                "name": label[:80],
                "method": method.upper(),
                "path": path,
                "description": (op.get("description") if isinstance(op, dict) else "") or "",
            })
    return {"name": name, "kind": "http", "base_url": base_url, "endpoints": endpoints}


def _import_postman(collection: dict) -> dict:
    info = collection.get("info") or {}
    name = info.get("name") or "Postman import"
    base_url = ""
    endpoints = []

    def _walk(items):
        for it in items or []:
            if it.get("item"):
                _walk(it["item"])
            req = it.get("request")
            if isinstance(req, dict):
                method = (req.get("method") or "GET").upper()
                url = req.get("url")
                raw_url = ""
                if isinstance(url, dict):
                    raw_url = url.get("raw") or ""
                elif isinstance(url, str):
                    raw_url = url
                endpoints.append({
                    "name": (it.get("name") or f"{method} {raw_url}")[:80],
                    "method": method,
                    "path": raw_url,
                    "description": it.get("description") or "",
                })

    _walk(collection.get("item") or [])
    return {"name": name, "kind": "http", "base_url": base_url, "endpoints": endpoints}


def _import_har(har: dict) -> dict:
    entries = (har.get("log") or {}).get("entries") or []
    if not entries:
        return {"name": "HAR import", "kind": "http", "base_url": "", "endpoints": []}
    from urllib.parse import urlsplit
    # Pick the most common origin as base_url
    origins = {}
    rows = []
    for e in entries:
        req = e.get("request") or {}
        u = req.get("url")
        if not u:
            continue
        sp = urlsplit(u)
        origin = f"{sp.scheme}://{sp.netloc}"
        origins[origin] = origins.get(origin, 0) + 1
        rows.append({"method": (req.get("method") or "GET").upper(), "url": u, "path": sp.path + (f"?{sp.query}" if sp.query else "")})
    base_url = max(origins.items(), key=lambda kv: kv[1])[0] if origins else ""
    endpoints = []
    for r in rows[:50]:
        # Only include endpoints that share the dominant origin; use relative path
        sp = urlsplit(r["url"])
        path = r["path"] if f"{sp.scheme}://{sp.netloc}" == base_url else r["url"]
        endpoints.append({
            "name": f"{r['method']} {path[:60]}",
            "method": r["method"],
            "path": path,
            "description": "",
        })
    return {"name": "HAR import", "kind": "http", "base_url": base_url, "endpoints": endpoints}


@app.post("/api/config/import-spec")
def import_spec(payload: Dict[str, Any], db: Session = Depends(get_db)):
    """Auto-detect OpenAPI, Postman collection v2.1, or HAR and create a provider."""
    spec = payload or {}
    if not isinstance(spec, dict):
        raise HTTPException(400, "Expected a JSON object")
    detected = None
    if "openapi" in spec or "swagger" in spec:
        result = _import_openapi(spec); detected = "openapi"
    elif isinstance(spec.get("info"), dict) and "item" in spec:
        result = _import_postman(spec); detected = "postman"
    elif isinstance(spec.get("log"), dict):
        result = _import_har(spec); detected = "har"
    else:
        raise HTTPException(400, "Unrecognized format. Expected OpenAPI 3.x, Postman 2.1, or HAR.")

    # Deduplicate provider name
    base_name = result["name"]
    name = base_name
    n = 2
    while db.query(models.Provider).filter(models.Provider.name == name).first():
        name = f"{base_name} ({n})"
        n += 1

    provider = models.Provider(
        name=name,
        kind=result["kind"],
        base_url=result["base_url"],
        auth_type="none",
        enabled=True,
    )
    for e in result["endpoints"]:
        provider.endpoints.append(models.Endpoint(
            name=e["name"], method=e["method"], path=e["path"], description=e.get("description", "")
        ))
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return {"ok": True, "detected": detected, "provider_id": provider.id, "endpoint_count": len(result["endpoints"])}


@app.post("/api/config/import")
def import_config(payload: Dict[str, Any], db: Session = Depends(get_db)):
    created = 0
    skipped = 0
    providers = (payload or {}).get("providers") or []
    for prov in providers:
        name = (prov or {}).get("name") or ""
        if not name:
            skipped += 1
            continue
        # LLM providers are no longer supported — silently drop them on import.
        if (prov or {}).get("kind") == "llm":
            skipped += 1
            continue
        exists = db.query(models.Provider).filter(models.Provider.name == name).first()
        if exists:
            skipped += 1
            continue
        p = models.Provider(
            name=name,
            kind=prov.get("kind", "http"),
            base_url=prov.get("base_url", ""),
            auth_type=prov.get("auth_type", "bearer"),
            auth_header_name=prov.get("auth_header_name", "Authorization"),
            auth_prefix=prov.get("auth_prefix", "Bearer "),
            auth_query_param=prov.get("auth_query_param", ""),
            extra_headers=prov.get("extra_headers", "{}") or "{}",
            variables=prov.get("variables", "{}") or "{}",
            enabled=bool(prov.get("enabled", True)),
            notes=prov.get("notes", ""),
            api_key_encrypted=encrypt(str(prov.get("api_key", "")).strip()) if prov.get("api_key") else "",
        )
        for e in prov.get("endpoints") or []:
            ep = models.Endpoint(
                name=e.get("name", ""),
                method=e.get("method", "GET"),
                path=e.get("path", ""),
                description=e.get("description", ""),
                auth_mode=e.get("auth_mode", "inherit"),
                api_key_encrypted=encrypt(str(e.get("api_key", "")).strip()) if e.get("api_key") else "",
            )
            p.endpoints.append(ep)
        db.add(p)
        created += 1
    db.commit()
    return {"ok": True, "created": created, "skipped": skipped}


# ---------- Webhook receiver ----------
#
# Inbound HTTP landing zone — external services POST to /hook/<slug> and we
# record the request so the user can inspect it. Management APIs live under
# /api/webhooks. The /hook/* path is deliberately outside /api/ so the
# authentication middleware doesn't block inbound webhooks.

_WEBHOOK_MAX_BODY_BYTES = 64 * 1024  # truncate anything larger — webhooks are usually small
_WEBHOOK_MAX_EVENTS_PER_HOOK = 500   # hard cap so an abusive sender can't fill the DB


def _webhook_to_out(w: models.Webhook) -> dict:
    evs = w.events or []
    last = evs[0].received_at if evs else None
    return {
        "id": w.id,
        "slug": w.slug,
        "name": w.name or "",
        "notes": w.notes or "",
        "enabled": bool(w.enabled),
        "created_at": w.created_at.isoformat() if w.created_at else "",
        "event_count": len(evs),
        "last_event_at": last.isoformat() if last else None,
    }


def _webhook_event_to_out(e: models.WebhookEvent) -> dict:
    try:
        headers = json.loads(e.headers_json or "{}")
    except Exception:
        headers = {}
    return {
        "id": e.id,
        "webhook_id": e.webhook_id,
        "method": e.method or "",
        "path": e.path or "",
        "query_string": e.query_string or "",
        "headers": headers if isinstance(headers, dict) else {},
        "body": e.body_text or "",
        "content_type": e.content_type or "",
        "source_ip": e.source_ip or "",
        "received_at": e.received_at.isoformat() if e.received_at else "",
    }


@app.get("/api/webhooks", response_model=List[schemas.WebhookOut])
def list_webhooks(db: Session = Depends(get_db)):
    return [_webhook_to_out(w) for w in db.query(models.Webhook).order_by(models.Webhook.created_at.desc()).all()]


@app.post("/api/webhooks", response_model=schemas.WebhookOut)
def create_webhook(payload: schemas.WebhookCreate, db: Session = Depends(get_db)):
    # Generate a URL-safe slug; retry on the astronomically unlikely collision.
    for _ in range(5):
        slug = secrets.token_urlsafe(9).replace("_", "-").replace("-", "")[:12].lower() or secrets.token_hex(6)
        if not db.query(models.Webhook).filter(models.Webhook.slug == slug).first():
            break
    else:
        raise HTTPException(500, "Could not allocate a unique webhook slug")
    w = models.Webhook(slug=slug, name=payload.name or "", notes=payload.notes or "", enabled=True)
    db.add(w)
    db.commit()
    db.refresh(w)
    return _webhook_to_out(w)


@app.patch("/api/webhooks/{webhook_id}", response_model=schemas.WebhookOut)
def update_webhook(webhook_id: int, payload: schemas.WebhookUpdate, db: Session = Depends(get_db)):
    w = db.get(models.Webhook, webhook_id)
    if not w:
        raise HTTPException(404, "Webhook not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
    db.commit()
    db.refresh(w)
    return _webhook_to_out(w)


@app.delete("/api/webhooks/{webhook_id}")
def delete_webhook(webhook_id: int, db: Session = Depends(get_db)):
    w = db.get(models.Webhook, webhook_id)
    if not w:
        raise HTTPException(404, "Webhook not found")
    db.delete(w)
    db.commit()
    return {"ok": True}


@app.get("/api/webhooks/{webhook_id}/events", response_model=List[schemas.WebhookEventOut])
def list_webhook_events(webhook_id: int, limit: int = 100, db: Session = Depends(get_db)):
    w = db.get(models.Webhook, webhook_id)
    if not w:
        raise HTTPException(404, "Webhook not found")
    events = (
        db.query(models.WebhookEvent)
        .filter(models.WebhookEvent.webhook_id == webhook_id)
        .order_by(models.WebhookEvent.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [_webhook_event_to_out(e) for e in events]


@app.delete("/api/webhooks/{webhook_id}/events")
def clear_webhook_events(webhook_id: int, db: Session = Depends(get_db)):
    w = db.get(models.Webhook, webhook_id)
    if not w:
        raise HTTPException(404, "Webhook not found")
    db.query(models.WebhookEvent).filter(models.WebhookEvent.webhook_id == webhook_id).delete()
    db.commit()
    return {"ok": True}


@app.delete("/api/webhook-events/{event_id}")
def delete_webhook_event(event_id: int, db: Session = Depends(get_db)):
    e = db.get(models.WebhookEvent, event_id)
    if not e:
        raise HTTPException(404, "Event not found")
    db.delete(e)
    db.commit()
    return {"ok": True}


async def _record_webhook(request: Request, slug: str, extra_path: str, db: Session):
    w = db.query(models.Webhook).filter(models.Webhook.slug == slug).first()
    if not w or not w.enabled:
        raise HTTPException(404, "Unknown webhook")

    raw = await request.body()
    truncated = False
    if len(raw) > _WEBHOOK_MAX_BODY_BYTES:
        raw = raw[:_WEBHOOK_MAX_BODY_BYTES]
        truncated = True
    try:
        body_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        import base64 as _b64
        body_text = "base64:" + _b64.b64encode(raw).decode()
    if truncated:
        body_text += "\n…[truncated]"

    headers = {k: v for k, v in request.headers.items()}
    src_ip = (request.client.host if request.client else "") or headers.get("x-forwarded-for", "").split(",")[0].strip()

    event = models.WebhookEvent(
        webhook_id=w.id,
        method=request.method,
        path="/" + extra_path if extra_path else "",
        query_string=request.url.query or "",
        headers_json=json.dumps(headers),
        body_text=body_text,
        content_type=headers.get("content-type", ""),
        source_ip=src_ip or "",
    )
    db.add(event)

    # Trim old events beyond the hard cap to keep the table from growing unboundedly.
    count = (
        db.query(models.WebhookEvent)
        .filter(models.WebhookEvent.webhook_id == w.id)
        .count()
    )
    if count >= _WEBHOOK_MAX_EVENTS_PER_HOOK:
        overflow = count - _WEBHOOK_MAX_EVENTS_PER_HOOK + 1
        old_ids = (
            db.query(models.WebhookEvent.id)
            .filter(models.WebhookEvent.webhook_id == w.id)
            .order_by(models.WebhookEvent.id.asc())
            .limit(overflow)
            .all()
        )
        if old_ids:
            db.query(models.WebhookEvent).filter(
                models.WebhookEvent.id.in_([r[0] for r in old_ids])
            ).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "webhook": w.slug}


@app.api_route("/hook/{slug}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def webhook_receive_root(slug: str, request: Request, db: Session = Depends(get_db)):
    return await _record_webhook(request, slug, "", db)


@app.api_route("/hook/{slug}/{extra:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def webhook_receive_subpath(slug: str, extra: str, request: Request, db: Session = Depends(get_db)):
    return await _record_webhook(request, slug, extra, db)


# ---------- Scheduled requests ----------
#
# APScheduler BackgroundScheduler runs alongside the FastAPI app. Jobs are
# persisted in the scheduled_jobs table; on startup we load + register all
# enabled jobs. Create/update/delete re-syncs the scheduler.
#
# Set SCHEDULER_DISABLED=1 to skip background execution (tests use the
# synchronous /run endpoint instead).

from datetime import datetime as _dt
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

_scheduler: Optional[BackgroundScheduler] = None


def _scheduler_enabled() -> bool:
    return os.environ.get("SCHEDULER_DISABLED", "").lower() not in {"1", "true", "yes"}


def _get_scheduler() -> Optional[BackgroundScheduler]:
    global _scheduler
    if not _scheduler_enabled():
        return None
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
        _scheduler.start()
    return _scheduler


def _parse_cron(expr: str) -> CronTrigger:
    """Accept a standard 5-field cron expression: minute hour dom month dow."""
    parts = (expr or "").strip().split()
    if len(parts) != 5:
        raise HTTPException(400, "Cron expression must have 5 fields: minute hour day-of-month month day-of-week")
    minute, hour, dom, month, dow = parts
    return CronTrigger(minute=minute, hour=hour, day=dom, month=month, day_of_week=dow, timezone="UTC")


def _build_trigger(job: models.ScheduledJob):
    if (job.trigger_type or "interval") == "cron":
        return _parse_cron(job.cron_expr or "")
    seconds = int(job.interval_seconds or 0)
    if seconds < 10:
        raise HTTPException(400, "Interval must be ≥ 10 seconds")
    return IntervalTrigger(seconds=seconds)


def _validate_trigger(job: models.ScheduledJob) -> None:
    """Fail fast on bad cron/interval config — runs regardless of scheduler state."""
    _build_trigger(job)


def _schedule_one(job: models.ScheduledJob) -> None:
    sched = _get_scheduler()
    if sched is None:
        return
    sched.add_job(
        _run_scheduled_job,
        args=[job.id],
        trigger=_build_trigger(job),
        id=f"job-{job.id}",
        replace_existing=True,
        misfire_grace_time=60,
    )


def _unschedule_one(job_id: int) -> None:
    sched = _get_scheduler()
    if sched is None:
        return
    try:
        sched.remove_job(f"job-{job_id}")
    except Exception:
        pass


def _execute_http_job(db: Session, job: models.ScheduledJob) -> dict:
    """Build an HTTPInvokeRequest from the job and run it. Returns a summary dict."""
    headers = {}
    query = {}
    body = None
    try:
        headers = json.loads(job.headers_json or "{}") or {}
    except Exception:
        pass
    try:
        query = json.loads(job.query_json or "{}") or {}
    except Exception:
        pass
    try:
        body = json.loads(job.body_json) if job.body_json else None
    except Exception:
        body = job.body_json
    payload = schemas.HTTPInvokeRequest(
        provider_id=job.provider_id,
        endpoint_id=job.endpoint_id,
        method=job.method or None,
        url=job.url or None,
        path=job.path or None,
        headers={str(k): str(v) for k, v in headers.items()} if isinstance(headers, dict) else {},
        query={str(k): str(v) for k, v in query.items()} if isinstance(query, dict) else {},
        body=body,
        body_type=job.body_type or "json",
    )
    # Re-enter the existing invoke handler so all auth / substitution / history
    # behavior stays in one place.
    result = invoke_http(payload, db)
    return {
        "ok": bool(result.ok),
        "status_code": int(result.status_code or 0),
        "latency_ms": int(result.latency_ms or 0),
        "error": result.error or "",
    }


def _run_scheduled_job(job_id: int) -> None:
    """Called by APScheduler on a worker thread."""
    db = SessionLocal()
    try:
        job = db.get(models.ScheduledJob, job_id)
        if not job or not job.enabled:
            return
        try:
            summary = _execute_http_job(db, job)
        except Exception as e:
            summary = {"ok": False, "status_code": 0, "latency_ms": 0, "error": str(e)[:500]}
        job.last_run_at = _dt.utcnow()
        job.last_ok = summary["ok"]
        job.last_status_code = summary["status_code"]
        job.last_latency_ms = summary["latency_ms"]
        job.last_error = summary["error"] or ""
        # Best-effort next_run_at — APScheduler knows the canonical next fire time.
        sched = _get_scheduler()
        if sched is not None:
            apscheduler_job = sched.get_job(f"job-{job.id}")
            if apscheduler_job and apscheduler_job.next_run_time:
                job.next_run_at = apscheduler_job.next_run_time.replace(tzinfo=None)
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
def _load_scheduled_jobs():
    if not _scheduler_enabled():
        return
    db = SessionLocal()
    try:
        jobs = db.query(models.ScheduledJob).filter(models.ScheduledJob.enabled == True).all()  # noqa: E712
        for j in jobs:
            try:
                _schedule_one(j)
            except Exception:
                # One bad job shouldn't take down startup.
                pass
    finally:
        db.close()


@app.on_event("shutdown")
def _stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None


def _sched_job_to_out(j: models.ScheduledJob) -> dict:
    def _parse(raw, default):
        if not raw:
            return default
        try:
            val = json.loads(raw)
            return val if isinstance(val, type(default)) else default
        except Exception:
            return default
    body_val: Any = None
    if j.body_json:
        try:
            body_val = json.loads(j.body_json)
        except Exception:
            body_val = j.body_json
    return {
        "id": j.id,
        "name": j.name or "",
        "enabled": bool(j.enabled),
        "trigger_type": j.trigger_type or "interval",
        "interval_seconds": j.interval_seconds,
        "cron_expr": j.cron_expr or "",
        "provider_id": j.provider_id,
        "endpoint_id": j.endpoint_id,
        "method": j.method or "",
        "url": j.url or "",
        "path": j.path or "",
        "headers": _parse(j.headers_json, {}),
        "query": _parse(j.query_json, {}),
        "body": body_val,
        "body_type": j.body_type or "json",
        "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
        "last_ok": j.last_ok,
        "last_status_code": j.last_status_code,
        "last_latency_ms": j.last_latency_ms,
        "last_error": j.last_error or "",
        "next_run_at": j.next_run_at.isoformat() if j.next_run_at else None,
        "created_at": j.created_at.isoformat() if j.created_at else "",
        "updated_at": j.updated_at.isoformat() if j.updated_at else "",
    }


def _apply_job_payload(j: models.ScheduledJob, data: Dict[str, Any]) -> None:
    for k in ("name", "enabled", "trigger_type", "interval_seconds", "cron_expr",
              "provider_id", "endpoint_id", "method", "url", "path", "body_type"):
        if k in data:
            setattr(j, k, data[k])
    if "headers" in data:
        j.headers_json = json.dumps(data["headers"] or {})
    if "query" in data:
        j.query_json = json.dumps(data["query"] or {})
    if "body" in data:
        j.body_json = json.dumps(data["body"]) if data["body"] is not None else ""


@app.get("/api/scheduled-jobs", response_model=List[schemas.ScheduledJobOut])
def list_scheduled_jobs(db: Session = Depends(get_db)):
    return [_sched_job_to_out(j) for j in db.query(models.ScheduledJob).order_by(models.ScheduledJob.created_at.desc()).all()]


@app.post("/api/scheduled-jobs", response_model=schemas.ScheduledJobOut)
def create_scheduled_job(payload: schemas.ScheduledJobCreate, db: Session = Depends(get_db)):
    j = models.ScheduledJob()
    _apply_job_payload(j, payload.model_dump())
    _validate_trigger(j)  # 400s on bad cron / interval before we hit the DB
    db.add(j)
    db.commit()
    db.refresh(j)
    if j.enabled:
        _schedule_one(j)
    return _sched_job_to_out(j)


@app.patch("/api/scheduled-jobs/{job_id}", response_model=schemas.ScheduledJobOut)
def update_scheduled_job(job_id: int, payload: schemas.ScheduledJobUpdate, db: Session = Depends(get_db)):
    j = db.get(models.ScheduledJob, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    _apply_job_payload(j, payload.model_dump(exclude_unset=True))
    _validate_trigger(j)
    db.commit()
    db.refresh(j)
    _unschedule_one(j.id)
    if j.enabled:
        _schedule_one(j)
    return _sched_job_to_out(j)


@app.delete("/api/scheduled-jobs/{job_id}")
def delete_scheduled_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(models.ScheduledJob, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    _unschedule_one(j.id)
    db.delete(j)
    db.commit()
    return {"ok": True}


@app.post("/api/scheduled-jobs/{job_id}/run")
def run_scheduled_job_now(job_id: int, db: Session = Depends(get_db)):
    j = db.get(models.ScheduledJob, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    try:
        summary = _execute_http_job(db, j)
    except Exception as e:
        summary = {"ok": False, "status_code": 0, "latency_ms": 0, "error": str(e)[:500]}
    j.last_run_at = _dt.utcnow()
    j.last_ok = summary["ok"]
    j.last_status_code = summary["status_code"]
    j.last_latency_ms = summary["latency_ms"]
    j.last_error = summary["error"] or ""
    db.commit()
    db.refresh(j)
    return {"ok": summary["ok"], "status_code": summary["status_code"], "latency_ms": summary["latency_ms"], "error": summary["error"], "job": _sched_job_to_out(j)}


# ---------- Data-driven Runs (Postman-runner style) ----------
#
# A Run is a request template + a data file + assertion rules. Executing a run
# iterates over the rows of the data file, substitutes {{column}} variables in
# the template per row, and records the outcome.

import csv as _csv
import io as _io
import threading as _threading

_RUN_DATA_MAX_BYTES = 2 * 1024 * 1024   # 2 MB cap on data blobs
_RUN_ROW_HARD_LIMIT = 10_000            # hard safety cap on iterations
_RUN_BODY_PREVIEW_BYTES = 4 * 1024      # per-iteration response preview size


def _parse_assertions_raw(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except Exception:
        return {}


def _assertions_from_payload(a: Optional[schemas.RunAssertions]) -> Dict[str, Any]:
    if a is None:
        return {}
    d = a.model_dump(exclude_none=True)
    # Normalize empty strings to absent
    for k in ("body_contains", "body_not_contains"):
        if k in d and not d[k]:
            d.pop(k)
    if "expected_status" in d and not d["expected_status"]:
        d.pop("expected_status")
    return d


def _parse_run_rows(content: str, fmt: str) -> List[Dict[str, str]]:
    """Parse the saved data_content into a list of row-dicts.

    Supported formats:
      - csv / tsv: header row defines column names → variables
      - json:      must be a top-level array of objects
    """
    content = (content or "").lstrip("\ufeff")  # strip BOM
    fmt = (fmt or "csv").lower()
    if fmt == "json":
        try:
            data = json.loads(content or "[]")
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Data is not valid JSON: {e}")
        if not isinstance(data, list):
            raise HTTPException(400, "JSON data must be a top-level array of objects")
        rows: List[Dict[str, str]] = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise HTTPException(400, f"Row {i} is not an object")
            rows.append({str(k): "" if v is None else str(v) if not isinstance(v, str) else v for k, v in item.items()})
        return rows

    if fmt not in {"csv", "tsv"}:
        raise HTTPException(400, f"Unsupported data format: {fmt}")
    delim = "\t" if fmt == "tsv" else ","
    reader = _csv.DictReader(_io.StringIO(content), delimiter=delim)
    out: List[Dict[str, str]] = []
    for i, row in enumerate(reader):
        # DictReader gives None for missing fields; normalize.
        cleaned: Dict[str, str] = {}
        for k, v in row.items():
            if k is None:
                continue
            cleaned[str(k).strip()] = "" if v is None else str(v)
        out.append(cleaned)
    if reader.fieldnames is None and content.strip():
        raise HTTPException(400, "Could not parse CSV — first non-empty line must be a header row")
    return out


_VAR_PAT = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


def _collect_template_vars(run: models.Run) -> List[str]:
    """Return distinct variable names referenced in the request template."""
    parts = [run.url or "", run.path or "", run.headers_json or "", run.query_json or "", run.body_json or ""]
    seen = set()
    out: List[str] = []
    for p in parts:
        for m in _VAR_PAT.finditer(p):
            name = m.group(1)
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _apply_row_vars(run: models.Run, row: Dict[str, str]) -> schemas.HTTPInvokeRequest:
    """Build an HTTPInvokeRequest with {{var}} substituted from the row."""
    def _sub(s: str) -> str:
        return _subst_str(s or "", row)

    headers: Dict[str, Any] = {}
    try:
        headers = json.loads(run.headers_json or "{}") or {}
    except Exception:
        headers = {}
    query: Dict[str, Any] = {}
    try:
        query = json.loads(run.query_json or "{}") or {}
    except Exception:
        query = {}
    body_val: Any = None
    if run.body_json:
        try:
            body_val = json.loads(run.body_json)
        except Exception:
            body_val = run.body_json

    return schemas.HTTPInvokeRequest(
        provider_id=run.provider_id,
        endpoint_id=run.endpoint_id,
        method=(run.method or "GET"),
        url=_sub(run.url) if run.url else None,
        path=_sub(run.path) if run.path else None,
        headers={str(k): _sub(str(v)) for k, v in (headers if isinstance(headers, dict) else {}).items()},
        query={str(k): _sub(str(v)) for k, v in (query if isinstance(query, dict) else {}).items()},
        body=_subst_any(body_val, row),
        body_type=run.body_type or "json",
    )


def _evaluate_assertions(rules: Dict[str, Any], resp: schemas.InvokeResponse) -> List[Dict[str, Any]]:
    """Return a list of {name, passed, message} — empty list if no rules."""
    results: List[Dict[str, Any]] = []
    if not rules:
        return results
    expected = rules.get("expected_status") or []
    if expected:
        ok = int(resp.status_code or 0) in set(int(x) for x in expected)
        results.append({
            "name": "expected_status",
            "passed": bool(ok),
            "message": f"got {resp.status_code}, expected one of {expected}",
        })
    body_text = ""
    if isinstance(resp.body, str):
        body_text = resp.body
    elif resp.body is not None:
        try:
            body_text = json.dumps(resp.body)
        except Exception:
            body_text = str(resp.body)
    needle = rules.get("body_contains")
    if needle:
        ok = needle in body_text
        results.append({"name": "body_contains", "passed": ok, "message": "" if ok else f"substring {needle!r} not in response"})
    forbidden = rules.get("body_not_contains")
    if forbidden:
        ok = forbidden not in body_text
        results.append({"name": "body_not_contains", "passed": ok, "message": "" if ok else f"forbidden substring {forbidden!r} present"})
    return results


def _make_preview(resp: schemas.InvokeResponse) -> str:
    if resp.body is None:
        return ""
    if isinstance(resp.body, str):
        s = resp.body
    else:
        try:
            s = json.dumps(resp.body, ensure_ascii=False)
        except Exception:
            s = str(resp.body)
    if len(s) > _RUN_BODY_PREVIEW_BYTES:
        s = s[:_RUN_BODY_PREVIEW_BYTES] + "\n…[truncated]"
    return s


def _run_to_out(r: models.Run) -> dict:
    def _parse(raw, default):
        if not raw:
            return default
        try:
            val = json.loads(raw)
            return val if isinstance(val, type(default)) else default
        except Exception:
            return default
    body_val: Any = None
    if r.body_json:
        try:
            body_val = json.loads(r.body_json)
        except Exception:
            body_val = r.body_json
    last = r.executions[0] if r.executions else None
    return {
        "id": r.id,
        "name": r.name or "",
        "notes": r.notes or "",
        "provider_id": r.provider_id,
        "endpoint_id": r.endpoint_id,
        "method": r.method or "GET",
        "url": r.url or "",
        "path": r.path or "",
        "headers": _parse(r.headers_json, {}),
        "query": _parse(r.query_json, {}),
        "body": body_val,
        "body_type": r.body_type or "json",
        "data_format": r.data_format or "csv",
        "data_content": r.data_content or "",
        "delay_ms": int(r.delay_ms or 0),
        "stop_on_error": bool(r.stop_on_error),
        "max_rows": r.max_rows,
        "assertions": _parse_assertions_raw(r.assertions_json),
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        "last_execution_id": last.id if last else None,
        "last_execution_status": last.status if last else None,
    }


def _execution_to_out(e: models.RunExecution, include_iterations: bool = False) -> dict:
    out = {
        "id": e.id,
        "run_id": e.run_id,
        "status": e.status or "pending",
        "started_at": e.started_at.isoformat() if e.started_at else "",
        "finished_at": e.finished_at.isoformat() if e.finished_at else None,
        "error": e.error or "",
        "total_rows": int(e.total_rows or 0),
        "completed_rows": int(e.completed_rows or 0),
        "succeeded": int(e.succeeded or 0),
        "failed": int(e.failed or 0),
        "assertions": _parse_assertions_raw(e.assertions_json),
    }
    if include_iterations:
        out["iterations"] = [_iteration_to_out(i) for i in e.iterations]
    return out


def _iteration_to_out(it: models.RunIteration) -> dict:
    try:
        vars_ = json.loads(it.variables_json or "{}")
    except Exception:
        vars_ = {}
    try:
        ar = json.loads(it.assertion_results_json or "[]")
    except Exception:
        ar = []
    return {
        "id": it.id,
        "execution_id": it.execution_id,
        "row_index": it.row_index,
        "variables": vars_ if isinstance(vars_, dict) else {},
        "method": it.method or "",
        "url": it.url or "",
        "status_code": int(it.status_code or 0),
        "latency_ms": int(it.latency_ms or 0),
        "ok": bool(it.ok),
        "passed": bool(it.passed),
        "error": it.error or "",
        "response_preview": it.response_preview or "",
        "assertion_results": ar if isinstance(ar, list) else [],
        "created_at": it.created_at.isoformat() if it.created_at else "",
    }


def _apply_run_payload(r: models.Run, data: Dict[str, Any]) -> None:
    for k in ("name", "notes", "provider_id", "endpoint_id", "method", "url",
              "path", "body_type", "data_format", "delay_ms", "stop_on_error", "max_rows"):
        if k in data:
            setattr(r, k, data[k])
    if "headers" in data:
        r.headers_json = json.dumps(data["headers"] or {})
    if "query" in data:
        r.query_json = json.dumps(data["query"] or {})
    if "body" in data:
        r.body_json = json.dumps(data["body"]) if data["body"] is not None else ""
    if "data_content" in data:
        content = data["data_content"] or ""
        if len(content.encode("utf-8", errors="ignore")) > _RUN_DATA_MAX_BYTES:
            raise HTTPException(400, f"data_content exceeds {_RUN_DATA_MAX_BYTES} bytes")
        r.data_content = content
    if "assertions" in data and data["assertions"] is not None:
        r.assertions_json = json.dumps(data["assertions"])


@app.get("/api/runs", response_model=List[schemas.RunOut])
def list_runs(db: Session = Depends(get_db)):
    return [_run_to_out(r) for r in db.query(models.Run).order_by(models.Run.updated_at.desc()).all()]


@app.post("/api/runs", response_model=schemas.RunOut)
def create_run(payload: schemas.RunCreate, db: Session = Depends(get_db)):
    r = models.Run()
    data = payload.model_dump()
    data["assertions"] = _assertions_from_payload(payload.assertions)
    _apply_run_payload(r, data)
    # Validate data up front so broken rows can't be saved unnoticed.
    _parse_run_rows(r.data_content or "", r.data_format or "csv")
    db.add(r)
    db.commit()
    db.refresh(r)
    return _run_to_out(r)


@app.get("/api/runs/{run_id}", response_model=schemas.RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    r = db.get(models.Run, run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    return _run_to_out(r)


@app.patch("/api/runs/{run_id}", response_model=schemas.RunOut)
def update_run(run_id: int, payload: schemas.RunUpdate, db: Session = Depends(get_db)):
    r = db.get(models.Run, run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    data = payload.model_dump(exclude_unset=True)
    if "assertions" in data:
        data["assertions"] = _assertions_from_payload(payload.assertions)
    _apply_run_payload(r, data)
    # Re-validate whenever data / format changes.
    if "data_content" in data or "data_format" in data:
        _parse_run_rows(r.data_content or "", r.data_format or "csv")
    db.commit()
    db.refresh(r)
    return _run_to_out(r)


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: int, db: Session = Depends(get_db)):
    r = db.get(models.Run, run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    db.delete(r)
    db.commit()
    return {"ok": True}


@app.post("/api/runs/{run_id}/preview")
def preview_run(run_id: int, db: Session = Depends(get_db)):
    """Dry-run: parse rows + return the variables used by the template + the first row rendered."""
    r = db.get(models.Run, run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    rows = _parse_run_rows(r.data_content or "", r.data_format or "csv")
    template_vars = _collect_template_vars(r)
    columns = list(rows[0].keys()) if rows else []
    missing = [v for v in template_vars if v not in columns]
    unused = [c for c in columns if c not in template_vars]
    rendered = None
    if rows:
        try:
            req = _apply_row_vars(r, rows[0])
            rendered = {
                "method": req.method, "url": req.url, "path": req.path,
                "headers": req.headers, "query": req.query, "body": req.body,
            }
        except Exception as e:
            rendered = {"error": str(e)}
    return {
        "row_count": len(rows),
        "columns": columns,
        "template_variables": template_vars,
        "missing_variables": missing,
        "unused_columns": unused,
        "first_row_rendered": rendered,
    }


def _execute_iteration(db: Session, run: models.Run, execution: models.RunExecution, row_index: int, row: Dict[str, str], rules: Dict[str, Any]) -> models.RunIteration:
    """Run one iteration end-to-end: invoke → evaluate → persist."""
    try:
        invoke_payload = _apply_row_vars(run, row)
    except Exception as e:
        it = models.RunIteration(
            execution_id=execution.id,
            row_index=row_index,
            variables_json=json.dumps(row),
            method=run.method or "",
            url=run.url or "",
            status_code=0,
            latency_ms=0,
            ok=False,
            passed=False,
            error=f"template render failed: {e}",
            response_preview="",
            assertion_results_json="[]",
        )
        db.add(it)
        db.commit()
        db.refresh(it)
        return it

    try:
        resp = invoke_http(invoke_payload, db)
    except HTTPException as e:
        resp = schemas.InvokeResponse(
            ok=False, status_code=e.status_code, latency_ms=0,
            headers={}, body=None, error=str(e.detail),
        )
    except Exception as e:
        resp = schemas.InvokeResponse(
            ok=False, status_code=0, latency_ms=0,
            headers={}, body=None, error=str(e)[:500],
        )

    assertion_results = _evaluate_assertions(rules, resp)
    assertion_pass = all(a.get("passed") for a in assertion_results) if assertion_results else True
    passed = bool(resp.ok) and assertion_pass

    it = models.RunIteration(
        execution_id=execution.id,
        row_index=row_index,
        variables_json=json.dumps(row),
        method=(resp.request.method if resp.request else (invoke_payload.method or "")) or "",
        url=(resp.request.url if resp.request else (invoke_payload.url or "")) or "",
        status_code=int(resp.status_code or 0),
        latency_ms=int(resp.latency_ms or 0),
        ok=bool(resp.ok),
        passed=passed,
        error=resp.error or "",
        response_preview=_make_preview(resp),
        assertion_results_json=json.dumps(assertion_results),
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _run_execute_worker(run_id: int, execution_id: int) -> None:
    """Background thread worker: iterates over rows, writes progress to DB."""
    db = SessionLocal()
    try:
        execution = db.get(models.RunExecution, execution_id)
        if not execution:
            return
        run = db.get(models.Run, run_id)
        if not run:
            execution.status = "failed"
            execution.error = "run no longer exists"
            execution.finished_at = _dt.utcnow()
            db.commit()
            return

        execution.status = "running"
        db.commit()

        try:
            rows = _parse_run_rows(run.data_content or "", run.data_format or "csv")
        except HTTPException as e:
            execution.status = "failed"
            execution.error = str(e.detail)[:500]
            execution.finished_at = _dt.utcnow()
            db.commit()
            return
        except Exception as e:
            execution.status = "failed"
            execution.error = str(e)[:500]
            execution.finished_at = _dt.utcnow()
            db.commit()
            return

        cap = run.max_rows if (run.max_rows and run.max_rows > 0) else _RUN_ROW_HARD_LIMIT
        rows = rows[:min(cap, _RUN_ROW_HARD_LIMIT)]
        execution.total_rows = len(rows)
        db.commit()

        rules = _parse_assertions_raw(execution.assertions_json)
        delay = max(0, int(run.delay_ms or 0))

        for idx, row in enumerate(rows):
            # Cancellation check — refresh from DB to pick up flag changes.
            db.refresh(execution)
            if execution.cancel_requested:
                execution.status = "canceled"
                break

            it = _execute_iteration(db, run, execution, idx, row, rules)

            execution.completed_rows = idx + 1
            if it.passed:
                execution.succeeded = (execution.succeeded or 0) + 1
            else:
                execution.failed = (execution.failed or 0) + 1
            db.commit()

            if run.stop_on_error and not it.passed:
                break

            if delay and idx < len(rows) - 1:
                time.sleep(delay / 1000.0)

        if execution.status == "running":
            execution.status = "completed"
        execution.finished_at = _dt.utcnow()
        db.commit()
    except Exception as e:
        try:
            execution = db.get(models.RunExecution, execution_id)
            if execution:
                execution.status = "failed"
                execution.error = str(e)[:500]
                execution.finished_at = _dt.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


# Track active worker threads so tests can wait for them; not exposed to HTTP.
_run_worker_threads: Dict[int, _threading.Thread] = {}


@app.post("/api/runs/{run_id}/execute", response_model=schemas.RunExecutionOut)
def execute_run(run_id: int, db: Session = Depends(get_db), sync: bool = False):
    r = db.get(models.Run, run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    # Fail early if the data / format is broken.
    _parse_run_rows(r.data_content or "", r.data_format or "csv")

    execution = models.RunExecution(
        run_id=r.id,
        status="pending",
        started_at=_dt.utcnow(),
        assertions_json=r.assertions_json or "{}",
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    exec_id = execution.id

    if sync:
        _run_execute_worker(r.id, exec_id)
        db.refresh(execution)
    else:
        t = _threading.Thread(
            target=_run_execute_worker,
            args=(r.id, exec_id),
            name=f"run-exec-{exec_id}",
            daemon=True,
        )
        _run_worker_threads[exec_id] = t
        t.start()
    return _execution_to_out(execution)


@app.get("/api/runs/{run_id}/executions", response_model=List[schemas.RunExecutionOut])
def list_executions(run_id: int, limit: int = 50, db: Session = Depends(get_db)):
    r = db.get(models.Run, run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    q = (
        db.query(models.RunExecution)
        .filter(models.RunExecution.run_id == run_id)
        .order_by(models.RunExecution.id.desc())
        .limit(max(1, min(limit, 200)))
    )
    return [_execution_to_out(e) for e in q.all()]


@app.get("/api/runs/{run_id}/executions/{execution_id}", response_model=schemas.RunExecutionDetail)
def get_execution(run_id: int, execution_id: int, db: Session = Depends(get_db)):
    e = db.get(models.RunExecution, execution_id)
    if not e or e.run_id != run_id:
        raise HTTPException(404, "Execution not found")
    return _execution_to_out(e, include_iterations=True)


@app.post("/api/runs/{run_id}/executions/{execution_id}/cancel")
def cancel_execution(run_id: int, execution_id: int, db: Session = Depends(get_db)):
    e = db.get(models.RunExecution, execution_id)
    if not e or e.run_id != run_id:
        raise HTTPException(404, "Execution not found")
    if e.status in {"completed", "canceled", "failed"}:
        return {"ok": True, "status": e.status}
    e.cancel_requested = True
    db.commit()
    return {"ok": True, "status": e.status}


@app.delete("/api/runs/{run_id}/executions/{execution_id}")
def delete_execution(run_id: int, execution_id: int, db: Session = Depends(get_db)):
    e = db.get(models.RunExecution, execution_id)
    if not e or e.run_id != run_id:
        raise HTTPException(404, "Execution not found")
    if e.status not in {"completed", "canceled", "failed"}:
        raise HTTPException(400, f"Cannot delete execution while status is '{e.status}' — cancel it first")
    db.delete(e)
    db.commit()
    return {"ok": True}
