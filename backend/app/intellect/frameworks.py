"""Framework, version, layer and rule management — the service layer of the Framework Builder.

Every mutating function enforces protection itself (the database enforces it again).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (IntellectDependency, IntellectEvidence, IntellectExecutionPolicy, IntellectFramework,
                      IntellectGuardrail, IntellectLayer, IntellectReferenceDocument, IntellectRule,
                      IntellectRuleHistory, IntellectVersion, utcnow)

SOURCE_DIR = Path(__file__).parent / "source"
SOURCE_PACK_ID = "x_layers_v0_3B"
SOURCE_FRAMEWORK_SLUG = "x-layers"
RULE_ID_RE = re.compile(r"\b([A-Z]{2,4}-\d{2})\b")
RULE_FIELDS = ("rule_code", "text", "applies_when", "not_when", "priority", "provenance", "source_marker",
               "is_protected", "is_active", "origin", "position")


class ProtectedRuleError(PermissionError):
    """Raised when an operation would modify, disable or outrank a protected rule."""


class FrameworkStateError(ValueError):
    """Raised when an operation is not allowed in the version's current state."""


@lru_cache
def load_source_pack(pack_id: str = SOURCE_PACK_ID) -> dict:
    return json.loads((SOURCE_DIR / f"{pack_id}.json").read_text(encoding="utf-8"))


def _legend_codes(legend: str) -> list[tuple[str, str]]:
    out = []
    for part in [p.strip() for p in legend.split("·") if p.strip()]:
        m = re.match(r"^((?:\+?[A-Z]\d?(?:\s*/\s*[A-Z]\d)?)|P1–P4)\s+(.*)$", part)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def _extract_dependencies(rule: IntellectRule) -> list[IntellectDependency]:
    deps: dict[tuple[str, str], IntellectDependency] = {}
    for field_name in ("text", "applies_when", "not_when"):
        body = getattr(rule, field_name) or ""
        for sentence in re.split(r"(?<=[.;])\s+", body):
            for code in RULE_ID_RE.findall(sentence):
                if code == rule.rule_code:
                    continue
                kind = "references"
                if re.search(rf"{re.escape(code)}\s+overrides", sentence):
                    kind = "overrides"
                elif field_name == "not_when":
                    kind = "defers_to"
                key = (code, kind)
                if key not in deps:
                    deps[key] = IntellectDependency(version_id=rule.version_id, rule_id=rule.id,
                                                    depends_on_code=code, kind=kind, origin="extracted",
                                                    context=f"[{field_name}] {sentence.strip()}")
    return list(deps.values())


# ---------------------------------------------------------------------------
# seeding
# ---------------------------------------------------------------------------

