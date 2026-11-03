"""Master Control switchboard enforcement and the Swarm Intelligence pipeline."""

from __future__ import annotations

from .conftest import drain_jobs, enable_test_provider


def _set(api, **kw):
    r = api.put("/api/admin/engine-switches", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_switchboard_permissions_and_audit(api):
    api.login("user@example.com")
    sw = api.get("/api/engine-switches").json()
    assert sw["can_edit"] is False and sw["switches"]["ai"] is True and len(sw["layers"]) == 10
    assert api.put("/api/admin/engine-switches", json={"ai": False}).status_code == 403
    api.login("admin@example.com")
    assert _set(api, quantum=False)["quantum"] is False
    assert api.put("/api/admin/engine-switches", json={"bogus": True}).status_code == 422
    log = api.get("/api/admin/audit?q=engine_switches").json()
    assert log and log[0]["detail"]["quantum"] == {"from": True, "to": False}
    assert api.get("/api/system/status").json()["switches"]["quantum"] is False


def test_quantum_off_skips_quantum(api):
    api.login("admin@example.com")
    _set(api, quantum=False)
    ex = api.post("/api/executions", json={"scenario_slug": "portfolio-allocation", "mode": "ai_quantum"}).json()
    q = next(s for s in ex["plan"]["steps"] if s["key"] == "quantum")
    assert q["status"] == "skipped" and "switched OFF" in q["reason"]


def test_ai_off_blocks_even_test_provider(api, seeded):
    enable_test_provider(seeded)
    api.login("admin@example.com")
    _set(api, ai=False)
    ex = api.post("/api/executions", json={"scenario_slug": "ascension-or-alarm", "mode": "intellect_vs_ai"}).json()
    assert ex["status"] == "awaiting_input" and "AI engine is switched OFF" in ex["error"]


def test_intellect_off_and_layer_switch(api, seeded):
    enable_test_provider(seeded)
    api.login("admin@example.com")
    _set(api, intellect=False)
    ex = api.post("/api/executions", json={"scenario_slug": "ascension-or-alarm", "mode": "ai_intellect"}).json()
    assert ex["status"] == "awaiting_input" and "Intellect engine is switched OFF" in ex["error"]
    _set(api, intellect=True, layers={"MC": False})
    ex = api.post("/api/executions", json={"scenario_slug": "ascension-or-alarm", "mode": "ai_intellect"}).json()
    drain_jobs()
    run_id = api.get(f"/api/executions/{ex['id']}").json()["intellect_runs"][0]
    run = api.get(f"/api/intellect/runs/{run_id}").json()
    mc = next(s for s in run["stages"] if s["layer"] == "MC")
    assert mc["status"] == "protected_only"  # guardrails survive a master layer switch


def test_swarm_pipeline_stages_and_chat(api, seeded):
    enable_test_provider(seeded)
    api.login("admin@example.com")
    _set(api, swarm=True, swarm_config={"agents": 6, "rounds": 2})
    ex = api.post("/api/executions", json={"scenario_slug": "patience-or-protection", "mode": "ai_intellect"}).json()
    drain_jobs()
    done = api.get(f"/api/executions/{ex['id']}").json()
    assert done["status"] == "completed", done["error"]
    sw = next(r for r in done["results"] if r["step"] == "swarm")
    c = sw["content"]
    assert [s["status"] for s in c["stages"]] == ["done", "done", "done", "done", "available"]
    assert len(c["agents"]) == 6 and len(c["graph"]["entities"]) == 8
    assert len([r for r in c["rounds"]]) >= 2 and c["actions"] and c["metrics"]["computed_from"] == "the recorded action log"
    assert sw["content_class"] == "test" and c["test_provider"] is True
    types = [e["type"] for e in api.get(f"/api/executions/{ex['id']}/events").json()]
    assert "swarm.graph.completed" in types and "swarm.report.completed" in types
    assert types.index("swarm.report.completed") < types.index("intellect.activated")  # swarm feeds Intellect
    reply = api.post(f"/api/executions/{ex['id']}/swarm/chat", json={"target": "a1", "message": "Why?"}).json()
    assert reply["who"] == "Agent 1" and reply["test_provider"] is True
    assert api.post(f"/api/executions/{ex['id']}/swarm/chat", json={"target": "zz", "message": "x"}).status_code == 404


def test_swarm_off_by_default(api, seeded):
    enable_test_provider(seeded)
    api.login("user@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "patience-or-protection", "mode": "ai_intellect"}).json()
    drain_jobs()
    done = api.get(f"/api/executions/{ex['id']}").json()
    assert not any(r["step"] == "swarm" for r in done["results"])
