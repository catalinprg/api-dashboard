"""Tests for the GraphQL invoke endpoint."""
import json


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = json.dumps(self._json)
        self.content = self.text.encode()
        self.headers = {"content-type": "application/json"}
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._json


class _FakeClient:
    last_call = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        _FakeClient.last_call = {"url": url, "headers": headers, "json": json}
        return _FakeClient._next_response

    def request(self, method, url, **kw):
        _FakeClient.last_call = {"method": method, "url": url, **kw}
        return _FakeClient._next_response


def _install_fake(monkeypatch, response):
    import main
    _FakeClient._next_response = response
    _FakeClient.last_call = None
    monkeypatch.setattr(main.httpx, "Client", _FakeClient)


def _create_graphql_provider(client, auth_type="none", **extra):
    body = {
        "name": "gh",
        "kind": "graphql",
        "base_url": "https://api.github.com/graphql",
        "auth_type": auth_type,
        **extra,
    }
    r = client.post("/api/providers", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_graphql_invoke_posts_query(client, monkeypatch):
    _install_fake(monkeypatch, _FakeResponse(200, {"data": {"viewer": {"login": "me"}}}))
    p = _create_graphql_provider(client)
    r = client.post("/api/invoke/graphql", json={
        "provider_id": p["id"],
        "query": "{ viewer { login } }",
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True
    assert out["body"] == {"data": {"viewer": {"login": "me"}}}
    call = _FakeClient.last_call
    assert call["url"] == "https://api.github.com/graphql"
    assert call["json"]["query"] == "{ viewer { login } }"
    assert call["headers"]["Content-Type"] == "application/json"


def test_graphql_includes_variables_and_operation(client, monkeypatch):
    _install_fake(monkeypatch, _FakeResponse(200, {"data": {}}))
    p = _create_graphql_provider(client)
    r = client.post("/api/invoke/graphql", json={
        "provider_id": p["id"],
        "query": "query GetUser($id: ID!) { user(id: $id) { name } }",
        "variables": {"id": "123"},
        "operation_name": "GetUser",
    })
    assert r.status_code == 200
    body = _FakeClient.last_call["json"]
    assert body["variables"] == {"id": "123"}
    assert body["operationName"] == "GetUser"


def test_graphql_surfaces_errors_in_body(client, monkeypatch):
    _install_fake(monkeypatch, _FakeResponse(200, {
        "data": None,
        "errors": [{"message": "Field 'nope' doesn't exist"}],
    }))
    p = _create_graphql_provider(client)
    r = client.post("/api/invoke/graphql", json={
        "provider_id": p["id"],
        "query": "{ nope }",
    })
    out = r.json()
    assert out["status_code"] == 200
    assert out["error"] and "nope" in out["error"]


def test_graphql_attaches_bearer_auth(client, monkeypatch):
    _install_fake(monkeypatch, _FakeResponse(200, {"data": {}}))
    p = _create_graphql_provider(client, auth_type="bearer", api_key="gh-pat-123", auth_prefix="Bearer ")
    client.post("/api/invoke/graphql", json={"provider_id": p["id"], "query": "{ x }"})
    assert _FakeClient.last_call["headers"]["Authorization"] == "Bearer gh-pat-123"


def test_graphql_rejects_non_graphql_provider(client, monkeypatch):
    _install_fake(monkeypatch, _FakeResponse(200, {"data": {}}))
    r = client.post("/api/providers", json={
        "name": "notgql", "kind": "http", "base_url": "https://example.com", "auth_type": "none",
    })
    pid = r.json()["id"]
    r = client.post("/api/invoke/graphql", json={"provider_id": pid, "query": "{ x }"})
    assert r.status_code == 400
    assert "GraphQL" in r.json()["detail"]
