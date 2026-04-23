"""Tests for OAuth 2.0 client-credentials auth.

Mocks the token endpoint by monkey-patching httpx.Client used inside
_oauth_cc_token. Verifies:
  - token is fetched + attached as Authorization: Bearer
  - cached tokens are reused within TTL
  - expired tokens trigger refetch
  - "basic" auth style uses HTTP Basic for client creds (not form body)
  - missing config raises 400
"""
import time
import types
import pytest


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text or str(self._json)

    def json(self):
        return self._json


class _FakeClient:
    """Drop-in replacement for httpx.Client used in _oauth_cc_token.

    Records the last .post() call so tests can assert on url/data/auth.
    """
    last_call = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, data=None, auth=None, headers=None):
        _FakeClient.last_call = {"url": url, "data": data, "auth": auth, "headers": headers}
        return _FakeClient._next_response


def _install_fake_httpx(monkeypatch, response):
    import main
    _FakeClient._next_response = response
    _FakeClient.last_call = None
    monkeypatch.setattr(main.httpx, "Client", _FakeClient)


def _provider(oauth_auth_style="body"):
    from types import SimpleNamespace
    return SimpleNamespace(
        id=42,
        auth_type="oauth2_cc",
        auth_header_name="Authorization",
        auth_prefix="",
        auth_query_param="",
        extra_headers="{}",
        api_key_encrypted="",  # not used in this helper
        oauth_client_id="client-abc",
        oauth_token_url="https://auth.example.com/token",
        oauth_scope="read write",
        oauth_auth_style=oauth_auth_style,
    )


def _reset_cache():
    import main
    main._oauth_cc_cache.clear()


def test_oauth_cc_fetches_and_attaches_bearer(monkeypatch):
    _reset_cache()
    _install_fake_httpx(monkeypatch, _FakeResponse(200, {"access_token": "TKN-1", "expires_in": 3600}))
    from main import _oauth_cc_token
    tok = _oauth_cc_token(_provider(), client_secret="sek")
    assert tok == "TKN-1"
    # form-body style: client creds go in data, not auth
    call = _FakeClient.last_call
    assert call["url"] == "https://auth.example.com/token"
    assert call["data"]["grant_type"] == "client_credentials"
    assert call["data"]["client_id"] == "client-abc"
    assert call["data"]["client_secret"] == "sek"
    assert call["data"]["scope"] == "read write"
    assert call["auth"] is None


def test_oauth_cc_basic_style_uses_http_basic(monkeypatch):
    _reset_cache()
    _install_fake_httpx(monkeypatch, _FakeResponse(200, {"access_token": "TKN-2", "expires_in": 3600}))
    from main import _oauth_cc_token
    _oauth_cc_token(_provider(oauth_auth_style="basic"), client_secret="sek")
    call = _FakeClient.last_call
    assert call["auth"] == ("client-abc", "sek")
    assert "client_id" not in call["data"]
    assert "client_secret" not in call["data"]


def test_oauth_cc_caches_within_ttl(monkeypatch):
    _reset_cache()
    _install_fake_httpx(monkeypatch, _FakeResponse(200, {"access_token": "TKN-A", "expires_in": 3600}))
    from main import _oauth_cc_token
    t1 = _oauth_cc_token(_provider(), client_secret="sek")
    # change what the next fetch would return — cached call shouldn't hit this
    _FakeClient._next_response = _FakeResponse(200, {"access_token": "DIFFERENT", "expires_in": 3600})
    t2 = _oauth_cc_token(_provider(), client_secret="sek")
    assert t1 == t2 == "TKN-A"


def test_oauth_cc_refetches_when_expired(monkeypatch):
    _reset_cache()
    import main
    _install_fake_httpx(monkeypatch, _FakeResponse(200, {"access_token": "OLD", "expires_in": 3600}))
    main._oauth_cc_token(_provider(), client_secret="sek")
    # expire the cache
    main._oauth_cc_cache[42]["expires_at"] = time.time() - 1
    _FakeClient._next_response = _FakeResponse(200, {"access_token": "NEW", "expires_in": 3600})
    tok = main._oauth_cc_token(_provider(), client_secret="sek")
    assert tok == "NEW"


def test_oauth_cc_raises_on_token_error(monkeypatch):
    _reset_cache()
    _install_fake_httpx(monkeypatch, _FakeResponse(401, {"error": "invalid_client"}, text="unauthorized"))
    from fastapi import HTTPException
    import main
    with pytest.raises(HTTPException) as exc:
        main._oauth_cc_token(_provider(), client_secret="sek")
    assert exc.value.status_code == 502


def test_oauth_cc_missing_config_raises(monkeypatch):
    _reset_cache()
    from fastapi import HTTPException
    import main
    p = _provider()
    p.oauth_token_url = ""
    with pytest.raises(HTTPException) as exc:
        main._oauth_cc_token(p, client_secret="sek")
    assert exc.value.status_code == 400


def test_build_auth_attaches_oauth_bearer(monkeypatch):
    _reset_cache()
    _install_fake_httpx(monkeypatch, _FakeResponse(200, {"access_token": "BUILT-TKN", "expires_in": 3600}))
    from main import _build_auth
    from crypto import encrypt
    p = _provider()
    p.api_key_encrypted = encrypt("sek")  # client secret lives here
    headers, params = {}, {}
    _build_auth(p, headers, params, method="GET", url="https://api.example.com/x")
    assert headers["Authorization"] == "Bearer BUILT-TKN"


def test_create_provider_with_oauth_fields(client):
    r = client.post("/api/providers", json={
        "name": "oauth-svc",
        "kind": "http",
        "base_url": "https://api.example.com",
        "auth_type": "oauth2_cc",
        "oauth_client_id": "myclient",
        "oauth_token_url": "https://auth.example.com/token",
        "oauth_scope": "read",
        "oauth_auth_style": "basic",
        "api_key": "secret-value",
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["oauth_client_id"] == "myclient"
    assert out["oauth_token_url"] == "https://auth.example.com/token"
    assert out["oauth_scope"] == "read"
    assert out["oauth_auth_style"] == "basic"
    assert out["has_api_key"] is True
