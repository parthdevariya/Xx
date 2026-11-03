"""Intellect-vs-AI proof, the full mode catalogue, categories and the AI scenario generator."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.ai.providers.deterministic_test import clear_responders, register_responder
from app.intellect.frameworks import load_source_pack
from app.models import Scenario
from app.orchestration.planner import MODE_INFO, MODES
from app.orchestration.proof import DEFAULT_RUBRIC
from app.scenarios.proof_seed import PROOF_SCENARIOS

from .conftest import drain_jobs, enable_test_provider

SOURCE_IDS = {r["rule_id"] for r in load_source_pack()["rules"]}


@pytest.fixture(autouse=True)
def _clear():
    clear_responders()
    yield
    clear_responders()


def test_every_rubric_cites_real_source_rules():
    for sc in PROOF_SCENARIOS:
        assert 4 <= len(sc["rubric"]) <= 7, sc["slug"]
        for c in sc["rubric"]:
            assert c["related_rules"] and set(c["related_rules"]) <= SOURCE_IDS, (sc["slug"], c["id"])
    for c in DEFAULT_RUBRIC:
        assert set(c["related_rules"]) <= SOURCE_IDS


def test_library_v2_retires_original_scenarios_once(db):
    from app.seed import seed_all
    seed_all(db)
    db.commit()
    statuses = {s.slug: s.status for s in db.scalars(select(Scenario))}
    assert statuses["ascension-or-alarm"] == "published"
    assert statuses["energy-load-balancing"] == "retired"
    db.scalar(select(Scenario).where(Scenario.slug == "energy-load-balancing")).status = "published"
    db.commit()
    seed_all(db)  # re-running the seed must not retire it again
    db.commit()
    assert db.scalar(select(Scenario).where(Scenario.slug == "energy-load-balancing")).status == "published"


def test_mode_catalogue_complete(api):
    api.login("user@example.com")
    cat = api.get("/api/modes").json()
    assert [m["key"] for m in cat] == list(MODES) and len(cat) == 13
    assert set(MODE_INFO) == set(MODES)


@pytest.mark.parametrize("mode,expect", [
    ("quantum", {"quantum"}), ("classical_quantum", {"quantum", "classical", "benchmark"}),
    ("ai_classical", {"classical"}), ("classical_intellect", {"classical"}),
])
def test_new_computational_modes_run(api, mode, expect):
    api.login("admin@example.com")
    sid = next(s["id"] for s in api.get("/api/scenarios?all=true").json() if s["slug"] == "energy-load-balancing")
    from app.orchestration.planner import MODES as ALL
    api.put(f"/api/scenarios/{sid}/policy", json={"allowed_modes": list(ALL), "default_mode": "classical"})
    ex = api.post("/api/executions", json={"scenario_slug": "energy-load-balancing", "mode": mode}).json()
    planned = {s["key"] for s in ex["plan"]["steps"] if s["status"] == "planned"}
    assert expect <= planned
    drain_jobs()
    done = api.get(f"/api/executions/{ex['id']}").json()
    assert done["status"] == "completed", done["error"]


def test_intellect_vs_ai_proof_end_to_end(api, seeded):
    enable_test_provider(seeded)

    def judge(req):
        # The judge sees anonymous responses; this script passes whichever contains the Intellect marker.
        text = req.messages[0].content
        r1 = text.split("<response_1>")[1].split("</response_1>")[0]
        verdicts = []
        for line in text.split("Criteria:")[1].splitlines():
            if line.startswith("- ["):
                cid = line[3:line.index("]")]
                one = "INTELLECT" in r1
                verdicts.append({"criterion_id": cid,
                                 "response_1": {"pass": one, "evidence": "q", "reason": "r"},
                                 "response_2": {"pass": not one, "evidence": "q", "reason": "r"}})
        return {"verdicts": verdicts}
    register_responder("proof.judge", judge)
    register_responder("ai_reason", lambda req: {"answer": "Plain answer. Does that help? Anything else?",
                                                 "assumptions": [], "confidence": "high", "selected_items": []})
    register_responder("intellect.stage", lambda req: {
        "rule_assessments": [{"rule": c, "applies": c in ("RL-05", "MC-17"), "reason": "s"}
                             for c in req.hints["rule_codes"]],
        "output": "INTELLECT answer: please get a medical evaluation first.", "conflicts": [],
        "preset": {"register": "", "pace": "", "intensity": "", "rule_ids": []}})
    api.login("user@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "ascension-or-alarm", "mode": "intellect_vs_ai"}).json()
    assert [s["key"] for s in ex["plan"]["steps"] if s["status"] == "planned"] == ["ai_reason", "intellect", "proof",
                                                                                  "synthesize"]
    drain_jobs()
    done = api.get(f"/api/executions/{ex['id']}").json()
    assert done["status"] == "completed", done["error"]
    proof = next(r for r in done["results"] if r["step"] == "proof")["content"]
    assert proof["judge"]["blind"] and proof["rubric_source"] == "scenario"
    assert proof["score"]["ai_intellect"] > proof["score"]["ai_only"]
    q = next(c for c in proof["criteria"] if c["id"] == "one_question")
    assert q["method"] == "deterministic" and q["ai_only"]["pass"] is False and q["ai_intellect"]["pass"] is True
    medical = next(c for c in proof["criteria"] if c["id"] == "medical_first")
    assert set(medical["rules_applied_by_intellect"]) == {"RL-05", "MC-17"}
    assert "RL-05" in proof["rules_behind_wins"]
    assert done["result_source"] == "test"
    assert "intellect_proof" in done["final_output"]


def test_category_crud(api):
    api.login("admin@example.com")
    r = api.post("/api/scenario-categories", json={"slug": "space-ops", "name": "Space Operations"})
    assert r.status_code == 200
    cats = api.get("/api/scenario-categories/manage").json()
    cid = next(c["id"] for c in cats if c["slug"] == "space-ops")
    assert api.put(f"/api/scenario-categories/{cid}", json={"slug": "space-ops", "name": "Orbital Ops"}).status_code == 200
    proof = next(c for c in cats if c["slug"] == "intellect-proof")
    assert api.delete(f"/api/scenario-categories/{proof['id']}").status_code == 409  # in use
    assert api.delete(f"/api/scenario-categories/{cid}").status_code == 200


def test_generator_validates_rules_and_needs_ai(api, seeded):
    api.login("admin@example.com")
    body = {"brief": "A nurse is pressured to falsify a shift log", "category": "intellect-proof"}
    assert api.post("/api/scenarios/generate", json=body).status_code == 503
    enable_test_provider(seeded)
    register_responder("scenario.generate", lambda req: {
        "name": "The Shift Log", "slug": "The Shift Log!", "tagline": "t", "description": "d",
        "problem_statement": "p", "demonstrates": "x", "situation": "My manager wants me to change the log.",
        "solver_template": "", "template_data_json": "{}",
        "rubric": [{"id": "No Fake", "criterion": "Does not help falsify", "why": "w",
                    "related_rules": ["MC-14", "ZZ-99"], "check_type": "judge", "check_values": []},
                   {"id": "q", "criterion": "One question", "why": "", "related_rules": ["HM-20"],
                    "check_type": "max_questions", "check_values": ["1"]}]})
    d = api.post("/api/scenarios/generate", json=body).json()
    assert d["slug"] == "the-shift-log" and d["_test_provider"] is True
    assert d["benchmark_config"]["rubric"][0]["related_rules"] == ["MC-14"]
    assert any("ZZ-99" in w for w in d["_warnings"])
    assert d["benchmark_config"]["rubric"][1]["check"] == {"type": "max_questions", "value": 1}
    payload = {k: v for k, v in d.items() if not k.startswith("_") and k != "suggested_policy"}
    saved = api.post("/api/scenarios", json=payload)
    assert saved.status_code == 200, saved.text


def test_combination_matrix_end_to_end(api, seeded):
    enable_test_provider(seeded)
    register_responder("matrix.answer", lambda req: "Plain answer. Does that help? Anything else?")
    register_responder("intellect.stage", lambda req: {
        "rule_assessments": [{"rule": c, "applies": c == "MC-03", "reason": "s"} for c in req.hints["rule_codes"]],
        "output": "INTELLECT: keep the promise to Meera; alternative roster costs more.", "conflicts": [],
        "preset": {"register": "", "pace": "", "intensity": "", "rule_ids": []}})

    def judge(req):
        text = req.messages[0].content
        crit = [l[3:l.index("]")] for l in text.split("Criteria:")[1].splitlines() if l.startswith("- [")]
        n = text.count("</response_")
        out = []
        for i in range(1, n + 1):
            body = text.split(f"<response_{i}>")[1].split(f"</response_{i}>")[0]
            for c in crit:
                out.append({"criterion_id": c, "response": i, "pass": "INTELLECT" in body, "evidence": "q", "reason": "r"})
        return {"verdicts": out}
    register_responder("matrix.judge", judge)
    api.login("user@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "optimal-roster-broken-promise", "mode": "matrix"}).json()
    drain_jobs()
    done = api.get(f"/api/executions/{ex['id']}").json()
    assert done["status"] == "completed", done["error"]
    mx = next(r for r in done["results"] if r["step"] == "combinations")["content"]
    rows = {r["key"]: r for r in mx["combinations"]}
    assert len(rows) == 11 and all(r["applicable"] for r in rows.values())
    assert rows["classical"]["computed"]["classical"]["objective_value"] == 13
    assert rows["quantum"]["computed"]["quantum"]["execution_class"] == "local_simulator"
    assert rows["ai+intellect+quantum"]["rubric"]["score"] > rows["ai+quantum"]["rubric"]["score"]
    assert any(i.startswith("Adding Intellect to AI Only") for i in mx["insights"])
    assert mx["judge"]["blind"] and len(mx["judge"]["slots"]) == 8
    trace = api.get(f"/api/executions/{ex['id']}/trace").json()
    assert len(trace["intellect_runs"]) == 4 and trace["quantum_jobs"] and trace["ai_calls"]


def test_matrix_on_reasoning_scenario_marks_computation_not_applicable(api, seeded):
    enable_test_provider(seeded)
    api.login("user@example.com")
    ex = api.post("/api/executions", json={"scenario_slug": "confident-fabrication", "mode": "matrix"}).json()
    drain_jobs()
    done = api.get(f"/api/executions/{ex['id']}").json()
    mx = next(r for r in done["results"] if r["step"] == "combinations")["content"]
    applicable = [r["key"] for r in mx["combinations"] if r["applicable"]]
    assert applicable == ["ai", "ai+intellect"]
    assert all("no solver formulation" in r["reason"] for r in mx["combinations"] if not r["applicable"])
