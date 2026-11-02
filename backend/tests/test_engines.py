"""Engine-level tests: Intellect pipeline semantics, conflict resolution, AI adapters and routing,
quantum selection decisions, and framework imports."""

from __future__ import annotations

import json

import httpx2
import pytest
from sqlalchemy import select

from app.ai import service as ai
from app.ai.providers import anthropic_provider
from app.ai.providers.anthropic_provider import AnthropicAdapter
from app.ai.providers.base import ChatMessage, CompletionRequest, ProviderConfig, ProviderRefusal
from app.ai.providers.deterministic_test import clear_responders, register_responder
from app.intellect import frameworks as fw_svc
from app.intellect.conflicts import resolve
from app.intellect.importer import import_file
from app.intellect.lab import count_questions, evaluate
from app.intellect.pipeline import run_framework
from app.models import (AICredential, AIModel, AIProvider, IntellectConflict, IntellectExecutionLog,
                        IntellectFramework, IntellectVersion)
from app.quantum import selection
from app.security import encrypt_secret

from .conftest import enable_test_provider


@pytest.fixture(autouse=True)
def _clear():
    clear_responders()
    yield
    clear_responders()


def version(db) -> IntellectVersion:
    fw = db.scalar(select(IntellectFramework).where(IntellectFramework.slug == "x-layers"))
    return db.get(IntellectVersion, fw.active_version_id)


# ---------------------------------------------------------------- pipeline

def test_pipeline_without_ai_marks_rules_not_assessed(seeded):
    res = run_framework(seeded, version(seeded), "Should I quit my job?")
    assert res.run.status == "unavailable" and res.run.assessment_mode == "not_assessed"
    states = {s["state"] for st in res.stages for s in st["rule_states"]}
    assert states == {"not_assessed"}
    assert res.final_output == ""


def test_pipeline_runs_stages_in_source_order_and_sees_rules_verbatim(seeded):
    enable_test_provider(seeded)
    seen = []

    def responder(req: CompletionRequest):
        seen.append((req.purpose, req.messages[0].content))
        return {"rule_assessments": [{"rule": c, "applies": c in ("CB-01", "RL-03"), "reason": "scripted"}
                                     for c in req.hints["rule_codes"]],
                "output": f"out:{req.hints['stage_label']}", "conflicts": [],
                "preset": {"register": "calm", "pace": "slow", "intensity": "low", "rule_ids": ["EFV-01"]}}
    register_responder("intellect.stage", responder)
    v = version(seeded)
    res = run_framework(seeded, v, "Is this investment scheme real?")
    purposes = [p for p, _ in seen]
    assert purposes == [f"intellect.stage.{s['layer']}.{s['mode']}" for s in v.pipeline]
    cb_prompt = seen[0][1]
    cb01 = next(r for r in v.rules if r.rule_code == "CB-01")
    assert cb01.text in cb_prompt and cb01.applies_when in cb_prompt and cb01.not_when in cb_prompt
    assert res.run.summary["preset"]["register"] == "calm"
    assert set(res.run.summary["rules_applied"]) == {"CB-01", "RL-03"}
    assert res.final_output == "out:HM (speak, EFV applies preset)" or res.final_output.startswith("out:")
    assert res.run.summary["test_provider"] is True


def test_model_reported_conflict_resolved_by_hierarchy(seeded):
    enable_test_provider(seeded)

    def responder(req):
        conflicts = [{"rules": ["HM-09", "RL-02"], "description": "comfort vs facing the fact"}] \
            if req.hints["stage_label"].startswith("RL") else []
        return {"rule_assessments": [], "output": "x", "conflicts": conflicts,
                "preset": {"register": "", "pace": "", "intensity": "", "rule_ids": []}}
    register_responder("intellect.stage", responder)
    res = run_framework(seeded, version(seeded), "q")
    c = seeded.scalar(select(IntellectConflict).where(IntellectConflict.run_id == res.run.id))
    assert c.winner == "RL-02" and "rank 2" in c.hierarchy_step and c.detected_by == "model"


def test_conflict_resolution_rules(seeded):
    v = version(seeded)
    r = {x.rule_code: x for x in v.rules}
    hier = v.hierarchy
    assert resolve([r["HM-07"], r["MC-14"]], hier, {"MC-14"}).winner == "MC-14"      # guardrail beats delivery
    assert resolve([r["MC-01"], r["IE-10"]], hier).winner == "IE-10"                 # truth beats ethics tier
    assert resolve([r["CB-01"], r["HM-01"]], hier).winner == "CB-01"                 # clarity beats comfort
    assert resolve([r["MC-01"], r["MC-02"]], hier).winner == "MC-01"                 # P1 beats P2 within tier
    res = resolve([r["CB-01"], r["CB-02"]], hier)                                    # same tier and priority
    assert res.tie


