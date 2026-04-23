"""Smoke tests to catch regressions in core CRUD paths."""


def test_providers_list_empty(client):
    r = client.get("/api/providers")
    assert r.status_code == 200
    assert r.json() == []


def test_create_http_provider_with_endpoint(client):
    # Regression: EndpointCreate has `api_key` which isn't a column on Endpoint.
    r = client.post("/api/providers", json={
        "name": "example",
        "kind": "http",
        "base_url": "https://example.com",
        "auth_type": "none",
        "endpoints": [{
            "name": "list",
            "method": "GET",
            "path": "/items",
            "api_key": None,
        }],
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["name"] == "example"
    assert len(out["endpoints"]) == 1
    assert out["endpoints"][0]["path"] == "/items"


def test_duplicate_provider_name_rejected(client):
    client.post("/api/providers", json={
        "name": "dup", "kind": "http", "base_url": "https://a.com", "auth_type": "none",
    })
    r = client.post("/api/providers", json={
        "name": "dup", "kind": "http", "base_url": "https://b.com", "auth_type": "none",
    })
    assert r.status_code == 400