def seed_source_framework(db: Session, user_id: str | None = None) -> IntellectFramework:
    """Create the X Layers framework and publish v0.3B from the checked-in source pack. Idempotent."""
    existing = db.scalar(select(IntellectFramework).where(IntellectFramework.slug == SOURCE_FRAMEWORK_SLUG))
    if existing:
        return existing
    pack = load_source_pack()
    fw = IntellectFramework(slug=SOURCE_FRAMEWORK_SLUG, name=pack["framework_name"],
                            description=pack["subtitle"], source_pack=SOURCE_PACK_ID)
    db.add(fw)
    db.flush()
    version = IntellectVersion(
        framework_id=fw.id, label=pack["version"], status="draft",
        pipeline=pack["stages"], hierarchy=pack["hierarchy"], hierarchy_note=pack["hierarchy_note"],
        meta={k: pack[k] for k in ("title", "subtitle", "preamble", "sequence_text", "legend",
                                   "hard_limit_note", "footer_note", "planned", "source_file",
                                   "source_sha256", "transformations", "always_on", "hard_limits",
                                   "declared_total")},
        notes="Imported from the authoritative source document.", created_by=user_id,
    )
    db.add(version)
    db.flush()
    layer_by_code: dict[str, IntellectLayer] = {}
    for pos, L in enumerate(pack["layers"], start=1):
        layer = IntellectLayer(version_id=version.id, code=L["code"], name=L["name"], question=L["question"],
                               description=L["description"], tier=L["tier"], tier_basis=L["tier_basis"],
                               origin="source", position=pos, declared_rule_count=L["declared_rule_count"],
                               source_page=L["page"])
        db.add(layer)
        layer_by_code[L["code"]] = layer
    db.flush()
    always_on, hard = set(pack["always_on"]), set(pack["hard_limits"])
    global_pos = 0
    rules: list[IntellectRule] = []
    for R in pack["rules"]:
        global_pos += 1
        rule = IntellectRule(
            version_id=version.id, layer_id=layer_by_code[R["layer"]].id, rule_code=R["rule_id"],
            number=R["number"], text=R["text"], applies_when=R["applies_when"], not_when=R["not_when"],
            priority=R["priority"], provenance=R["provenance"], source_marker=R["source_marker"],
            is_protected=R["rule_id"] in always_on, is_active=True, origin="source", position=global_pos,
            source_page=R["page"], source_sha256=R["sha256"], source_block=R["source_block"],
        )
        db.add(rule)
        rules.append(rule)
    db.flush()
    for rule in rules:
        if rule.is_protected:
            db.add(IntellectGuardrail(
                version_id=version.id, rule_id=rule.id, rule_code=rule.rule_code,
                kind="hard_limit" if rule.rule_code in hard else "always_on",
                source_basis=("Listed under 'Always on: no switch, setting or customer can turn these off'"
                              + ("; Moral Compass Hard Limit, never weighed against anything"
                                 if rule.rule_code in hard else ""))))
        for dep in _extract_dependencies(rule):
            db.add(dep)
    for code, meaning in _legend_codes(pack["legend"]):
        db.add(IntellectEvidence(version_id=version.id, code=code, meaning=meaning))
    for entry in pack["library"].get("entries", []):
        db.add(IntellectReferenceDocument(
            framework_id=fw.id, filename=entry["file"], description=entry["row"],
            use_for=pack["library"].get("when_to_use", ""), executable=False))
    db.add(IntellectExecutionPolicy(framework_id=fw.id, name="All layers on", is_default=True,
                                    layer_switches={}, rule_switches={}))
    db.flush()
    report = validate_version(db, version)
    if not report["ok"]:
        raise FrameworkStateError("source framework failed validation: " + "; ".join(report["errors"]))
    version.validation = report
    version.status = "published"
    version.published_at = utcnow()
    version.published_by = user_id
    fw.active_version_id = version.id
    db.flush()
    return fw


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def validate_version(db: Session, version: IntellectVersion) -> dict:
    """Publication gate. For source-derived frameworks, the full source must be intact."""
    errors: list[str] = []
    warnings: list[str] = []
    db.refresh(version)
    fw = db.get(IntellectFramework, version.framework_id)
    layer_codes = {l.code for l in version.layers}
    rules_by_code = {r.rule_code: r for r in version.rules}

    stage_layers = [s["layer"] for s in version.pipeline]
    for code in stage_layers:
        if code not in layer_codes:
            errors.append(f"pipeline references layer {code} which does not exist in this version")
    for layer in version.layers:
        if layer.code not in stage_layers:
            errors.append(f"layer {layer.code} has no stage in the execution pipeline")
    positions = [s["position"] for s in version.pipeline]
    if positions != list(range(1, len(positions) + 1)):
        errors.append("pipeline positions must be consecutive from 1")

    if fw is not None and fw.source_pack:
        pack = load_source_pack(fw.source_pack)
        src_layers = {L["code"] for L in pack["layers"]}
        missing_layers = src_layers - layer_codes
        if missing_layers:
            errors.append(f"source layers missing: {sorted(missing_layers)}")
        n_source_rules = sum(1 for r in version.rules if r.origin == "source")
        if n_source_rules != len(pack["rules"]):
            errors.append(f"expected {len(pack['rules'])} source rules, found {n_source_rules}")
        for R in pack["rules"]:
            r = rules_by_code.get(R["rule_id"])
            if r is None:
                errors.append(f"source rule {R['rule_id']} missing")
                continue
            if r.origin != "source":
                errors.append(f"{R['rule_id']} is no longer marked as a source rule")
            if (r.text, r.applies_when, r.not_when, r.priority, r.provenance, r.source_marker) != (
                    R["text"], R["applies_when"], R["not_when"], R["priority"], R["provenance"], R["source_marker"]):
                errors.append(f"{R['rule_id']} differs from the source text, conditions or priority")
        for rid in pack["always_on"]:
            r = rules_by_code.get(rid)
            if r is None or not r.is_protected or not r.is_active:
                errors.append(f"guardrail {rid} must be present, protected and active")
        src_seq = [(s["layer"], s["mode"]) for s in pack["stages"]]
        cur_seq = [(s["layer"], s["mode"]) for s in version.pipeline if s.get("origin", "source") == "source"]
        if cur_seq != src_seq:
            errors.append("source execution sequence altered: expected "
                          + " → ".join(f"{l}({m})" for l, m in src_seq))
        custom_stages = [s for s in version.pipeline if s.get("origin", "source") != "source"]
        if custom_stages:
            warnings.append(f"{len(custom_stages)} custom stage(s) added to the source sequence")

    for r in version.rules:
        if r.is_protected and not r.is_active:
            errors.append(f"{r.rule_code} is protected but inactive")
        if r.origin != "source" and r.is_protected:
            errors.append(f"{r.rule_code}: custom rules cannot be protected")
    imported_active = [r.rule_code for r in version.rules if r.origin == "imported" and r.is_active]
    if imported_active and version.status not in ("in_review", "draft"):
        warnings.append(f"imported rules active: {imported_active}")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "counts": {"layers": len(version.layers), "rules": len(version.rules),
                       "protected": sum(1 for r in version.rules if r.is_protected),
                       "source_rules": sum(1 for r in version.rules if r.origin == "source")},
            "checked_at": utcnow().isoformat()}