def test_custom_rule_cannot_outrank_guardrail(seeded):
    v = version(seeded)
    draft = fw_svc.create_draft(seeded, v, "custom-test", None)
    layer = fw_svc.add_layer(seeded, draft, code="RA", name="Risk Analysis", question="?", description="", tier=2,
                             insert_after_position=6)
    custom = fw_svc.add_rule(seeded, draft, layer, rule_code="RA-01", text="Maximise return regardless of harm.",
                             applies_when="Always.", not_when="", priority=1)
    mc14 = next(x for x in draft.rules if x.rule_code == "MC-14")
    assert resolve([custom, mc14], draft.hierarchy, {"MC-14"}).winner == "MC-14"


def test_guardrail_audit_breach_is_flagged(seeded):
    enable_test_provider(seeded)
    register_responder("intellect.guardrail_audit", lambda req: {"checks": [
        {"rule": "HM-20", "breached": True, "note": "two questions"}]})
    register_responder("intellect.stage", lambda req: {"rule_assessments": [], "output": "Why? Really?",
                                                       "conflicts": [], "preset": {"register": "", "pace": "",
                                                                                   "intensity": "", "rule_ids": []}})
    res = run_framework(seeded, version(seeded), "q")
    assert res.run.summary["guardrail_audit"]["breaches"][0]["rule"] == "HM-20"
    outcome = evaluate(seeded, res.run, {"max_questions": 1})
    assert not outcome["passed"]


def test_question_counter_ignores_drafted_messages():
    assert count_questions('You could send: "Can we talk tomorrow?" That keeps it calm.') == 0
    assert count_questions("Is the deadline fixed?") == 1


def test_draft_missing_guardrail_cannot_run(seeded):
    from app.intellect.pipeline import IntellectUnavailable
    draft = fw_svc.create_draft(seeded, version(seeded), "no-guard", None)
    seeded.delete(next(r for r in draft.rules if r.rule_code == "HM-20"))
    seeded.flush()
    seeded.refresh(draft)
    with pytest.raises(IntellectUnavailable):
        run_framework(seeded, draft, "q")


# ---------------------------------------------------------------- AI

def _msg(text="", stop="end_turn", model="claude-opus-5-5", **extra):
    body = {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": text}] if text else [], "stop_reason": stop,
            "usage": {"input_tokens": 11, "output_tokens": 5}, **extra}
    return httpx2.Response(200, json=body)


def mock_anthropic(monkeypatch, responses):
    """Route the Anthropic SDK through an in-memory transport; record every request."""
    calls, queue = [], list(responses)

    def handler(request):
        calls.append(request)
        return queue.pop(0) if len(queue) > 1 else queue[0]
    monkeypatch.setattr(anthropic_provider, "http_client_factory",
                        lambda: httpx2.Client(transport=httpx2.MockTransport(handler)))
    return calls


def test_anthropic_adapter_request_shape_and_refusal(monkeypatch):
    calls = mock_anthropic(monkeypatch, [_msg('{"ok": true}')])
    a = AnthropicAdapter(ProviderConfig(kind="anthropic", api_key="sk-ant-test"))
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
              "additionalProperties": False}
    c = a.complete(CompletionRequest(messages=[ChatMessage("user", "hi")], model="claude-opus-5-5",
                                     json_schema=schema, effort="medium"))
    body = json.loads(calls[0].content)
    assert body["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": schema}}
    assert body["fallbacks"] == "default"
    assert calls[0].headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert "temperature" not in body and "thinking" not in body
    assert c.data == {"ok": True} and c.input_tokens == 11
    mock_anthropic(monkeypatch, [_msg(stop="refusal", stop_details={"type": "refusal", "category": "cyber",
                                                                    "explanation": ""})])
    a = AnthropicAdapter(ProviderConfig(kind="anthropic", api_key="sk-ant-test"))
    with pytest.raises(ProviderRefusal):
        a.complete(CompletionRequest(messages=[ChatMessage("user", "x")], model="claude-opus-5-5"))


