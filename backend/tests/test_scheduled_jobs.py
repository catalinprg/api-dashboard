"""Tests for scheduled jobs: CRUD + run-now + cron validation.

Scheduler is disabled via env var in conftest, so we exercise the DB/API
paths and the synchronous /run endpoint. httpx is stubbed so "run now"
doesn't hit the network.
"""
import json
import pytest


class _FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._json = body if body is not None else {"hello": "world"}
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

    def request(self, method, url, **kw):
        _FakeClient.last_call = {"method": method, "url": url, **kw}
        return _FakeClient._next_response

    def post(self, url, **kw):
        _FakeClient.last_call = {"method": "POST", "url": url, **kw}
        return _FakeClient._next_response


@pytest.fixture
def stub_httpx(monkeypatch):
    import main
    _FakeClient._next_response = _FakeResponse(200, {"ok": True})
    _FakeClient.last_call = None
    monkeypatch.setattr(main.httpx, "Client", _FakeClient)
    return _FakeClient


def test_create_and_list_scheduled_job(client):
    r = client.post("/api/scheduled-jobs", json={
        "name": "heartbeat",
        "trigger_type": "interval",
        "interval_seconds": 60,
        "method": "GET",
        "url": "https://example.com/health",
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["name"] == "heartbeat"
    assert out["interval_seconds"] == 60

    jobs = client.get("/api/scheduled-jobs").json()
    assert len(jobs) == 1


def test_interval_under_10s_rejected(client):
    r = client.post("/api/scheduled-jobs", json={
        "name": "too-fast",
        "trigger_type": "interval",
        "interval_seconds": 5,
        "url": "https://example.com/",
    })
    assert r.status_code == 400
    assert "10" in r.json()["detail"]


def test_invalid_cron_rejected(client):
    r = client.post("/api/scheduled-jobs", json={
        "name": "bad-cron",
        "trigger_type": "cron",
        "cron_expr": "invalid",
        "url": "https://example.com/",
    })
    assert r.status_code == 400
    assert "5 fields" in r.json()["detail"]


def test_valid_cron_accepted(client):
    r = client.post("/api/scheduled-jobs", json={
        "name": "every-15-min",
        "trigger_type": "cron",
        "cron_expr": "*/15 * * * *",
        "url": "https://example.com/",
    })
    assert r.status_code == 200, r.text
    assert r.json()["cron_expr"] == "*/15 * * * *"


def test_update_scheduled_job(client):
    j = client.post("/api/scheduled-jobs", json={
        "name": "orig", "trigger_type": "interval", "interval_seconds": 60, "url": "https://a.com/",
    }).json()
    r = client.patch(f"/api/scheduled-jobs/{j['id']}", json={"name": "updated", "interval_seconds": 120})
    assert r.status_code == 200
    out = r.json()
    assert out["name"] == "updated"
    assert out["interval_seconds"] == 120


def test_delete_scheduled_job(client):
    j = client.post("/api/scheduled-jobs", json={
        "name": "del-me", "trigger_type": "interval", "interval_seconds": 30, "url": "https://x.com/",
    }).json()
    r = client.delete(f"/api/scheduled-jobs/{j['id']}")
    assert r.status_code == 200
    assert client.get("/api/scheduled-jobs").json() == []


def test_run_now_executes_and_records_status(client, stub_httpx):
    j = client.post("/api/scheduled-jobs", json={
        "name": "run-me",
        "trigger_type": "interval",
        "interval_seconds": 30,
        "method": "GET",
        "url": "https://api.example.com/ping",
    }).json()
    r = client.post(f"/api/scheduled-jobs/{j['id']}/run")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True
    assert out["status_code"] == 200
    assert stub_httpx.last_call["url"] == "https://api.example.com/ping"
    assert stub_httpx.last_call["method"] == "GET"
    # Job state was persisted
    assert out["job"]["last_ok"] is True
    assert out["job"]["last_status_code"] == 200


def test_run_now_with_headers_and_body(client, stub_httpx):
    j = client.post("/api/scheduled-jobs", json={
        "name": "posty",
        "trigger_type": "interval",
        "interval_seconds": 60,
        "method": "POST",
        "url": "https://api.example.com/thing",
        "headers": {"X-Custom": "yes"},
        "body": {"a": 1},
        "body_type": "json",
    }).json()
    client.post(f"/api/scheduled-jobs/{j['id']}/run")
    call = stub_httpx.last_call
    assert call["method"] == "POST"
    assert call["headers"]["X-Custom"] == "yes"
    assert call["json"] == {"a": 1}


def test_run_now_surfaces_http_error(client, monkeypatch):
    import main
    _FakeClient._next_response = _FakeResponse(500, {"error": "boom"})
    monkeypatch.setattr(main.httpx, "Client", _FakeClient)
    j = client.post("/api/scheduled-jobs", json={
        "name": "fails", "trigger_type": "interval", "interval_seconds": 30, "url": "https://x.com/",
    }).json()
    r = client.post(f"/api/scheduled-jobs/{j['id']}/run")
    out = r.json()
    assert out["ok"] is False
    assert out["status_code"] == 500
    assert out["job"]["last_ok"] is False
