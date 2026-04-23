"""Tests for the webhook receiver: create → receive → list events → delete."""


def test_create_and_list_webhook(client):
    r = client.post("/api/webhooks", json={"name": "github-push", "notes": "for PR events"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["name"] == "github-push"
    assert out["slug"]
    assert out["enabled"] is True
    assert out["event_count"] == 0

    r2 = client.get("/api/webhooks")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_receive_post_records_event(client):
    slug = client.post("/api/webhooks", json={"name": "h"}).json()["slug"]

    r = client.post(f"/hook/{slug}", json={"event": "push", "ref": "main"}, headers={"X-Sig": "abc"})
    assert r.status_code == 200
    assert r.json()["webhook"] == slug

    events = client.get(f"/api/webhooks/{_wid(client)}/events").json()
    assert len(events) == 1
    e = events[0]
    assert e["method"] == "POST"
    assert e["content_type"].startswith("application/json")
    assert "push" in e["body"]
    assert e["headers"].get("x-sig") == "abc"


def _wid(client):
    return client.get("/api/webhooks").json()[0]["id"]


def test_receive_subpath_captures_path_and_query(client):
    slug = client.post("/api/webhooks", json={"name": "h"}).json()["slug"]
    r = client.post(f"/hook/{slug}/stripe/events?ts=123")
    assert r.status_code == 200
    events = client.get(f"/api/webhooks/{_wid(client)}/events").json()
    e = events[0]
    assert e["path"] == "/stripe/events"
    assert e["query_string"] == "ts=123"


def test_receive_different_methods(client):
    slug = client.post("/api/webhooks", json={"name": "h"}).json()["slug"]
    for m in ("GET", "PUT", "DELETE"):
        r = client.request(m, f"/hook/{slug}")
        assert r.status_code == 200, (m, r.text)
    events = client.get(f"/api/webhooks/{_wid(client)}/events").json()
    methods = {e["method"] for e in events}
    assert {"GET", "PUT", "DELETE"}.issubset(methods)


def test_unknown_slug_returns_404(client):
    r = client.post("/hook/does-not-exist", json={})
    assert r.status_code == 404


def test_disabled_webhook_rejects(client):
    wh = client.post("/api/webhooks", json={"name": "h"}).json()
    client.patch(f"/api/webhooks/{wh['id']}", json={"enabled": False})
    r = client.post(f"/hook/{wh['slug']}")
    assert r.status_code == 404


def test_delete_webhook_cascades_events(client):
    wh = client.post("/api/webhooks", json={"name": "h"}).json()
    client.post(f"/hook/{wh['slug']}", json={"x": 1})
    events_before = client.get(f"/api/webhooks/{wh['id']}/events").json()
    assert len(events_before) == 1

    client.delete(f"/api/webhooks/{wh['id']}")
    r = client.get(f"/api/webhooks/{wh['id']}/events")
    assert r.status_code == 404


def test_clear_events(client):
    wh = client.post("/api/webhooks", json={"name": "h"}).json()
    for _ in range(3):
        client.post(f"/hook/{wh['slug']}")
    assert len(client.get(f"/api/webhooks/{wh['id']}/events").json()) == 3
    client.delete(f"/api/webhooks/{wh['id']}/events")
    assert client.get(f"/api/webhooks/{wh['id']}/events").json() == []


def test_large_body_truncated(client):
    wh = client.post("/api/webhooks", json={"name": "h"}).json()
    big = "x" * 80_000
    r = client.post(f"/hook/{wh['slug']}", content=big, headers={"content-type": "text/plain"})
    assert r.status_code == 200
    events = client.get(f"/api/webhooks/{wh['id']}/events").json()
    body = events[0]["body"]
    assert "truncated" in body
    assert len(body) < len(big) + 100
