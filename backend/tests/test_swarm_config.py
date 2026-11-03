"""Swarm Intelligence configuration, Swarm-only mode and the Zep Cloud integration (mock transport)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.integrations import zep

from .conftest import drain_jobs, enable_test_provider


@pytest.fixture()
def zep_mock(monkeypatch):
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        path = request.url.path
        if request.headers.get("authorization") != "Api-Key zk-test-key-1234":
            return httpx.Response(401, json={"message": "unauthorized"})
        if path.endswith("/graphs/list"):
            return httpx.Response(200, json={"items": [], "next_cursor": None})
        if path.endswith("/graphs") and request.method == "POST":
            return httpx.Response(201, json={"uuid": "g-123", "name": "x"})
        if "/episodes" in path:
            return httpx.Response(202, json={"episode": {"processed": False}, "task": {"uuid": "t1"}})
        if path.endswith("/search/edges"):
            return httpx.Response(200, json={"items": [{"fact": "Agents distrust the employer", "source_node_name": "a",
                                                        "target_node_name": "b"}]})
        return httpx.Response(404, json={})
    monkeypatch.setattr(zep, "transport", httpx.MockTransport(handler))
    return calls


def test_config_validation_and_audit(api):
    api.login("admin@example.com")
    ov = api.get("/api/admin/swarm").json()
    assert ov["integrations"]["llm"]["required"] and not ov["integrations"]["zep"]["required"]
    assert ov["integrations"]["llm"]["status"] == "missing"
    bad = api.put("/api/admin/swarm/config", json={"platforms": {"feed": False, "forum": False}})
    assert bad.status_code == 422
    bad = api.put("/api/admin/swarm/config", json={"allowed_actions": ["LIKE_POST"]})
    assert bad.status_code == 422 and "writing action" in bad.json()["detail"]
    ok = api.put("/api/admin/swarm/config", json={"agents": 99, "rounds": 3, "platforms": {"forum": False}}).json()
    assert ok["config"]["agents"] == 40 and ok["config"]["platforms"] == {"feed": True, "forum": False}
    assert ok["estimate"]["model_calls_per_run"] == 3 + 3
    api.login("user@example.com")
    assert api.put("/api/admin/swarm/config", json={"rounds": 2}).status_code == 403


def test_swarm_mode_respects_config(api, seeded):
    enable_test_provider(seeded)
    api.login("admin@example.com")
    api.put("/api/admin/engine-switches", json={"swarm": True})
    api.put("/api/admin/swarm/config", json={"agents": 5, "rounds": 3, "platforms": {"forum": False},
                                             "allowed_actions": ["CREATE_POST", "LIKE_POST", "DO_NOTHING"]})
    ex = api.post("/api/executions", json={"scenario_slug": "tell-me-im-right", "mode": "swarm",
                                           "swarm_variable": "A respected auditor publishes the café's real accounts"}).json()
    assert [s["key"] for s in ex["plan"]["steps"] if s["status"] == "planned"] == ["swarm", "synthesize"]
    drain_jobs()
    done = api.get(f"/api/executions/{ex['id']}").json()
    assert done["status"] == "completed", done["error"]
    c = next(r for r in done["results"] if r["step"] == "swarm")["content"]
    assert {r["platform"] for r in c["rounds"]} == {"feed"}
    assert {a["action"] for a in c["actions"]} <= {"CREATE_POST", "LIKE_POST", "DO_NOTHING"}
    assert c["variable"] == {"text": "A respected auditor publishes the café's real accounts", "round": 2}
    types = [e["type"] for e in api.get(f"/api/executions/{ex['id']}/events").json()]
    assert "swarm.variable.injected" in types and "intellect.activated" not in types  # swarm only, no 13 stages
    assert "swarm_prediction" in done["final_output"]


def test_swarm_mode_skipped_when_switched_off(api, seeded):
    enable_test_provider(seeded)
    api.login("admin@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "tell-me-im-right", "mode": "swarm"}).json()
    step = next(s for s in ex["plan"]["steps"] if s["key"] == "swarm")
    assert step["status"] == "skipped" and "Swarm Intelligence is switched OFF" in step["reason"]


def test_zep_integration_health_and_memory(api, seeded, zep_mock):
    enable_test_provider(seeded)
    api.login("admin@example.com")
    ov = api.put("/api/admin/integrations/zep", json={"api_key": "zk-test-key-1234", "enabled": True}).json()
    z = ov["integrations"]["zep"]
    assert z["configured"] and z["hint"] == "zk-…1234" and "api_key" not in json.dumps(z)
    assert api.put("/api/admin/integrations/zep", json={"base_url": "http://insecure"}).status_code == 422
    z = api.post("/api/admin/integrations/zep/health").json()["integrations"]["zep"]
    assert z["status"] == "healthy"
    assert zep_mock[-1].url.path == "/api/v4/graphs/list" and zep_mock[-1].url.params["page_size"] == "1"
    api.put("/api/admin/engine-switches", json={"swarm": True})
    api.put("/api/admin/swarm/config", json={"agents": 4, "rounds": 1, "memory_backend": "zep"})
    ex = api.post("/api/executions", json={"scenario_slug": "tell-me-im-right", "mode": "swarm"}).json()
    drain_jobs()
    c = next(r for r in api.get(f"/api/executions/{ex['id']}").json()["results"] if r["step"] == "swarm")["content"]
    assert c["memory"]["backend"] == "zep" and c["memory"]["zep_graph"] == "g-123"
    assert c["memory"]["episodes"] >= 2 and c["memory"]["report_facts"][0]["fact"] == "Agents distrust the employer"
    paths = [r.url.path for r in zep_mock]
    assert "/api/v4/graphs" in paths and "/api/v4/graphs/g-123/episodes" in paths and "/api/v4/graphs/g-123/search/edges" in paths
    reply = api.post(f"/api/executions/{ex['id']}/swarm/chat", json={"target": "report", "message": "Why?"}).json()
    assert reply["memory_facts"] == 1


def test_zep_failure_falls_back_to_internal_memory(api, seeded, monkeypatch):
    enable_test_provider(seeded)
    monkeypatch.setattr(zep, "transport", httpx.MockTransport(lambda r: httpx.Response(500, text="boom")))
    api.login("admin@example.com")
    api.put("/api/admin/integrations/zep", json={"api_key": "zk-test-key-1234", "enabled": True})
    api.put("/api/admin/engine-switches", json={"swarm": True})
    api.put("/api/admin/swarm/config", json={"agents": 4, "rounds": 1, "memory_backend": "zep"})
    ex = api.post("/api/executions", json={"scenario_slug": "tell-me-im-right", "mode": "swarm"}).json()
    drain_jobs()
    done = api.get(f"/api/executions/{ex['id']}").json()
    assert done["status"] == "completed"
    c = next(r for r in done["results"] if r["step"] == "swarm")["content"]
    assert c["memory"]["backend"] == "internal" and "Zep unavailable" in c["memory"]["errors"][0]
    assert c["report"] is not None
