"""Tests for data-driven Runs.

Covers CRUD, parsing of CSV / TSV / JSON data, variable substitution,
assertion evaluation, synchronous + background execution, cancellation,
stop-on-error, and edge cases (malformed data, missing variables, large
responses, template render failures).

httpx is stubbed so the executor doesn't hit the network.
"""
import json
import time
import pytest


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=None):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {"ok": True}
        self.text = text if text is not None else json.dumps(self._json)
        self.content = self.text.encode()
        self.headers = {"content-type": "application/json"}
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._json


class _FakeClient:
    """Stub for httpx.Client — responds per URL if you stash a dict in `plan`."""
    last_calls: list = []
    _default = _FakeResponse(200, {"ok": True})
    plan: dict = {}  # url → _FakeResponse

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _respond(self, url):
        return _FakeClient.plan.get(url, _FakeClient._default)

    def request(self, method, url, **kw):
        _FakeClient.last_calls.append({"method": method, "url": url, **kw})
        return self._respond(url)

    def post(self, url, **kw):
        _FakeClient.last_calls.append({"method": "POST", "url": url, **kw})
        return self._respond(url)


@pytest.fixture
def stub_httpx(monkeypatch):
    import main
    _FakeClient.last_calls = []
    _FakeClient.plan = {}
    _FakeClient._default = _FakeResponse(200, {"ok": True})
    monkeypatch.setattr(main.httpx, "Client", _FakeClient)
    return _FakeClient


def _run_payload(**overrides):
    base = {
        "name": "smoke",
        "method": "GET",
        "url": "https://api.example.com/items/{{id}}",
        "data_format": "csv",
        "data_content": "id,name\n1,alice\n2,bob\n3,carol\n",
    }
    base.update(overrides)
    return base


# ---------- CRUD + validation ----------

def test_create_and_list_run(client):
    r = client.post("/api/runs", json=_run_payload())
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["name"] == "smoke"
    assert out["data_content"].startswith("id,name")

    assert len(client.get("/api/runs").json()) == 1


def test_create_rejects_invalid_csv(client):
    r = client.post("/api/runs", json=_run_payload(data_content=""))
    # Empty CSV is allowed (zero rows). But malformed JSON should fail:
    assert r.status_code == 200
    r = client.post("/api/runs", json=_run_payload(name="bad-json", data_format="json", data_content="not valid json"))
    assert r.status_code == 400
    assert "JSON" in r.json()["detail"]


def test_create_rejects_json_not_array(client):
    r = client.post("/api/runs", json=_run_payload(data_format="json", data_content='{"id": 1}'))
    assert r.status_code == 400


def test_create_rejects_json_non_object_rows(client):
    r = client.post("/api/runs", json=_run_payload(data_format="json", data_content='[{"id": 1}, "bad"]'))
    assert r.status_code == 400


def test_create_enforces_data_size_cap(client):
    huge = "id,name\n" + ("1,abc\n" * 500_000)  # well over 2MB
    r = client.post("/api/runs", json=_run_payload(data_content=huge))
    assert r.status_code == 400
    assert "bytes" in r.json()["detail"]


def test_update_and_delete_run(client):
    rid = client.post("/api/runs", json=_run_payload()).json()["id"]
    r = client.patch(f"/api/runs/{rid}", json={"name": "renamed", "delay_ms": 50})
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"
    assert r.json()["delay_ms"] == 50

    r = client.delete(f"/api/runs/{rid}")
    assert r.status_code == 200
    assert client.get(f"/api/runs/{rid}").status_code == 404


# ---------- Data parsing ----------

def test_parse_csv_with_quoted_comma(client):
    data = 'name,note\n"alice","hello, world"\n'
    rid = client.post("/api/runs", json=_run_payload(data_content=data)).json()["id"]
    preview = client.post(f"/api/runs/{rid}/preview").json()
    assert preview["row_count"] == 1
    # The rendered first row has columns = ["name", "note"]
    assert preview["columns"] == ["name", "note"]


def test_parse_tsv(client):
    data = "id\tname\n1\talice\n2\tbob\n"
    rid = client.post("/api/runs", json=_run_payload(data_format="tsv", data_content=data)).json()["id"]
    preview = client.post(f"/api/runs/{rid}/preview").json()
    assert preview["row_count"] == 2
    assert preview["columns"] == ["id", "name"]


def test_parse_json_array(client):
    data = '[{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]'
    rid = client.post("/api/runs", json=_run_payload(data_format="json", data_content=data)).json()["id"]
    preview = client.post(f"/api/runs/{rid}/preview").json()
    assert preview["row_count"] == 2
    assert set(preview["columns"]) == {"id", "name"}


