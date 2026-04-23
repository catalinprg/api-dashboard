import json
import os
import secrets
import time
from typing import Any, Dict, List, Optional

import httpx
import re
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

import auth as auth_module
import models
import schemas
from crypto import encrypt, decrypt
from database import Base, engine, get_db

Base.metadata.create_all(bind=engine)


def _migrate_schema() -> None:
    """Add columns that were introduced after initial DB creation."""
    insp = inspect(engine)
    if "providers" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("providers")}
        with engine.begin() as conn:
            if "models" not in cols:
                conn.execute(text("ALTER TABLE providers ADD COLUMN models TEXT DEFAULT '[]'"))
            if "variables" not in cols:
                conn.execute(text("ALTER TABLE providers ADD COLUMN variables TEXT DEFAULT '{}'"))
    if "chat_sessions" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("chat_sessions")}
        with engine.begin() as conn:
            if "tools_json" not in cols:
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN tools_json TEXT DEFAULT '[]'"))
    if "chat_messages" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("chat_messages")}
        with engine.begin() as conn:
            if "tool_calls_json" not in cols:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN tool_calls_json TEXT DEFAULT ''"))
            if "tool_call_id" not in cols:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN tool_call_id TEXT DEFAULT ''"))
    if "endpoints" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("endpoints")}
        with engine.begin() as conn:
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


