"""Tests for provider auth types — verifies _build_auth mutates headers/params correctly."""
import base64


def _make_provider(auth_type, key="", **kwargs):
    from types import SimpleNamespace
    from crypto import encrypt
    defaults = dict(
        auth_type=auth_type,
        auth_header_name="Authorization",
        auth_prefix="",
        auth_query_param="",
        extra_headers="{}",
        api_key_encrypted=encrypt(key) if key else "",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_basic_auth_encodes_user_pass():
    from main import _build_auth
    p = _make_provider("basic", key="alice:secret")
    headers, params = {}, {}
    _build_auth(p, headers, params, method="GET", url="https://api.example.com/x")
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Basic ")
    decoded = base64.b64decode(headers["Authorization"][len("Basic "):]).decode()
    assert decoded == "alice:secret"
    assert params == {}


def test_basic_auth_with_colon_in_password():
    from main import _build_auth
    # RFC 7617: only the first colon separates user from password
    p = _make_provider("basic", key="alice:pass:with:colons")
    headers = {}
    _build_auth(p, headers, {}, method="GET", url="")
    decoded = base64.b64decode(headers["Authorization"][len("Basic "):]).decode()
    assert decoded == "alice:pass:with:colons"


def test_basic_auth_skipped_when_no_key():
    from main import _build_auth
    p = _make_provider("basic", key="")
    headers = {}
    _build_auth(p, headers, {}, method="GET", url="")
    assert "Authorization" not in headers


def test_bearer_auth_still_works():
    """Regression: don't break existing auth types."""
    from main import _build_auth
    p = _make_provider("bearer", key="abc123", auth_prefix="Bearer ")
    headers = {}
    _build_auth(p, headers, {}, method="GET", url="")
    assert headers["Authorization"] == "Bearer abc123"


def test_create_provider_with_basic_auth(client):
    r = client.post("/api/providers", json={
        "name": "basic-svc",
        "kind": "http",
        "base_url": "https://api.example.com",
        "auth_type": "basic",
        "api_key": "alice:secret",
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["auth_type"] == "basic"
    assert out["has_api_key"] is True