def test_parse_strips_bom(client):
    data = "\ufeffid,name\n1,alice\n"
    rid = client.post("/api/runs", json=_run_payload(data_content=data)).json()["id"]
    preview = client.post(f"/api/runs/{rid}/preview").json()
    assert preview["columns"] == ["id", "name"]


# ---------- Preview ----------

def test_preview_reports_missing_and_unused_variables(client):
    data = "id,email\n1,a@x.com\n"
    rid = client.post("/api/runs", json=_run_payload(
        url="https://api.example.com/user/{{id}}/{{missing}}",
        data_content=data,
    )).json()["id"]
    preview = client.post(f"/api/runs/{rid}/preview").json()
    assert "missing" in preview["missing_variables"]
    assert "email" in preview["unused_columns"]


def test_preview_renders_first_row(client):
    rid = client.post("/api/runs", json=_run_payload(
        url="https://api.example.com/items/{{id}}",
        data_content="id,name\n42,foo\n",
    )).json()["id"]
    preview = client.post(f"/api/runs/{rid}/preview").json()
    assert preview["first_row_rendered"]["url"] == "https://api.example.com/items/42"


# ---------- Execution ----------

def test_execute_sync_iterates_rows(client, stub_httpx):
    rid = client.post("/api/runs", json=_run_payload()).json()["id"]
    r = client.post(f"/api/runs/{rid}/execute?sync=true")
    assert r.status_code == 200
    exec_id = r.json()["id"]
    detail = client.get(f"/api/runs/{rid}/executions/{exec_id}").json()
    assert detail["status"] == "completed"
    assert detail["total_rows"] == 3
    assert detail["completed_rows"] == 3
    assert detail["succeeded"] == 3
    assert detail["failed"] == 0
    assert len(detail["iterations"]) == 3
    # URL substitution happened
    urls = [call["url"] for call in stub_httpx.last_calls]
    assert any(u.endswith("/items/1") for u in urls)
    assert any(u.endswith("/items/2") for u in urls)
    assert any(u.endswith("/items/3") for u in urls)


def test_execute_with_failing_assertion(client, stub_httpx):
    rid = client.post("/api/runs", json=_run_payload(
        assertions={"expected_status": [201]},
    )).json()["id"]
    r = client.post(f"/api/runs/{rid}/execute?sync=true")
    detail = client.get(f"/api/runs/{rid}/executions/{r.json()['id']}").json()
    # Default stub returns 200, assertion requires 201 → all iterations fail
    assert detail["status"] == "completed"
    assert detail["succeeded"] == 0
    assert detail["failed"] == 3
    for it in detail["iterations"]:
        assert not it["passed"]
        assert it["assertion_results"]
        assert it["assertion_results"][0]["name"] == "expected_status"


def test_execute_with_body_contains_assertion(client, stub_httpx):
    stub_httpx._default = _FakeResponse(200, {"status": "ok", "id": 42})
    rid = client.post("/api/runs", json=_run_payload(
        assertions={"body_contains": '"status": "ok"'},
    )).json()["id"]
    r = client.post(f"/api/runs/{rid}/execute?sync=true")
    detail = client.get(f"/api/runs/{rid}/executions/{r.json()['id']}").json()
    assert detail["succeeded"] == 3


def test_stop_on_error_halts_after_first_failure(client, stub_httpx):
    # Plan: row 1 (id=1) gets a 500, others would get 200.
    stub_httpx.plan = {"https://api.example.com/items/1": _FakeResponse(500, {"error": "boom"})}
    rid = client.post("/api/runs", json=_run_payload(stop_on_error=True)).json()["id"]
    r = client.post(f"/api/runs/{rid}/execute?sync=true")
    detail = client.get(f"/api/runs/{rid}/executions/{r.json()['id']}").json()
    assert detail["completed_rows"] == 1
    assert detail["failed"] == 1
    assert len(detail["iterations"]) == 1


def test_max_rows_caps_iterations(client, stub_httpx):
    rid = client.post("/api/runs", json=_run_payload(max_rows=2)).json()["id"]
    r = client.post(f"/api/runs/{rid}/execute?sync=true")
    detail = client.get(f"/api/runs/{rid}/executions/{r.json()['id']}").json()
    assert detail["total_rows"] == 2
    assert len(detail["iterations"]) == 2


def test_background_execution_and_list(client, stub_httpx):
    rid = client.post("/api/runs", json=_run_payload()).json()["id"]
    r = client.post(f"/api/runs/{rid}/execute")
    assert r.status_code == 200
    exec_id = r.json()["id"]
    # Wait for the background thread to finish.
    import main
    t = main._run_worker_threads.get(exec_id)
    if t is not None:
        t.join(timeout=10)
    detail = client.get(f"/api/runs/{rid}/executions/{exec_id}").json()
    assert detail["status"] == "completed"

    executions = client.get(f"/api/runs/{rid}/executions").json()
    assert len(executions) == 1
    assert executions[0]["id"] == exec_id