def _parse_models(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return [str(m) for m in val if str(m).strip()]
    except Exception:
        pass
    return []


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
        "default_model": p.default_model,
        "models": _parse_models(p.models),
        "extra_headers": p.extra_headers or "{}",
        "variables": getattr(p, "variables", None) or "{}",
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
        default_model=payload.default_model,
        models=json.dumps([m.strip() for m in (payload.models or []) if m.strip()]),
        extra_headers=payload.extra_headers or "{}",
        variables=payload.variables or "{}",
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
    if "models" in data:
        mods = data.pop("models") or []
        p.models = json.dumps([str(m).strip() for m in mods if str(m).strip()])
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
    # Best-effort probe per provider kind
    if p.kind == "llm":
        url = f"{base}/models"
        method = "GET"
    else:
        # pick first endpoint if configured, otherwise hit base_url
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


def _build_llm_request(provider: models.Provider, payload: schemas.LLMInvokeRequest):
    headers = {"content-type": "application/json"}
    try:
        extra = json.loads(provider.extra_headers or "{}")
        if isinstance(extra, dict):
            headers.update({k: str(v) for k, v in extra.items()})
    except Exception:
        pass
    params: dict = {}
    _build_auth(provider, headers, params)

    vars = _parse_variables(getattr(provider, "variables", None))
    messages = _subst_any(payload.messages, vars)

    is_anthropic_native = "api.anthropic.com" in provider.base_url
    if is_anthropic_native:
        system_msgs = [m["content"] for m in messages if m.get("role") == "system"]
        chat_msgs = [m for m in messages if m.get("role") != "system"]
        body = {
            "model": payload.model or provider.default_model,
            "messages": chat_msgs,
            "max_tokens": payload.max_tokens or 4096,
        }
        if system_msgs:
            body["system"] = "\n\n".join(system_msgs if all(isinstance(x, str) for x in system_msgs) else [str(x) for x in system_msgs])
        if payload.temperature is not None:
            body["temperature"] = payload.temperature
        body.update(payload.extra)
        url = provider.base_url.rstrip("/") + "/messages"
    else:
        body = {
            "model": payload.model or provider.default_model,
            "messages": messages,
        }
        if payload.temperature is not None:
            body["temperature"] = payload.temperature
        if payload.max_tokens is not None:
            body["max_tokens"] = payload.max_tokens
        if payload.tools:
            body["tools"] = payload.tools
        if payload.tool_choice is not None:
            body["tool_choice"] = payload.tool_choice
        body.update(payload.extra)
        url = provider.base_url.rstrip("/") + "/chat/completions"
    return url, headers, params, body, is_anthropic_native


def _extract_assistant_text(response_body) -> str:
    if not isinstance(response_body, dict):
        return ""
    choices = response_body.get("choices") or []
    if choices:
        msg = (choices[0] or {}).get("message") or {}
        if isinstance(msg.get("content"), str):
            return msg["content"]
    content = response_body.get("content")
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


@app.post("/api/invoke/llm", response_model=schemas.InvokeResponse)
def invoke_llm(payload: schemas.LLMInvokeRequest, db: Session = Depends(get_db)):
    provider = db.get(models.Provider, payload.provider_id)
    if not provider or not provider.enabled:
        raise HTTPException(400, "Provider not found or disabled")

    url, headers, params, body, _is_anth = _build_llm_request(provider, payload)

    echo = schemas.RequestEcho(
        method="POST", url=url, headers=_mask_headers(headers), query=params,
    )
    start = time.time()
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(url, headers=headers, params=params, json=body)
    except httpx.HTTPError as exc:
        err_out = schemas.InvokeResponse(
            ok=False, status_code=0, latency_ms=int((time.time() - start) * 1000),
            headers={}, body=None, error=str(exc), request=echo,
        )
        _log_history(
            db, kind="llm", provider=provider,
            label=body.get("model", ""),
            request_dict={**echo.model_dump(), "body": body},
            response=err_out,
        )
        return err_out
    latency = int((time.time() - start) * 1000)
    out = _parse_response(r)
    out.latency_ms = latency
    out.request = echo
    _log_history(
        db, kind="llm", provider=provider,
        label=body.get("model", ""),
        request_dict={**echo.model_dump(), "body": body},
        response=out,
    )
    # Persist to session on non-streaming path (so the chat shows in sidebar sessions too)
    if payload.session_id and out.ok:
        try:
            # Persist the newest appended message(s) we sent: the last user (or tool) message
            last_msg = payload.messages[-1] if payload.messages else None
            if last_msg and last_msg.get("role") in {"user", "tool"}:
                _append_session_message(
                    db, payload.session_id, last_msg.get("role"), last_msg.get("content", ""),
                    tool_call_id=last_msg.get("tool_call_id") or None,
                )
            reply = _extract_assistant_text(out.body)
            tool_calls = None
            if isinstance(out.body, dict):
                choices = out.body.get("choices") or []
                if choices:
                    msg = (choices[0] or {}).get("message") or {}
                    tc = msg.get("tool_calls")
                    if isinstance(tc, list) and tc:
                        tool_calls = tc
            if reply or tool_calls:
                _append_session_message(db, payload.session_id, "assistant", reply or "", tool_calls=tool_calls)
        except Exception:
            pass
    return out


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


# ---------- Chat sessions ----------

def _session_msg_to_out(m: models.ChatMessage) -> dict:
    try:
        content = json.loads(m.content_json) if m.content_json else ""
    except Exception:
        content = m.content_json or ""
    tool_calls = None
    raw_tc = getattr(m, "tool_calls_json", None)
    if raw_tc:
        try:
            tc = json.loads(raw_tc)
            if isinstance(tc, list) and tc:
                tool_calls = tc
        except Exception:
            pass
    out = {
        "id": m.id,
        "role": m.role,
        "content": content,
        "created_at": m.created_at.isoformat() if m.created_at else "",
    }
    if tool_calls:
        out["tool_calls"] = tool_calls
    tcid = getattr(m, "tool_call_id", None)
    if tcid:
        out["tool_call_id"] = tcid
    return out


def _session_to_out(s: models.ChatSession, include_messages: bool = False) -> dict:
    try:
        tools = json.loads(getattr(s, "tools_json", None) or "[]")
        if not isinstance(tools, list): tools = []
    except Exception:
        tools = []
    return {
        "id": s.id,
        "name": s.name or "New chat",
        "provider_id": s.provider_id,
        "model": s.model or "",
        "system_prompt": s.system_prompt or "",
        "temperature": s.temperature if s.temperature not in (None, "") else "0.7",
        "max_tokens": s.max_tokens,
        "tools": tools,
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
        "message_count": len(s.messages),
        "messages": [_session_msg_to_out(m) for m in s.messages] if include_messages else [],
    }


@app.get("/api/sessions", response_model=List[schemas.ChatSessionOut])
def list_sessions(db: Session = Depends(get_db)):
    q = db.query(models.ChatSession).order_by(models.ChatSession.updated_at.desc()).all()
    return [_session_to_out(s, include_messages=False) for s in q]


@app.post("/api/sessions", response_model=schemas.ChatSessionOut)
def create_session(payload: schemas.ChatSessionCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    tools = data.pop("tools", [])
    s = models.ChatSession(**data, tools_json=json.dumps(tools or []))
    db.add(s)
    db.commit()
    db.refresh(s)
    return _session_to_out(s, include_messages=True)


@app.get("/api/sessions/{session_id}", response_model=schemas.ChatSessionOut)
def get_session(session_id: int, db: Session = Depends(get_db)):
    s = db.get(models.ChatSession, session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return _session_to_out(s, include_messages=True)


@app.patch("/api/sessions/{session_id}", response_model=schemas.ChatSessionOut)
def update_session(session_id: int, payload: schemas.ChatSessionUpdate, db: Session = Depends(get_db)):
    s = db.get(models.ChatSession, session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    data = payload.model_dump(exclude_unset=True)
    if "tools" in data:
        s.tools_json = json.dumps(data.pop("tools") or [])
    for k, v in data.items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return _session_to_out(s, include_messages=True)


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    s = db.get(models.ChatSession, session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    db.delete(s)
    db.commit()
    return {"ok": True}


@app.delete("/api/sessions/{session_id}/messages")
def clear_session_messages(session_id: int, db: Session = Depends(get_db)):
    s = db.get(models.ChatSession, session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    db.query(models.ChatMessage).filter(models.ChatMessage.session_id == session_id).delete()
    db.commit()
    return {"ok": True}


@app.post("/api/sessions/{session_id}/truncate/{message_id}")
def truncate_session_at(session_id: int, message_id: int, db: Session = Depends(get_db)):
    """Delete all messages in the session with id > message_id (used for regen/edit)."""
    s = db.get(models.ChatSession, session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session_id,
        models.ChatMessage.id > message_id,
    ).delete()
    db.commit()
    return {"ok": True}


@app.patch("/api/sessions/{session_id}/messages/{message_id}")
def edit_session_message(
    session_id: int,
    message_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    m = db.get(models.ChatMessage, message_id)
    if not m or m.session_id != session_id:
        raise HTTPException(404, "Message not found")
    if "content" in payload:
        m.content_json = json.dumps(payload["content"], default=str)
    # bump session.updated_at so the sidebar reflects recent activity
    s = db.get(models.ChatSession, session_id)
    if s:
        from datetime import datetime as _dt
        s.updated_at = _dt.utcnow()
    db.commit()
    return _session_msg_to_out(m)


@app.delete("/api/sessions/{session_id}/messages/{message_id}")
def delete_session_message(session_id: int, message_id: int, db: Session = Depends(get_db)):
    m = db.get(models.ChatMessage, message_id)
    if not m or m.session_id != session_id:
        raise HTTPException(404, "Message not found")
    db.delete(m)
    db.commit()
    return {"ok": True}


def _append_session_message(
    db: Session,
    session_id: int,
    role: str,
    content: Any,
    *,
    tool_calls: Optional[list] = None,
    tool_call_id: Optional[str] = None,
) -> None:
    m = models.ChatMessage(
        session_id=session_id,
        role=role,
        content_json=json.dumps(content, default=str) if content is not None else "",
        tool_calls_json=json.dumps(tool_calls) if tool_calls else "",
        tool_call_id=tool_call_id or "",
    )
    db.add(m)
    # bump session.updated_at
    s = db.get(models.ChatSession, session_id)
    if s:
        from datetime import datetime as _dt
        s.updated_at = _dt.utcnow()
    db.commit()


# ---------- Streaming LLM ----------

@app.post("/api/invoke/llm/stream")
def invoke_llm_stream(payload: schemas.LLMInvokeRequest, db: Session = Depends(get_db)):
    provider = db.get(models.Provider, payload.provider_id)
    if not provider or not provider.enabled:
        raise HTTPException(400, "Provider not found or disabled")

    url, headers, params, body, is_anth = _build_llm_request(provider, payload)
    body["stream"] = True
    # OpenAI-compat providers: ask for usage in the final stream chunk
    if not is_anth:
        body.setdefault("stream_options", {"include_usage": True})

    echo = schemas.RequestEcho(
        method="POST", url=url, headers=_mask_headers(headers), query=params,
    )

    if payload.session_id:
        # persist only the message we're appending this turn — last user or tool msg
        last_msg = payload.messages[-1] if payload.messages else None
        if last_msg and last_msg.get("role") in {"user", "tool"}:
            _append_session_message(
                db, payload.session_id, last_msg.get("role"), last_msg.get("content", ""),
                tool_call_id=last_msg.get("tool_call_id") or None,
            )

    def _event(data: dict) -> bytes:
        return f"data: {json.dumps(data)}\n\n".encode()

    def gen():
        start = time.time()
        yield _event({"type": "start", "request": echo.model_dump()})
        full_text_parts: List[str] = []
        tool_calls_acc: dict = {}  # keyed by index
        last_status = 0
        error_msg: Optional[str] = None
        try:
            with httpx.Client(timeout=None) as client:
                with client.stream("POST", url, headers=headers, params=params, json=body) as r:
                    last_status = r.status_code
                    if r.status_code >= 400:
                        # read full body and emit as error
                        err_body = r.read().decode("utf-8", errors="replace")
                        try:
                            parsed = json.loads(err_body)
                        except Exception:
                            parsed = err_body
                        yield _event({"type": "error", "status_code": r.status_code, "body": parsed})
                        full_text_parts.append(err_body)
                        return
                    for line in r.iter_lines():
                        if not line:
                            continue
                        s = line.strip()
                        if s.startswith("data:"):
                            s = s[5:].strip()
                        if s == "[DONE]":
                            break
                        if not s:
                            continue
                        try:
                            event = json.loads(s)
                        except Exception:
                            # not JSON, forward raw
                            yield _event({"type": "raw", "data": s})
                            continue
                        # Extract text delta across provider shapes
                        delta_text = ""
                        if is_anth:
                            ev_type = event.get("type")
                            if ev_type == "content_block_delta":
                                d = event.get("delta") or {}
                                if d.get("type") == "text_delta":
                                    delta_text = d.get("text", "") or ""
                        else:
                            choices = event.get("choices") or []
                            if choices:
                                d = choices[0].get("delta") or {}
                                delta_text = d.get("content") or ""
                        if delta_text:
                            full_text_parts.append(delta_text)
                            yield _event({"type": "delta", "text": delta_text})
                        # Forward usage if present (OpenAI-compat final chunk has `usage`)
                        usage = event.get("usage") if isinstance(event, dict) else None
                        if usage:
                            yield _event({"type": "usage", "usage": usage})
                        # Forward tool_calls chunks (OpenAI-compat: choices[0].delta.tool_calls)
                        tc_delta = None
                        if not is_anth:
                            choices_ = event.get("choices") or []
                            if choices_:
                                d = choices_[0].get("delta") or {}
                                tc_delta = d.get("tool_calls")
                        if tc_delta:
                            yield _event({"type": "tool_calls", "delta": tc_delta})
                            # Accumulate on the server too so we can persist
                            for d in tc_delta:
                                try:
                                    idx = d.get("index", 0) if isinstance(d, dict) else 0
                                except Exception:
                                    idx = 0
                                slot = tool_calls_acc.get(idx) or {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                if isinstance(d, dict):
                                    if d.get("id"): slot["id"] = d["id"]
                                    if d.get("type"): slot["type"] = d["type"]
                                    f = d.get("function") or {}
                                    if isinstance(f, dict):
                                        if f.get("name"): slot["function"]["name"] = (slot["function"].get("name") or "") + f["name"]
                                        if f.get("arguments"): slot["function"]["arguments"] = (slot["function"].get("arguments") or "") + f["arguments"]
                                tool_calls_acc[idx] = slot
                        if not delta_text and not usage and not tc_delta:
                            yield _event({"type": "event", "data": event})
        except httpx.HTTPError as exc:
            error_msg = str(exc)
            yield _event({"type": "error", "error": error_msg})
        latency = int((time.time() - start) * 1000)
        full_text = "".join(full_text_parts)
        yield _event({
            "type": "done",
            "text": full_text,
            "status_code": last_status,
            "latency_ms": latency,
        })

        # Log to history + session after stream ends
        try:
            fake_response = schemas.InvokeResponse(
                ok=(last_status == 200 and not error_msg),
                status_code=last_status,
                latency_ms=latency,
                headers={},
                body={"text": full_text},
                error=error_msg,
                request=echo,
            )
            _log_history(
                db, kind="llm", provider=provider,
                label=body.get("model", ""),
                request_dict={**echo.model_dump(), "body": body},
                response=fake_response,
            )
            if payload.session_id and (full_text or tool_calls_acc):
                tc_list = [tool_calls_acc[k] for k in sorted(tool_calls_acc.keys())] if tool_calls_acc else None
                _append_session_message(db, payload.session_id, "assistant", full_text, tool_calls=tc_list)
        except Exception:
            pass

    return StreamingResponse(gen(), media_type="text/event-stream")


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
            "default_model": p.default_model,
            "models": _parse_models(p.models),
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
            default_model=prov.get("default_model", ""),
            models=json.dumps(prov.get("models") or []),
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
