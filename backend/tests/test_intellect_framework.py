"""Intellect framework acceptance tests (brief, Part 16)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, DatabaseError

from app.intellect import frameworks as fw_svc
from app.intellect.source_parser import parse_pdf
from app.models import (IntellectDependency, IntellectFramework, IntellectGuardrail, IntellectLayer,
                        IntellectReferenceDocument, IntellectRule, IntellectRuleCondition, IntellectVersion)

PDF = Path(__file__).resolve().parents[2] / "docs" / "source" / "X_Layers_v0.3B_Rules.pdf"
GUARDRAILS = ["MC-14", "HM-11", "UL-01", "HM-13", "RL-03", "RL-05", "MC-17", "MC-18", "MC-19", "HM-20"]
EXPECTED_COUNTS = {"CB": 9, "TP": 7, "HM": 14, "EFV": 3, "RL": 7, "IE": 8, "UL": 5, "MC": 19, "FD": 5, "VL": 16}
EXPECTED_SEQUENCE = [("CB", "main"), ("TP", "frame"), ("HM", "read"), ("EFV", "select_preset"), ("RL", "main"),
                     ("IE", "main"), ("UL", "main"), ("MC", "main"), ("TP", "check"), ("FD", "main"),
                     ("VL", "main"), ("HM", "speak"), ("EFV", "apply_preset")]


def active_version(db) -> IntellectVersion:
    fw = db.scalar(select(IntellectFramework).where(IntellectFramework.slug == "x-layers"))
    return db.get(IntellectVersion, fw.active_version_id)


# ---------------------------------------------------------------- source fidelity

def test_pdf_reparses_to_checked_in_pack():
    """The seed is not hand-edited: re-parsing the PDF yields identical rules and hashes."""
    fw = parse_pdf(PDF)
    pack = fw_svc.load_source_pack()
    assert fw.warnings == []
    assert [(r.rule_id, r.sha256) for r in fw.rules] == [(r["rule_id"], r["sha256"]) for r in pack["rules"]]


def test_all_layers_and_rules_imported(seeded):
    v = active_version(seeded)
    assert v.label == "v0.3B" and v.status == "published"
    assert {l.code: sum(1 for r in v.rules if r.layer_id == l.id) for l in v.layers} == EXPECTED_COUNTS
    assert len(v.rules) == 93
    assert all(r.origin == "source" for r in v.rules)


def test_original_metadata_preserved(seeded):
    v = active_version(seeded)
    pack = fw_svc.load_source_pack()
    by_code = {r.rule_code: r for r in v.rules}
    for R in pack["rules"]:
        r = by_code[R["rule_id"]]
        assert (r.text, r.applies_when, r.not_when, r.priority, r.provenance, r.source_marker) == (
            R["text"], R["applies_when"], R["not_when"], R["priority"], R["provenance"], R["source_marker"])
    # spot checks against the PDF wording
    assert by_code["CB-01"].text.startswith("Before answering, pin down exactly what the person is unsure about.")
    assert by_code["MC-14"].priority == 1 and by_code["MC-14"].source_marker == "Hard limit · always on"
    assert by_code["UL-05"].not_when.endswith("want honest accountability (MC-01).")
    assert by_code["MC-17"].not_when.startswith("Clearly fictional or academic discussion")
    assert by_code["HM-20"].provenance == "G-review"
    assert "non-imminent" in by_code["MC-17"].not_when
    layers = {l.code: l for l in v.layers}
    assert layers["VL"].question == "What should be done?"
    assert layers["IE"].name == "Intellect"


def test_rule_ids_are_source_ids_not_renumbered(seeded):
    codes = {r.rule_code for r in active_version(seeded).rules}
    assert "CB-06" not in codes and "CB-11" in codes and "VL-24" in codes


def test_exact_execution_sequence(seeded):
    v = active_version(seeded)
    assert [(s["layer"], s["mode"]) for s in v.pipeline] == EXPECTED_SEQUENCE
    efv = [s for s in v.pipeline if s["layer"] == "EFV"]
    hm = {s["mode"]: s["position"] for s in v.pipeline if s["layer"] == "HM"}
    assert efv[0]["bound_to"] == hm["read"] and efv[1]["bound_to"] == hm["speak"]


def test_conflict_hierarchy_tiers(seeded):
    tiers = {l.code: l.tier for l in active_version(seeded).layers}
    assert tiers == {"RL": 2, "IE": 2, "MC": 3, "VL": 4, "TP": 4, "UL": 4, "FD": 4, "CB": 5, "HM": 6, "EFV": 6}


def test_guardrails_protected(seeded):
    v = active_version(seeded)
    protected = sorted(r.rule_code for r in v.rules if r.is_protected)
    assert protected == sorted(GUARDRAILS)
    kinds = {g.rule_code: g.kind for g in seeded.scalars(select(IntellectGuardrail)
                                                         .where(IntellectGuardrail.version_id == v.id))}
    assert {c for c, k in kinds.items() if k == "hard_limit"} == {"MC-14", "MC-17", "MC-18", "MC-19"}


def test_dependencies_extracted_from_source_text(seeded):
    v = active_version(seeded)
    mc03 = next(r for r in v.rules if r.rule_code == "MC-03")
    deps = seeded.scalars(select(IntellectDependency).where(IntellectDependency.rule_id == mc03.id)).all()
    assert any(d.depends_on_code == "MC-04" and d.kind == "overrides" for d in deps)


def test_library_is_reference_only(seeded):
    docs = seeded.scalars(select(IntellectReferenceDocument)).all()
    assert {d.filename for d in docs} == {"LIBRARY.md", "HUMAN_SIGNALS.md"}
    assert all(d.executable is False for d in docs)
    pack = fw_svc.load_source_pack()
    assert pack["planned"]["name"] == "QPower"
    assert not any("QPower" in r["rule_id"] for r in pack["rules"])


# ---------------------------------------------------------------- protection (DB level)

def _protected(db):
    return next(r for r in active_version(db).rules if r.rule_code == "MC-14")


@pytest.mark.parametrize("field,value", [("is_active", False), ("text", "weakened"), ("priority", 4),
                                         ("is_protected", False), ("not_when", "always")])
def test_database_rejects_protected_rule_changes(seeded, field, value):
    rule = _protected(seeded)
    setattr(rule, field, value)
    with pytest.raises((IntegrityError, DatabaseError)):
        seeded.flush()
    seeded.rollback()


def test_database_rejects_deleting_protected_rule(seeded):
    seeded.delete(_protected(seeded))
    with pytest.raises((IntegrityError, DatabaseError)):
        seeded.flush()
    seeded.rollback()


def test_database_rejects_conditions_on_protected_rule(seeded):
    seeded.add(IntellectRuleCondition(rule_id=_protected(seeded).id, kind="not_when", text="never"))
    with pytest.raises((IntegrityError, DatabaseError)):
        seeded.flush()
    seeded.rollback()


def test_database_rejects_custom_protected_rule_and_tier1_layer(seeded):
    v = active_version(seeded)
    seeded.add(IntellectLayer(version_id=v.id, code="ZZ", name="x", tier=1, origin="custom"))
    with pytest.raises((IntegrityError, DatabaseError)):
        seeded.flush()
    seeded.rollback()


def test_reference_documents_cannot_be_executable(seeded):
    doc = seeded.scalars(select(IntellectReferenceDocument)).first()
    doc.executable = True
    with pytest.raises((IntegrityError, DatabaseError)):
        seeded.flush()
    seeded.rollback()


# ---------------------------------------------------------------- protection (service level)

def test_service_refuses_protected_and_source_changes(seeded):
    v = active_version(seeded)
    draft = fw_svc.create_draft(seeded, v, "v0.3B-draft1", None)
    by_code = {r.rule_code: r for r in draft.rules}
    with pytest.raises(fw_svc.ProtectedRuleError):
        fw_svc.update_rule(seeded, by_code["HM-20"], {"is_active": False}, None)
    with pytest.raises(fw_svc.ProtectedRuleError):
        fw_svc.update_rule(seeded, by_code["CB-01"], {"text": "rewritten"}, None)
    with pytest.raises(fw_svc.ProtectedRuleError):
        fw_svc.delete_rule(seeded, by_code["RL-03"], None)
    with pytest.raises(fw_svc.ProtectedRuleError):
        fw_svc.add_layer(seeded, draft, code="SR", name="Scientific Reasoning", question="?", description="",
                         tier=1, insert_after_position=6)


def test_layer_switch_never_removes_protected_rules(seeded):
    v = active_version(seeded)
    sw = fw_svc.resolve_switches(v, {"MC": False, "HM": False}, {"MC-17": False, "RL-03": False, "CB-01": False})
    assert "MC" in sw.layers_off
    assert "MC-17" not in sw.rules_off and "RL-03" not in sw.rules_off
    assert "CB-01" not in sw.rules_off  # source rules switch per layer only
    assert any("MC-14" in note for note in sw.ignored)


# ---------------------------------------------------------------- builder and versions

def test_custom_layer_and_rule_in_draft_then_publish_and_rollback(seeded):
    v = active_version(seeded)
    draft = fw_svc.create_draft(seeded, v, "v0.3B+SR", None)
    layer = fw_svc.add_layer(seeded, draft, code="SR", name="Scientific Reasoning",
                             question="Is the method sound?", description="", tier=2, insert_after_position=6)
    rule = fw_svc.add_rule(seeded, draft, layer, rule_code="SR-01", text="State the study design.",
                           applies_when="A study is cited.", not_when="No empirical claim.", priority=2)
    assert rule.is_active is False  # custom rules start inactive
    fw_svc.update_rule(seeded, rule, {"is_active": True}, None)
    seeded.flush()
    pipeline = [(s["layer"], s["mode"]) for s in draft.pipeline]
    assert pipeline[6] == ("SR", "main") and len(pipeline) == 14
    with pytest.raises(fw_svc.ProtectedRuleError):
        fw_svc.move_custom_stage(draft, 1, 3)  # CB is a source stage
    fw_svc.move_custom_stage(draft, 7, 8)       # the custom stage may move
    assert [(s["layer"], s["mode"]) for s in draft.pipeline][7] == ("SR", "main")
    report = fw_svc.submit_for_review(seeded, draft)
    assert report["ok"], report
    fw_svc.publish_version(seeded, draft, None)
    fw = seeded.get(IntellectFramework, v.framework_id)
    assert fw.active_version_id == draft.id and v.status == "archived"
    diff = fw_svc.diff_versions(v, draft)
    assert diff["rules_added"] == ["SR-01"] and diff["layers_added"] == ["SR"] and diff["pipeline_changed"]
    fw_svc.rollback(seeded, fw, v)
    assert fw.active_version_id == v.id and v.status == "published"


def test_published_versions_are_immutable(seeded):
    v = active_version(seeded)
    layer = v.layers[0]
    with pytest.raises(fw_svc.FrameworkStateError):
        fw_svc.add_rule(seeded, v, layer, rule_code="CB-99", text="x", applies_when="", not_when="", priority=2)


def test_publication_blocked_if_source_incomplete(seeded):
    """Simulates an extraction discrepancy: a draft missing a source rule cannot be published."""
    v = active_version(seeded)
    draft = fw_svc.create_draft(seeded, v, "broken", None)
    victim = next(r for r in draft.rules if r.rule_code == "FD-03")
    seeded.delete(victim)  # bypasses the service on purpose (drafts allow DB deletion of non-protected rows)
    seeded.flush()
    seeded.refresh(draft)
    report = fw_svc.submit_for_review(seeded, draft)
    assert not report["ok"]
    assert any("FD-03" in e for e in report["errors"]) and any("expected 93" in e for e in report["errors"])
    assert draft.status == "draft"


def test_draft_cannot_publish_without_review(seeded):
    draft = fw_svc.create_draft(seeded, active_version(seeded), "unreviewed", None)
    with pytest.raises(fw_svc.FrameworkStateError):
        fw_svc.publish_version(seeded, draft, None)