# ---------------------------------------------------------------------------
# versions
# ---------------------------------------------------------------------------

def create_draft(db: Session, version: IntellectVersion, label: str, user_id: str | None,
                 notes: str = "") -> IntellectVersion:
    draft = IntellectVersion(framework_id=version.framework_id, label=label, status="draft",
                             parent_version_id=version.id,
                             pipeline=[dict(s) for s in version.pipeline],
                             hierarchy=[dict(h) for h in version.hierarchy],
                             hierarchy_note=version.hierarchy_note, meta=dict(version.meta),
                             notes=notes, created_by=user_id)
    db.add(draft)
    db.flush()
    layer_map: dict[str, str] = {}
    for L in version.layers:
        nl = IntellectLayer(version_id=draft.id, code=L.code, name=L.name, question=L.question,
                            description=L.description, tier=L.tier, tier_basis=L.tier_basis, origin=L.origin,
                            enabled_by_default=L.enabled_by_default, position=L.position,
                            declared_rule_count=L.declared_rule_count, source_page=L.source_page)
        db.add(nl)
        db.flush()
        layer_map[L.id] = nl.id
    new_rules = []
    for R in version.rules:
        nr = IntellectRule(version_id=draft.id, layer_id=layer_map[R.layer_id], rule_code=R.rule_code,
                           number=R.number, text=R.text, applies_when=R.applies_when, not_when=R.not_when,
                           priority=R.priority, provenance=R.provenance, source_marker=R.source_marker,
                           is_protected=R.is_protected, is_active=R.is_active, origin=R.origin,
                           position=R.position, source_page=R.source_page, source_sha256=R.source_sha256,
                           source_block=R.source_block, revision=R.revision)
        db.add(nr)
        new_rules.append(nr)
    db.flush()
    for nr in new_rules:
        if nr.is_protected:
            src = db.scalar(select(IntellectGuardrail).where(IntellectGuardrail.version_id == version.id,
                                                             IntellectGuardrail.rule_code == nr.rule_code))
            db.add(IntellectGuardrail(version_id=draft.id, rule_id=nr.id, rule_code=nr.rule_code,
                                      kind=src.kind if src else "always_on",
                                      source_basis=src.source_basis if src else ""))
        for dep in _extract_dependencies(nr):
            db.add(dep)
    for ev in db.scalars(select(IntellectEvidence).where(IntellectEvidence.version_id == version.id)):
        db.add(IntellectEvidence(version_id=draft.id, code=ev.code, meaning=ev.meaning))
    db.flush()
    return draft