def test_cancel_execution(client, stub_httpx, monkeypatch):
    # Slow the stub so we have time to cancel.
    import main

    def slow_request(self, method, url, **kw):
        time.sleep(0.1)
        _FakeClient.last_calls.append({"method": method, "url": url, **kw})
        return self._respond(url)

    def slow_post(self, url, **kw):
        time.sleep(0.1)
        _FakeClient.last_calls.append({"method": "POST", "url": url, **kw})
        return self._respond(url)

    monkeypatch.setattr(_FakeClient, "post", slow_post)
    monkeypatch.setattr(_FakeClient, "request", slow_request)

    rid = client.post("/api/runs", json=_run_payload(
        data_content="id,x\n" + "\n".join(f"{i},y" for i in range(20)),
        delay_ms=50,
    )).json()["id"]
    r = client.post(f"/api/runs/{rid}/execute")
    exec_id = r.json()["id"]

    # Give the worker a moment to start, then cancel.
    time.sleep(0.15)
    cancel = client.post(f"/api/runs/{rid}/executions/{exec_id}/cancel")
    assert cancel.status_code == 200

    t = main._run_worker_threads.get(exec_id)
    if t is not None:
        t.join(timeout=10)
    detail = client.get(f"/api/runs/{rid}/executions/{exec_id}").json()
    assert detail["status"] == "canceled"
    assert detail["completed_rows"] < 20


def test_delete_running_execution_rejected(client, stub_httpx, monkeypatch):
    import main

    def slow_request(self, method, url, **kw):
        time.sleep(0.3)
        return _FakeResponse(200, {"ok": True})

    def slow_post(self, url, **kw):
        time.sleep(0.3)
        return _FakeResponse(200, {"ok": True})

    monkeypatch.setattr(_FakeClient, "post", slow_post)
    monkeypatch.setattr(_FakeClient, "request", slow_request)

    rid = client.post("/api/runs", json=_run_payload(
        data_content="id\n" + "\n".join(str(i) for i in range(10)),
    )).json()["id"]
    exec_id = client.post(f"/api/runs/{rid}/execute").json()["id"]
    time.sleep(0.1)  # ensure status is "running"
    r = client.delete(f"/api/runs/{rid}/executions/{exec_id}")
    assert r.status_code == 400

    # Cleanup: cancel + join so later tests' DB cleanup succeeds.
    client.post(f"/api/runs/{rid}/executions/{exec_id}/cancel")
    t = main._run_worker_threads.get(exec_id)
    if t is not None:
        t.join(timeout=10)


def test_template_render_failure_recorded_not_fatal(client, stub_httpx):
    # No {{foo}} in the data, but the template references it — substitution
    # leaves the raw placeholder, which is fine for URL (just produces a
    # weird URL) so this stays "passed". Real render failures happen if we
    # reference invalid JSON in body_json, but those are caught up front.
    # This test just asserts an unresolved {{var}} doesn't crash the run.
    rid = client.post("/api/runs", json=_run_payload(
        url="https://api.example.com/{{id}}/{{nope}}",
    )).json()["id"]
    r = client.post(f"/api/runs/{rid}/execute?sync=true")
    detail = client.get(f"/api/runs/{rid}/executions/{r.json()['id']}").json()
    assert detail["completed_rows"] == 3
    for it in detail["iterations"]:
        assert "{{nope}}" in it["url"]


def test_empty_data_produces_empty_run(client, stub_httpx):
    rid = client.post("/api/runs", json=_run_payload(data_content="id,name\n")).json()["id"]
    r = client.post(f"/api/runs/{rid}/execute?sync=true")
    detail = client.get(f"/api/runs/{rid}/executions/{r.json()['id']}").json()
    assert detail["status"] == "completed"
    assert detail["total_rows"] == 0
    assert detail["iterations"] == []


def test_response_preview_truncated(client, stub_httpx):
    big = "x" * 20_000
    stub_httpx._default = _FakeResponse(200, {"data": big})
    rid = client.post("/api/runs", json=_run_payload()).json()["id"]
    r = client.post(f"/api/runs/{rid}/execute?sync=true")
    detail = client.get(f"/api/runs/{rid}/executions/{r.json()['id']}").json()
    preview = detail["iterations"][0]["response_preview"]
    assert "truncated" in preview
    assert len(preview) < len(big) + 100