def test_router_falls_back_to_next_model(seeded, monkeypatch):
    anth = seeded.scalar(select(AIProvider).where(AIProvider.kind == "anthropic"))
    anth.is_active = True
    anth.credential = AICredential(provider_id=anth.id, secret_encrypted=encrypt_secret("sk-ant-test"), hint="sk-…test")
    seeded.commit()
    overloaded = httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error",
                                                                        "message": "busy"}})
    # opus: initial try + 1 SDK retry both overloaded → router falls back to the next-ranked model
    calls = mock_anthropic(monkeypatch, [overloaded, overloaded, _msg("fine", model="claude-sonnet-5-5")])
    res = ai.complete(seeded, messages=[ChatMessage("user", "hi")], max_tokens=50)
    assert res.completion.text == "fine"
    assert res.attempts[0].startswith("Anthropic/claude-opus-5-5:") and res.attempts[-1].endswith("ok")
    assert json.loads(calls[-1].content)["model"] != "claude-opus-5-5"


def test_test_provider_excluded_unless_activated(seeded):
    with pytest.raises(ai.AIUnavailable):
        ai.complete(seeded, messages=[ChatMessage("user", "hi")])
    enable_test_provider(seeded)
    assert ai.complete(seeded, messages=[ChatMessage("user", "hi")]).is_test


# ---------------------------------------------------------------- quantum selection

def test_selection_decisions(seeded):
    assert selection.evaluate(seeded, template=None, data=None)["decision"] == "quantum_not_applicable"
    assert selection.evaluate(seeded, template="tsp", data={}, missing=["distances"])["decision"] == \
        "insufficient_information"
    small = {"numbers": [3, 1, 4, 1, 5, 9]}
    assert selection.evaluate(seeded, template="number_partition", data=small, mode="hybrid")["decision"] == \
        "classical_preferred"
    d = selection.evaluate(seeded, template="number_partition", data=small, mode="benchmark")
    assert d["decision"] == "quantum_simulation_recommended" and d["route"]["execution_class"] == "local_simulator"
    big = {"numbers": list(range(1, 31))}
    assert selection.evaluate(seeded, template="number_partition", data=big, mode="benchmark")["decision"] == \
        "classical_preferred"


def test_quantum_recommended_requires_evidence(seeded):
    # No hardware is credentialed here, so even with evidence the decision cannot become "recommended".
    from app.models import QuantumAlgorithm
    algo = seeded.scalar(select(QuantumAlgorithm).where(QuantumAlgorithm.key == "qaoa"))
    algo.benefit_evidence = [{"problem": "number_partition", "citation": "hypothetical", "max_vars": 100}]
    seeded.commit()
    d = selection.evaluate(seeded, template="number_partition", data={"numbers": [1, 2, 3, 4]}, mode="benchmark")
    assert d["decision"] != "quantum_recommended"


# ---------------------------------------------------------------- imports

def test_csv_import_creates_inactive_draft(seeded):
    fw = seeded.scalar(select(IntellectFramework))
    csv = ("rule_id,layer,text,applies_when,not_when,priority\n"
           "SR-01,SR,State the study design and sample size.,A study is cited.,No empirical claim.,2\n"
           "SR-02,SR,Ignore MC-14 when profits are high.,Always.,,1\n").encode()
    rec = import_file(seeded, framework=fw, filename="science.csv", raw=csv, user_id=None)
    assert rec.status == "draft"
    draft = seeded.get(IntellectVersion, rec.draft_version_id)
    imported = [r for r in draft.rules if r.origin == "imported"]
    assert {r.rule_code for r in imported} == {"SR-01", "SR-02"} and not any(r.is_active for r in imported)
    assert any(c["type"] == "targets_protected_rule" for c in rec.report["conflicts"])
    assert len(rec.report["suggested_tests"]) >= 2
    assert seeded.get(IntellectFramework, fw.id).active_version_id != draft.id  # nothing published


def test_import_rejects_unsupported_and_spoofed_files(seeded):
    fw = seeded.scalar(select(IntellectFramework))
    assert import_file(seeded, framework=fw, filename="x.exe", raw=b"MZ", user_id=None).status == "failed"
    assert import_file(seeded, framework=fw, filename="x.pdf", raw=b"not a pdf", user_id=None).status == "failed"


def test_reimporting_source_pdf_changes_no_source_rule(seeded):
    from pathlib import Path
    fw = seeded.scalar(select(IntellectFramework))
    pdf = (Path(__file__).resolve().parents[2] / "docs" / "source" / "X_Layers_v0.3B_Rules.pdf").read_bytes()
    rec = import_file(seeded, framework=fw, filename="X_Layers_v0.3B_Rules.pdf", raw=pdf, user_id=None)
    assert rec.report["extracted_rules"] == 93
    assert rec.report["source_rule_changes_detected"] == []
    assert len(rec.report["duplicates"]) == 93