def _require_draft(version: IntellectVersion) -> None:
    if version.status not in ("draft",):
        raise FrameworkStateError(f"version {version.label} is {version.status}; create a draft to make changes")


def submit_for_review(db: Session, version: IntellectVersion) -> dict:
    _require_draft(version)
    report = validate_version(db, version)
    version.validation = report
    if report["ok"]:
        version.status = "in_review"
        version.submitted_at = utcnow()
    return report


def publish_version(db: Session, version: IntellectVersion, user_id: str | None) -> dict:
    """Publish a reviewed version. Imported rules stay inactive unless an admin activated them in review."""
    if version.status not in ("in_review",):
        raise FrameworkStateError("only versions in review can be published (submit the draft first)")
    report = validate_version(db, version)
    version.validation = report
    if not report["ok"]:
        return report
    fw = db.get(IntellectFramework, version.framework_id)
    if fw.active_version_id:
        prev = db.get(IntellectVersion, fw.active_version_id)
        if prev and prev.id != version.id:
            prev.status = "archived"
    version.status = "published"
    version.published_at = utcnow()
    version.published_by = user_id
    fw.active_version_id = version.id
    db.flush()
    return report


def reject_version(db: Session, version: IntellectVersion, reason: str) -> None:
    if version.status not in ("in_review", "draft"):
        raise FrameworkStateError("only drafts or versions in review can be rejected")
    version.status = "rejected"
    version.notes = (version.notes + "\nRejected: " + reason).strip()


def rollback(db: Session, fw: IntellectFramework, target: IntellectVersion) -> None:
    if target.framework_id != fw.id or target.status not in ("published", "archived"):
        raise FrameworkStateError("rollback target must be a previously published version of this framework")
    report = validate_version(db, target)
    if not report["ok"]:
        raise FrameworkStateError("rollback target no longer validates: " + "; ".join(report["errors"]))
    if fw.active_version_id and fw.active_version_id != target.id:
        cur = db.get(IntellectVersion, fw.active_version_id)
        if cur:
            cur.status = "archived"
    target.status = "published"
    fw.active_version_id = target.id
    db.flush()


def diff_versions(a: IntellectVersion, b: IntellectVersion) -> dict:
    def rule_map(v):
        return {r.rule_code: r for r in v.rules}

    ra, rb = rule_map(a), rule_map(b)
    added = sorted(set(rb) - set(ra))
    removed = sorted(set(ra) - set(rb))
    changed = []
    for code in sorted(set(ra) & set(rb)):
        fields = [f for f in ("text", "applies_when", "not_when", "priority", "provenance", "is_active",
                              "is_protected", "source_marker")
                  if getattr(ra[code], f) != getattr(rb[code], f)]
        if ra[code].layer.code != rb[code].layer.code:
            fields.append("layer")
        if fields:
            changed.append({"rule": code, "fields": fields,
                            "before": {f: getattr(ra[code], f) for f in fields if f != "layer"},
                            "after": {f: getattr(rb[code], f) for f in fields if f != "layer"}})
    la, lb = {l.code: l for l in a.layers}, {l.code: l for l in b.layers}
    return {
        "from": a.label, "to": b.label,
        "rules_added": added, "rules_removed": removed, "rules_changed": changed,
        "layers_added": sorted(set(lb) - set(la)), "layers_removed": sorted(set(la) - set(lb)),
        "layers_changed": [c for c in sorted(set(la) & set(lb))
                           if (la[c].name, la[c].tier, la[c].question) != (lb[c].name, lb[c].tier, lb[c].question)],
        "pipeline_changed": [(s["layer"], s["mode"]) for s in a.pipeline] != [(s["layer"], s["mode"]) for s in b.pipeline],
    }


