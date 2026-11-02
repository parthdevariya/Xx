"""End-to-end API tests: auth, RBAC, CSRF, scenarios, executions in every mode, events, reports, audit."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, IntellectFramework, IntellectVersion

from .conftest import drain_jobs, enable_test_provider


def test_auth_flow_and_csrf(api):
    assert api.get("/api/auth/me").status_code == 401
    me = api.login("admin@example.com")
    assert me["role"] == "super_admin" and "intellect.publish" in me["permissions"]
    r = api.c.post("/api/auth/logout")  # no CSRF header
    assert r.status_code == 403
    assert api.post("/api/auth/logout").status_code == 200
    assert api.get("/api/auth/me").status_code == 401


def test_wrong_password_is_audited(api, seeded):
    r = api.c.post("/api/auth/login", json={"email": "admin@example.com", "password": "nope-nope-nope"})
    assert r.status_code == 401
    assert seeded.scalar(select(AuditLog).where(AuditLog.action == "login_failed")) is not None


def test_rbac_server_side(api):
    api.login("user@example.com")
    assert api.get("/api/ai/providers").status_code == 403
    assert api.get("/api/admin/dashboard").status_code == 403
    assert api.get("/api/scenarios").status_code == 200


def test_system_status_reports_real_state(api):
    s = api.get("/api/system/status").json()
    assert s["intellect"] == {"framework": "X Layers", "version": "v0.3B", "layers": 10, "rules": 93,
                              "protected": 10, "status": "ready"}
    assert s["ai"]["status"] == "unconfigured"  # no keys on the test machine; never faked
    local = next(p for p in s["quantum"]["providers"] if p["vendor"] == "local")
    assert local["status"] == "healthy"
    ibm = next(p for p in s["quantum"]["providers"] if p["vendor"] == "ibm")
    assert ibm["status"] in ("unavailable", "unconfigured")


def test_protected_rule_cannot_be_changed_through_api(api, seeded):
    api.login("admin@example.com")
    fw = seeded.scalar(select(IntellectFramework))
    v = api.get(f"/api/intellect/versions/{fw.active_version_id}").json()
    draft_id = api.post(f"/api/intellect/versions/{v['id']}/drafts", json={"label": "d1"}).json()["id"]
    draft = api.get(f"/api/intellect/versions/{draft_id}").json()
    mc14 = next(r for r in draft["rules"] if r["rule_code"] == "MC-14")
    r = api.patch(f"/api/intellect/rules/{mc14['id']}", json={"is_active": False})
    assert r.status_code == 403 and "protected" in r.json()["detail"]
    assert seeded.scalar(select(AuditLog).where(AuditLog.action == "rule_update_refused")) is not None


def test_scenarios_are_database_driven(api):
    api.login("admin@example.com")
    lst = api.get("/api/scenarios").json()
    assert {"logistics-routing", "portfolio-allocation", "strategic-decision-review"} <= {s["slug"] for s in lst}
    body = {"slug": "test-cut", "category": "optimization", "name": "Grid cut", "solver_template": "max_cut",
            "fields": [{"key": "n", "type": "number", "required": True},
                       {"key": "edges", "type": "json", "required": True}],
            "defaults": {"n": 4, "edges": [[0, 1], [1, 2], [2, 3], [3, 0]]}}
    created = api.post("/api/scenarios", json=body).json()
    assert created["status"] == "draft"
    api.login("user@example.com")
    assert "test-cut" not in {s["slug"] for s in api.get("/api/scenarios").json()}
    api.login("admin@example.com")
    assert api.post(f"/api/scenarios/{created['id']}/status", json={"status": "published"}).status_code == 200
    api.login("user@example.com")
    assert "test-cut" in {s["slug"] for s in api.get("/api/scenarios").json()}


def test_scenario_input_validation(api):
    api.login("user@example.com")
    r = api.post("/api/executions", json={"scenario_slug": "energy-load-balancing", "mode": "classical",
                                          "inputs": {"numbers": "not a list"}})
    assert r.status_code == 422


def test_classical_execution_end_to_end(api):
    api.login("user@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "energy-load-balancing", "mode": "classical"}).json()
    assert ex["status"] == "queued"
    assert drain_jobs() >= 1
    done = api.get(f"/api/executions/{ex['id']}").json()
    assert done["status"] == "completed", done["error"]
    classical = next(r for r in done["results"] if r["step"] == "classical")
    assert classical["content_class"] == "computed" and classical["execution_class"] == "classical"
    assert classical["content"]["feasible"] and classical["content"]["proven_optimal"]
    # loads sum to 206: a perfect 103/103 split exists, so imbalance objective is 0
    assert classical["content"]["objective_value"] == 0
    events = api.get(f"/api/executions/{ex['id']}/events").json()
    types = [e["type"] for e in events]
    assert types[0] == "problem.received" and "plan.generated" in types and types[-1] == "execution.completed"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    md = api.get(f"/api/executions/{ex['id']}/report.md")
    assert md.status_code == 200 and "Executive Summary" in md.text


def test_quantum_simulation_runs_and_is_labelled(api):
    api.login("user@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "portfolio-allocation", "mode": "ai_quantum"}).json()
    assert ex["plan"]["quantum_decision"]["decision"] == "quantum_simulation_recommended"
    drain_jobs()
    done = api.get(f"/api/executions/{ex['id']}").json()
    assert done["status"] == "completed", done["error"]
    q = next(r for r in done["results"] if r["step"] == "quantum")
    assert q["execution_class"] == "local_simulator"  # never presented as hardware
    assert q["content"]["qubits"] == 8
    assert done["final_output"]["quantum_contribution"]["content"]["execution_class"] == "local_simulator"
    assert any("simulator" in l for l in done["final_output"]["limitations"]["content"])


def test_large_problem_classical_preferred(api):
    api.login("user@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "supply-chain-allocation", "mode": "hybrid"}).json()
    qd = ex["plan"]["quantum_decision"]
    assert qd["decision"] == "classical_preferred" and len(qd["factors"]) == 15
    quantum_step = next(s for s in ex["plan"]["steps"] if s["key"] == "quantum")
    assert quantum_step["status"] == "skipped"


def test_reasoning_scenario_without_ai_is_honest(api):
    api.login("user@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "strategic-decision-review",
                                           "mode": "ai_intellect"}).json()
    assert ex["status"] == "awaiting_input"
    assert "no AI provider" in ex["error"]
    assert ex["plan"]["quantum_decision"]["decision"] == "quantum_not_applicable"


def test_hybrid_with_test_provider_runs_all_engines(api, seeded):
    enable_test_provider(seeded)
    api.login("user@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "portfolio-allocation", "mode": "benchmark"}).json()
    drain_jobs()
    done = api.get(f"/api/executions/{ex['id']}").json()
    assert done["status"] == "completed", done["error"]
    assert done["result_source"] == "test"  # the test provider is never reported as live
    steps = {r["step"] for r in done["results"]}
    assert {"classical", "quantum", "ai_reason", "intellect"} <= steps
    ai = next(r for r in done["results"] if r["step"] == "ai_reason")
    assert ai["content_class"] == "test" and "verification" in ai["content"]
    metrics = {(m["approach"], m["metric"]) for m in done["benchmark"]["metrics"]}
    assert ("classical", "objective_value") in metrics and ("ai_only", "objective_value") in metrics
    assert "not evidence" in done["benchmark"]["methodology"]["timing"]
    assert "quantum advantage" in done["benchmark"]["conclusion"]
    run = api.get(f"/api/intellect/runs/{done['intellect_runs'][0]}")
    assert run.status_code == 403  # standard users cannot read Intellect admin data
    api.login("admin@example.com")
    run = api.get(f"/api/intellect/runs/{done['intellect_runs'][0]}").json()
    assert [(s["layer"], s["mode"]) for s in run["stages"]][:4] == [("CB", "main"), ("TP", "frame"),
                                                                     ("HM", "read"), ("EFV", "select_preset")]
    assert len(run["stages"]) == 13


def test_cancel_before_start(api):
    api.login("user@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "energy-load-balancing", "mode": "classical",
                                           "auto_run": False}).json()
    assert ex["status"] == "planned"
    assert api.post(f"/api/executions/{ex['id']}/cancel").json()["status"] == "cancelled"
    assert drain_jobs() == 0


def test_users_cannot_see_each_others_executions(api, seeded):
    from .conftest import make_user
    make_user(seeded, "other@example.com", "standard")
    api.login("user@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "energy-load-balancing", "mode": "classical",
                                           "auto_run": False}).json()
    api.login("other@example.com")
    assert api.get(f"/api/executions/{ex['id']}").status_code == 404


def test_free_text_problem_classified_without_ai(api):
    api.login("user@example.com")
    ex = api.post("/api/executions", json={
        "text": "split these loads into two equal groups", "mode": "classical",
        "inputs": {"numbers": [4, 5, 6, 7, 8]}}).json()
    assert ex["problem"]["structured"]["method"] == "pattern_classifier"
    assert ex["problem"]["structured"]["solver_template"] == "number_partition"


def test_lab_run_through_queue(api, seeded):
    enable_test_provider(seeded)
    api.login("admin@example.com")
    v = seeded.scalar(select(IntellectVersion).where(IntellectVersion.status == "published"))
    job = api.post("/api/intellect/lab/run", json={"version_id": v.id, "prompt": "Should I lend my cousin money?",
                                                   "layer_switches": {"MC": False}}).json()
    drain_jobs()
    res = api.get(f"/api/intellect/lab/jobs/{job['job_id']}").json()
    assert res["status"] == "done"
    run = api.get(f"/api/intellect/runs/{res['result']['run_id']}").json()
    mc = next(s for s in run["stages"] if s["layer"] == "MC")
    assert mc["status"] == "protected_only"
    assessed = {s["rule"] for s in mc["rule_states"] if s["state"] != "disabled"}
    assert assessed == {"MC-14", "MC-17", "MC-18", "MC-19"}


def test_admin_dashboard_counts_are_real(api):
    api.login("admin@example.com")
    d = api.get("/api/admin/dashboard").json()
    assert d["users"]["total"] == 2 and d["executions"]["total"] == 0
    assert d["frameworks"]["rules"] == 93


def test_openapi_documented(api):
    spec = api.get("/openapi.json").json()
    assert "/api/executions" in spec["paths"] and "/api/intellect/lab/run" in spec["paths"]


def test_duplicate_framework_and_missing_fields(api, seeded):
    api.login("admin@example.com")
    fw = seeded.scalar(select(IntellectFramework))
    for slug in ("copy-one", "copy-two"):  # second duplicate used to collide on the draft label
        r = api.post("/api/intellect/frameworks", json={"name": slug, "slug": slug,
                                                        "duplicate_from_version_id": fw.active_version_id})
        assert r.status_code == 200, r.text
    d = api.post("/api/quantum/evaluate", json={"template": "knapsack", "data": {"values": [1, 2]}}).json()
    assert d["decision"] == "insufficient_information"
    assert any(m.startswith("weights") for m in d["missing"]) and any(m.startswith("capacity") for m in d["missing"])