# ---------------------------------------------------------------------------
# layers and rules (drafts only)
# ---------------------------------------------------------------------------

def _snapshot(rule: IntellectRule) -> dict:
    return {f: getattr(rule, f) for f in RULE_FIELDS}


def add_layer(db: Session, version: IntellectVersion, *, code: str, name: str, question: str,
              description: str, tier: int, insert_after_position: int | None, mode: str = "main") -> IntellectLayer:
    _require_draft(version)
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z]{2,4}", code):
        raise ValueError("layer code must be 2-4 capital letters")
    if any(l.code == code for l in version.layers):
        raise ValueError(f"layer {code} already exists")
    if not 2 <= tier <= 6:
        raise ProtectedRuleError("custom layers must sit in conflict tiers 2-6; tier 1 is reserved for guardrails")
    layer = IntellectLayer(version_id=version.id, code=code, name=name, question=question,
                           description=description, tier=tier, origin="custom",
                           tier_basis="assigned by administrator",
                           position=max([l.position for l in version.layers] or [0]) + 1)
    db.add(layer)
    pipeline = [dict(s) for s in version.pipeline]
    at = len(pipeline) if insert_after_position is None else insert_after_position
    pipeline.insert(at, {"position": 0, "layer": code, "mode": mode, "source_label": f"{code} (custom)",
                         "bound_to": None, "origin": "custom"})
    version.pipeline = _renumber(pipeline)
    db.flush()
    return layer


def _renumber(pipeline: list[dict]) -> list[dict]:
    old_to_new = {}
    for i, s in enumerate(pipeline, start=1):
        old_to_new[s["position"]] = i
    out = []
    for i, s in enumerate(pipeline, start=1):
        s = dict(s)
        if s.get("bound_to"):
            s["bound_to"] = old_to_new.get(s["bound_to"], s["bound_to"])
        s["position"] = i
        out.append(s)
    return out


def move_custom_stage(version: IntellectVersion, from_position: int, to_position: int) -> None:
    _require_draft(version)
    pipeline = [dict(s) for s in version.pipeline]
    stage = next((s for s in pipeline if s["position"] == from_position), None)
    if stage is None:
        raise ValueError("no stage at that position")
    if stage.get("origin", "source") == "source":
        raise ProtectedRuleError("source stages keep the source-defined order; only custom stages can move")
    pipeline.remove(stage)
    pipeline.insert(to_position - 1, stage)
    version.pipeline = _renumber(pipeline)


def add_rule(db: Session, version: IntellectVersion, layer: IntellectLayer, *, rule_code: str, text: str,
             applies_when: str, not_when: str, priority: int, provenance: str = "custom",
             is_active: bool = False, user_id: str | None = None, origin: str = "custom") -> IntellectRule:
    _require_draft(version)
    if layer.version_id != version.id:
        raise ValueError("layer belongs to a different version")
    rule_code = rule_code.strip().upper()
    if not RULE_ID_RE.fullmatch(rule_code):
        raise ValueError("rule code must look like ABC-01")
    if any(r.rule_code == rule_code for r in version.rules):
        raise ValueError(f"rule {rule_code} already exists in this version")
    if not 1 <= priority <= 4:
        raise ValueError("priority must be P1-P4")
    rule = IntellectRule(version_id=version.id, layer_id=layer.id, rule_code=rule_code,
                         number=int(rule_code.split("-")[1]), text=text.strip(), applies_when=applies_when.strip(),
                         not_when=not_when.strip(), priority=priority, provenance=provenance, is_protected=False,
                         is_active=is_active, origin=origin,
                         position=max([r.position for r in version.rules] or [0]) + 1)
    db.add(rule)
    db.flush()
    for dep in _extract_dependencies(rule):
        db.add(dep)
    db.add(IntellectRuleHistory(rule_id=rule.id, version_id=version.id, rule_code=rule.rule_code,
                                action="created", after=_snapshot(rule), changed_by=user_id))
    return rule


EDITABLE_FIELDS = {"text", "applies_when", "not_when", "priority", "provenance", "is_active"}


def update_rule(db: Session, rule: IntellectRule, changes: dict, user_id: str | None) -> IntellectRule:
    version = db.get(IntellectVersion, rule.version_id)
    if rule.is_protected:
        raise ProtectedRuleError(f"{rule.rule_code} is a protected guardrail and cannot be changed or disabled")
    if rule.origin == "source":
        raise ProtectedRuleError(
            f"{rule.rule_code} is an original source rule; its wording, conditions, priority and status are "
            "preserved. The source framework is switched per layer only. Changes to source rules require a new "
            "source document import.")
    _require_draft(version)
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"fields not editable: {sorted(unknown)}")
    if "priority" in changes and not 1 <= int(changes["priority"]) <= 4:
        raise ValueError("priority must be P1-P4")
    before = _snapshot(rule)
    for k, v in changes.items():
        setattr(rule, k, v)
    rule.revision += 1
    action = "updated"
    if set(changes) == {"is_active"}:
        action = "activated" if changes["is_active"] else "deactivated"
    db.add(IntellectRuleHistory(rule_id=rule.id, version_id=version.id, rule_code=rule.rule_code,
                                action=action, before=before, after=_snapshot(rule), changed_by=user_id))
    db.flush()
    return rule


def delete_rule(db: Session, rule: IntellectRule, user_id: str | None) -> None:
    version = db.get(IntellectVersion, rule.version_id)
    if rule.is_protected:
        raise ProtectedRuleError(f"{rule.rule_code} is a protected guardrail and cannot be deleted")
    if rule.origin == "source":
        raise ProtectedRuleError(f"{rule.rule_code} is an original source rule and cannot be deleted")
    _require_draft(version)
    db.add(IntellectRuleHistory(rule_id=None, version_id=version.id, rule_code=rule.rule_code,
                                action="deleted", before=_snapshot(rule), changed_by=user_id))
    db.delete(rule)
    db.flush()


@dataclass
class EffectiveSwitches:
    layers_off: set[str]
    rules_off: set[str]
    ignored: list[str]


def resolve_switches(version: IntellectVersion, layer_switches: dict | None,
                     rule_switches: dict | None) -> EffectiveSwitches:
    """Apply user/admin switches, honouring protection. Returns what was ignored and why."""
    layer_switches = layer_switches or {}
    rule_switches = rule_switches or {}
    layers_off = {code for code, on in layer_switches.items() if on is False}
    for l in version.layers:
        if not l.enabled_by_default and layer_switches.get(l.code) is not True:
            layers_off.add(l.code)
    rules_off: set[str] = set()
    ignored: list[str] = []
    by_code = {r.rule_code: r for r in version.rules}
    for code, on in rule_switches.items():
        if on is False:
            r = by_code.get(code)
            if r is None:
                ignored.append(f"{code}: no such rule in {version.label}")
            elif r.is_protected:
                ignored.append(f"{code}: protected guardrail, switch ignored")
            elif r.origin == "source":
                ignored.append(f"{code}: source rules are switched per layer only, switch ignored")
            else:
                rules_off.add(code)
    for code in layers_off:
        kept = sorted(r.rule_code for r in version.rules if r.is_protected and r.layer.code == code)
        if kept:
            ignored.append(f"layer {code} off: protected rules {', '.join(kept)} remain active")
    return EffectiveSwitches(layers_off, rules_off, ignored)
