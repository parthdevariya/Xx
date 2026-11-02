from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..intellect import frameworks as fw_svc
from ..intellect import lab
from ..intellect.importer import import_file
from ..models import (BackgroundJob, IntellectConflict, IntellectDependency, IntellectEvidence,
                      IntellectExecutionLog, IntellectExecutionPolicy, IntellectFramework, IntellectGuardrail,
                      IntellectImport, IntellectLayer, IntellectReferenceDocument, IntellectRule,
                      IntellectRuleHistory, IntellectRun, IntellectTestCase, IntellectVersion, User)
from ..services.audit import audit

router = APIRouter(prefix="/api/intellect", tags=["intellect"])


def _err(e: Exception):
    if isinstance(e, fw_svc.ProtectedRuleError):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, fw_svc.FrameworkStateError):
        return HTTPException(status_code=409, detail=str(e))
    return HTTPException(status_code=422, detail=str(e))


def _version(db, vid) -> IntellectVersion:
    v = db.get(IntellectVersion, vid)
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return v


def _framework(db, fid) -> IntellectFramework:
    f = db.get(IntellectFramework, fid)
    if f is None:
        raise HTTPException(status_code=404, detail="Framework not found.")
    return f


def rule_out(r: IntellectRule) -> dict:
    return {"id": r.id, "rule_code": r.rule_code, "layer": r.layer.code, "layer_name": r.layer.name,
            "text": r.text, "applies_when": r.applies_when, "not_when": r.not_when, "priority": r.priority,
            "provenance": r.provenance, "source_marker": r.source_marker, "is_protected": r.is_protected,
            "is_active": r.is_active, "origin": r.origin, "position": r.position, "source_page": r.source_page,
            "source_sha256": r.source_sha256, "revision": r.revision,
            "editable": (not r.is_protected) and r.origin != "source" and r.version.status == "draft"}


def layer_out(l: IntellectLayer, rules: list[IntellectRule]) -> dict:
    mine = [r for r in rules if r.layer_id == l.id]
    return {"id": l.id, "code": l.code, "name": l.name, "question": l.question, "description": l.description,
            "tier": l.tier, "tier_basis": l.tier_basis, "origin": l.origin, "enabled_by_default": l.enabled_by_default,
            "position": l.position, "declared_rule_count": l.declared_rule_count, "rule_count": len(mine),
            "protected_count": sum(1 for r in mine if r.is_protected), "source_page": l.source_page}


def version_summary(v: IntellectVersion) -> dict:
    return {"id": v.id, "label": v.label, "status": v.status, "parent_version_id": v.parent_version_id,
            "created_at": v.created_at, "published_at": v.published_at, "notes": v.notes,
            "counts": {"layers": len(v.layers), "rules": len(v.rules),
                       "protected": sum(1 for r in v.rules if r.is_protected)},
            "validation": v.validation}


# ---------------------------------------------------------------- frameworks

class FrameworkIn(BaseModel):
    name: str = Field(max_length=160)
    slug: str = Field(max_length=80)
    description: str = ""
    duplicate_from_version_id: str | None = None


@router.get("/frameworks")
def list_frameworks(db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    out = []
    for f in db.scalars(select(IntellectFramework).order_by(IntellectFramework.created_at)):
        active = db.get(IntellectVersion, f.active_version_id) if f.active_version_id else None
        out.append({"id": f.id, "slug": f.slug, "name": f.name, "description": f.description,
                    "source_pack": f.source_pack, "active_version": version_summary(active) if active else None,
                    "versions": [version_summary(v) for v in f.versions]})
    return out


@router.post("/frameworks")
def create_framework(body: FrameworkIn, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require("intellect.write"))):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", body.slug):
        raise HTTPException(status_code=422, detail="Slug must be lowercase letters, digits and hyphens.")
    if db.scalar(select(IntellectFramework).where(IntellectFramework.slug == body.slug)):
        raise HTTPException(status_code=409, detail="Slug already used.")
    fw = IntellectFramework(slug=body.slug, name=body.name, description=body.description)
    db.add(fw)
    db.flush()
    if body.duplicate_from_version_id:
        src = _version(db, body.duplicate_from_version_id)
        src_fw = db.get(IntellectFramework, src.framework_id)
        fw.source_pack = src_fw.source_pack  # keep source integrity checks on duplicates
        # Created under the source framework with a unique label, then moved to the new framework.
        draft = fw_svc.create_draft(db, src, f"dup-{fw.id[:12]}", user.id,
                                    notes=f"Duplicated from {src_fw.name} {src.label}")
        draft.framework_id = fw.id
        db.flush()
        draft.label = "v1-draft"
    else:
        db.add(IntellectVersion(framework_id=fw.id, label="v1-draft", status="draft", pipeline=[],
                                hierarchy=[{"rank": 1, "label": "hard limits and always-on guardrails", "layers": [],
                                            "raw": "hard limits and always-on guardrails"}],
                                created_by=user.id))
    db.add(IntellectExecutionPolicy(framework_id=fw.id, name="All layers on", is_default=True))
    audit(db, actor=user, category="framework", action="framework_created", target_type="intellect_framework",
          target_id=fw.id, detail=body.model_dump(), request=request)
    db.commit()
    return {"id": fw.id}


@router.post("/frameworks/{fid}/rollback")
def rollback(fid: str, body: dict, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require("intellect.publish"))):
    fw = _framework(db, fid)
    try:
        fw_svc.rollback(db, fw, _version(db, body.get("version_id")))
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
    audit(db, actor=user, category="framework", action="framework_rolled_back", target_type="intellect_framework",
          target_id=fid, detail=body, request=request)
    db.commit()
    return {"ok": True}


@router.get("/frameworks/{fid}/policies")
def policies(fid: str, db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    return [{"id": p.id, "name": p.name, "is_default": p.is_default, "layer_switches": p.layer_switches,
             "rule_switches": p.rule_switches}
            for p in db.scalars(select(IntellectExecutionPolicy).where(IntellectExecutionPolicy.framework_id == fid))]


# ---------------------------------------------------------------- versions

@router.get("/versions/{vid}")
def get_version(vid: str, db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    v = _version(db, vid)
    guardrails = db.scalars(select(IntellectGuardrail).where(IntellectGuardrail.version_id == vid)).all()
    evidence = db.scalars(select(IntellectEvidence).where(IntellectEvidence.version_id == vid)).all()
    fw = db.get(IntellectFramework, v.framework_id)
    return {**version_summary(v), "framework": {"id": fw.id, "name": fw.name, "slug": fw.slug,
                                                "source_pack": fw.source_pack,
                                                "is_active_version": fw.active_version_id == v.id},
            "pipeline": v.pipeline, "hierarchy": v.hierarchy, "hierarchy_note": v.hierarchy_note, "meta": v.meta,
            "layers": [layer_out(l, v.rules) for l in v.layers], "rules": [rule_out(r) for r in v.rules],
            "guardrails": [{"rule_code": g.rule_code, "kind": g.kind, "source_basis": g.source_basis}
                           for g in guardrails],
            "evidence_legend": [{"code": e.code, "meaning": e.meaning} for e in evidence]}


@router.get("/versions/{vid}/validate")
def validate(vid: str, db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    return fw_svc.validate_version(db, _version(db, vid))


class DraftIn(BaseModel):
    label: str = Field(max_length=64)
    notes: str = ""


@router.post("/versions/{vid}/drafts")
def create_draft(vid: str, body: DraftIn, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require("intellect.write"))):
    v = _version(db, vid)
    if any(x.label == body.label for x in db.get(IntellectFramework, v.framework_id).versions):
        raise HTTPException(status_code=409, detail="Label already used in this framework.")
    draft = fw_svc.create_draft(db, v, body.label, user.id, body.notes)
    audit(db, actor=user, category="framework", action="draft_created", target_type="intellect_version",
          target_id=draft.id, detail={"from": v.label, "label": body.label}, request=request)
    db.commit()
    return {"id": draft.id}


@router.post("/versions/{vid}/submit")
def submit(vid: str, request: Request, db: Session = Depends(get_db),
           user: User = Depends(require("intellect.write"))):
    v = _version(db, vid)
    try:
        report = fw_svc.submit_for_review(db, v)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
    audit(db, actor=user, category="framework", action="version_submitted", target_type="intellect_version",
          target_id=vid, outcome="success" if report["ok"] else "failed", detail={"errors": report["errors"]},
          request=request)
    db.commit()
    return report


@router.post("/versions/{vid}/publish")
def publish(vid: str, request: Request, db: Session = Depends(get_db),
            user: User = Depends(require("intellect.publish"))):
    v = _version(db, vid)
    try:
        report = fw_svc.publish_version(db, v, user.id)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
    audit(db, actor=user, category="framework", action="version_published", target_type="intellect_version",
          target_id=vid, outcome="success" if report["ok"] else "failed", detail={"errors": report["errors"]},
          request=request)
    db.commit()
    if not report["ok"]:
        raise HTTPException(status_code=409, detail={"message": "Publication blocked", **report})
    return report


@router.post("/versions/{vid}/reject")
def reject(vid: str, body: dict, request: Request, db: Session = Depends(get_db),
           user: User = Depends(require("intellect.publish"))):
    v = _version(db, vid)
    try:
        fw_svc.reject_version(db, v, str(body.get("reason", ""))[:1000])
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
    audit(db, actor=user, category="framework", action="version_rejected", target_type="intellect_version",
          target_id=vid, detail=body, request=request)
    db.commit()
    return {"ok": True}


@router.get("/versions/{a}/diff/{b}")
def diff(a: str, b: str, db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    return fw_svc.diff_versions(_version(db, a), _version(db, b))


# ---------------------------------------------------------------- layers, pipeline

class LayerIn(BaseModel):
    code: str = Field(max_length=4)
    name: str = Field(max_length=160)
    question: str = ""
    description: str = ""
    tier: int = Field(ge=2, le=6)
    insert_after_position: int | None = None
    mode: str = "main"


class LayerPatch(BaseModel):
    name: str | None = None
    question: str | None = None
    description: str | None = None
    tier: int | None = Field(None, ge=2, le=6)
    enabled_by_default: bool | None = None


@router.post("/versions/{vid}/layers")
def add_layer(vid: str, body: LayerIn, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require("intellect.write"))):
    v = _version(db, vid)
    try:
        layer = fw_svc.add_layer(db, v, **body.model_dump())
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
    audit(db, actor=user, category="framework", action="layer_added", target_type="intellect_layer",
          target_id=layer.id, detail=body.model_dump(), request=request)
    db.commit()
    return {"id": layer.id}


@router.patch("/layers/{lid}")
def update_layer(lid: str, body: LayerPatch, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require("intellect.write"))):
    layer = db.get(IntellectLayer, lid)
    if layer is None:
        raise HTTPException(status_code=404, detail="Layer not found.")
    v = layer.version
    if v.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft versions can be edited.")
    changes = body.model_dump(exclude_none=True)
    if layer.origin == "source" and set(changes) - {"enabled_by_default"}:
        raise HTTPException(status_code=403, detail="Source layers keep their name, question, description and "
                                                    "tier. Only their default switch can change.")
    for k, val in changes.items():
        setattr(layer, k, val)
    audit(db, actor=user, category="framework", action="layer_updated", target_type="intellect_layer",
          target_id=lid, detail=changes, request=request)
    db.commit()
    return {"ok": True}


@router.delete("/layers/{lid}")
def delete_layer(lid: str, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require("intellect.write"))):
    layer = db.get(IntellectLayer, lid)
    if layer is None:
        raise HTTPException(status_code=404, detail="Layer not found.")
    v = layer.version
    if layer.origin == "source":
        raise HTTPException(status_code=403, detail="Source layers cannot be deleted.")
    if v.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft versions can be edited.")
    if any(r.layer_id == lid and r.is_protected for r in v.rules):
        raise HTTPException(status_code=403, detail="Layer contains protected rules.")
    v.pipeline = fw_svc._renumber([s for s in v.pipeline if s["layer"] != layer.code])
    for r in [r for r in v.rules if r.layer_id == lid]:
        db.delete(r)
    db.delete(layer)
    audit(db, actor=user, category="framework", action="layer_deleted", target_type="intellect_layer",
          target_id=lid, detail={"code": layer.code}, request=request)
    db.commit()
    return {"ok": True}


@router.post("/versions/{vid}/pipeline/move")
def move_stage(vid: str, body: dict, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require("intellect.write"))):
    v = _version(db, vid)
    try:
        fw_svc.move_custom_stage(v, int(body["from_position"]), int(body["to_position"]))
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
    audit(db, actor=user, category="framework", action="pipeline_reordered", target_type="intellect_version",
          target_id=vid, detail=body, request=request)
    db.commit()
    return {"pipeline": v.pipeline}


# ---------------------------------------------------------------- rules

class RuleIn(BaseModel):
    layer_id: str
    rule_code: str = Field(max_length=16)
    text: str = Field(min_length=1, max_length=8000)
    applies_when: str = Field("", max_length=4000)
    not_when: str = Field("", max_length=4000)
    priority: int = Field(ge=1, le=4)
    provenance: str = Field("custom", max_length=16)


class RulePatch(BaseModel):
    text: str | None = Field(None, max_length=8000)
    applies_when: str | None = Field(None, max_length=4000)
    not_when: str | None = Field(None, max_length=4000)
    priority: int | None = Field(None, ge=1, le=4)
    provenance: str | None = Field(None, max_length=16)
    is_active: bool | None = None


@router.get("/versions/{vid}/rules")
def list_rules(vid: str, layer: str | None = None, q: str | None = None, protected: bool | None = None,
               db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    rules = _version(db, vid).rules
    if layer:
        rules = [r for r in rules if r.layer.code == layer]
    if q:
        ql = q.lower()
        rules = [r for r in rules if ql in r.text.lower() or ql in r.rule_code.lower()]
    if protected is not None:
        rules = [r for r in rules if r.is_protected == protected]
    return [rule_out(r) for r in rules]


@router.post("/versions/{vid}/rules")
def add_rule(vid: str, body: RuleIn, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require("intellect.write"))):
    v = _version(db, vid)
    layer = db.get(IntellectLayer, body.layer_id)
    if layer is None:
        raise HTTPException(status_code=404, detail="Layer not found.")
    try:
        r = fw_svc.add_rule(db, v, layer, rule_code=body.rule_code, text=body.text, applies_when=body.applies_when,
                            not_when=body.not_when, priority=body.priority, provenance=body.provenance,
                            user_id=user.id)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
    audit(db, actor=user, category="rule", action="rule_created", target_type="intellect_rule", target_id=r.id,
          detail=body.model_dump(), request=request)
    db.commit()
    return rule_out(r)


@router.patch("/rules/{rid}")
def update_rule(rid: str, body: RulePatch, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require("intellect.write"))):
    r = db.get(IntellectRule, rid)
    if r is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    changes = body.model_dump(exclude_none=True)
    try:
        fw_svc.update_rule(db, r, changes, user.id)
    except Exception as e:  # noqa: BLE001
        audit(db, actor=user, category="rule", action="rule_update_refused", target_type="intellect_rule",
              target_id=rid, outcome="denied", detail={"rule": r.rule_code, "reason": str(e), **changes},
              request=request)
        db.commit()
        raise _err(e) from e
    audit(db, actor=user, category="rule", action="rule_activation_changed" if set(changes) == {"is_active"}
          else "rule_updated", target_type="intellect_rule", target_id=rid,
          detail={"rule": r.rule_code, **changes}, request=request)
    db.commit()
    return rule_out(r)


@router.delete("/rules/{rid}")
def delete_rule(rid: str, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require("intellect.write"))):
    r = db.get(IntellectRule, rid)
    if r is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    code = r.rule_code
    try:
        fw_svc.delete_rule(db, r, user.id)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
    audit(db, actor=user, category="rule", action="rule_deleted", target_type="intellect_rule", target_id=rid,
          detail={"rule": code}, request=request)
    db.commit()
    return {"ok": True}


@router.get("/rules/{rid}")
def rule_detail(rid: str, db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    r = db.get(IntellectRule, rid)
    if r is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    deps = db.scalars(select(IntellectDependency).where(IntellectDependency.rule_id == rid)).all()
    hist = db.scalars(select(IntellectRuleHistory).where(IntellectRuleHistory.rule_code == r.rule_code,
                                                         IntellectRuleHistory.version_id == r.version_id)
                      .order_by(IntellectRuleHistory.at)).all()
    referenced_by = db.scalars(select(IntellectDependency).where(IntellectDependency.version_id == r.version_id,
                                                                 IntellectDependency.depends_on_code == r.rule_code))
    return {**rule_out(r), "source_block": r.source_block,
            "dependencies": [{"code": d.depends_on_code, "kind": d.kind, "origin": d.origin, "context": d.context}
                             for d in deps],
            "referenced_by": [{"rule_id": d.rule_id, "kind": d.kind, "context": d.context} for d in referenced_by],
            "history": [{"action": h.action, "at": h.at, "before": h.before, "after": h.after,
                         "changed_by": h.changed_by} for h in hist]}


# ---------------------------------------------------------------- runs and conflicts

def run_out(db, run: IntellectRun, full: bool = False) -> dict:
    v = db.get(IntellectVersion, run.version_id)
    out = {"id": run.id, "started_at": run.started_at, "finished_at": run.finished_at,
           "version": v.label if v else None, "version_id": run.version_id, "origin": run.origin,
           "status": run.status, "assessment_mode": run.assessment_mode, "prompt": run.prompt[:4000],
           "execution_id": run.execution_id, "layer_switches": run.layer_switches, "summary": run.summary,
           "error": run.error}
    if full:
        out["final_output"] = run.final_output
        out["stages"] = [{"position": l.position, "layer": l.layer, "mode": l.mode, "status": l.status,
                          "rule_states": l.rule_states, "output": l.output, "data": l.data, "model": l.model,
                          "latency_ms": l.latency_ms}
                         for l in db.scalars(select(IntellectExecutionLog).where(IntellectExecutionLog.run_id == run.id)
                                             .order_by(IntellectExecutionLog.position))]
        out["conflicts"] = [{"stage": c.stage_position, "rules": c.rule_codes, "layers": c.layers,
                             "description": c.description, "hierarchy_step": c.hierarchy_step, "winner": c.winner,
                             "decision": c.decision, "detected_by": c.detected_by}
                            for c in db.scalars(select(IntellectConflict).where(IntellectConflict.run_id == run.id))]
    return out


@router.get("/runs")
def list_runs(limit: int = 50, origin: str | None = None, db: Session = Depends(get_db),
              _: User = Depends(require("intellect.read"))):
    q = select(IntellectRun).order_by(IntellectRun.started_at.desc()).limit(min(limit, 200))
    if origin:
        q = q.where(IntellectRun.origin == origin)
    return [run_out(db, r) for r in db.scalars(q)]


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    run = db.get(IntellectRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run_out(db, run, full=True)


@router.get("/conflicts")
def list_conflicts(limit: int = 100, version_id: str | None = None, db: Session = Depends(get_db),
                   _: User = Depends(require("intellect.read"))):
    q = select(IntellectConflict).join(IntellectRun, IntellectConflict.run_id == IntellectRun.id)
    if version_id:
        q = q.where(IntellectRun.version_id == version_id)
    rows = db.scalars(q.order_by(IntellectRun.started_at.desc()).limit(min(limit, 500)))
    return [{"run_id": c.run_id, "stage": c.stage_position, "rules": c.rule_codes, "layers": c.layers,
             "description": c.description, "hierarchy_step": c.hierarchy_step, "winner": c.winner,
             "decision": c.decision, "detected_by": c.detected_by} for c in rows]


# ---------------------------------------------------------------- lab

class LabRunIn(BaseModel):
    version_id: str
    prompt: str = Field(min_length=1, max_length=20000)
    layer_switches: dict = {}
    test_case_id: str | None = None


@router.post("/lab/run")
def lab_run(body: LabRunIn, request: Request, db: Session = Depends(get_db),
            user: User = Depends(require("intellect.test"))):
    _version(db, body.version_id)
    job = BackgroundJob(kind="intellect_lab", payload={**body.model_dump(), "user_id": user.id}, max_attempts=1)
    db.add(job)
    audit(db, actor=user, category="framework", action="lab_run_requested", target_type="intellect_version",
          target_id=body.version_id, detail={"switches": body.layer_switches}, request=request)
    db.commit()
    return {"job_id": job.id}


@router.get("/lab/jobs/{job_id}")
def lab_job(job_id: str, db: Session = Depends(get_db), _: User = Depends(require("intellect.test"))):
    job = db.get(BackgroundJob, job_id)
    if job is None or job.kind not in ("intellect_lab", "intellect_regression"):
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"status": job.status, "error": job.error, "result": job.payload.get("result")}


@router.post("/lab/compare")
def lab_compare(body: dict, db: Session = Depends(get_db), _: User = Depends(require("intellect.test"))):
    a, b = db.get(IntellectRun, body.get("run_a")), db.get(IntellectRun, body.get("run_b"))
    if not a or not b:
        raise HTTPException(status_code=404, detail="Run not found.")
    return lab.compare_runs(db, a, b)


@router.post("/lab/evaluate")
def lab_evaluate(body: dict, db: Session = Depends(get_db), _: User = Depends(require("intellect.test"))):
    run = db.get(IntellectRun, body.get("run_id"))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return lab.evaluate(db, run, body.get("expected") or {})


class CaseIn(BaseModel):
    name: str = Field(max_length=200)
    prompt: str = Field(min_length=1, max_length=20000)
    layer_switches: dict = {}
    expected: dict = {}


@router.get("/frameworks/{fid}/test-cases")
def list_cases(fid: str, db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    return [{"id": c.id, "name": c.name, "prompt": c.prompt, "layer_switches": c.layer_switches,
             "expected": c.expected, "origin": c.origin, "last_outcome": c.last_outcome, "last_run_id": c.last_run_id}
            for c in db.scalars(select(IntellectTestCase).where(IntellectTestCase.framework_id == fid)
                                .order_by(IntellectTestCase.created_at))]


@router.post("/frameworks/{fid}/test-cases")
def add_case(fid: str, body: CaseIn, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require("intellect.test"))):
    _framework(db, fid)
    c = IntellectTestCase(framework_id=fid, created_by=user.id, **body.model_dump())
    db.add(c)
    audit(db, actor=user, category="framework", action="test_case_added", target_type="intellect_framework",
          target_id=fid, detail={"name": body.name}, request=request)
    db.commit()
    return {"id": c.id}


@router.put("/test-cases/{cid}")
def update_case(cid: str, body: CaseIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require("intellect.test"))):
    c = db.get(IntellectTestCase, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="Test case not found.")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    audit(db, actor=user, category="framework", action="test_case_updated", target_type="intellect_test_case",
          target_id=cid, detail={"name": body.name}, request=request)
    db.commit()
    return {"ok": True}


@router.delete("/test-cases/{cid}")
def delete_case(cid: str, db: Session = Depends(get_db), _: User = Depends(require("intellect.test"))):
    c = db.get(IntellectTestCase, cid)
    if c:
        db.delete(c)
        db.commit()
    return {"ok": True}


@router.post("/frameworks/{fid}/regression")
def regression(fid: str, body: dict, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require("intellect.test"))):
    _framework(db, fid)
    v = _version(db, body.get("version_id"))
    job = BackgroundJob(kind="intellect_regression",
                        payload={"framework_id": fid, "version_id": v.id, "user_id": user.id}, max_attempts=1)
    db.add(job)
    audit(db, actor=user, category="framework", action="regression_requested", target_type="intellect_version",
          target_id=v.id, request=request)
    db.commit()
    return {"job_id": job.id}


# ---------------------------------------------------------------- imports and library

@router.post("/frameworks/{fid}/imports")
async def upload_import(fid: str, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                        user: User = Depends(require("intellect.write"))):
    fw = _framework(db, fid)
    if fw.active_version_id is None:
        raise HTTPException(status_code=409, detail="Framework has no published version to extend.")
    raw = await file.read(10 * 1024 * 1024 + 1)
    rec = import_file(db, framework=fw, filename=file.filename or "upload", raw=raw, user_id=user.id)
    audit(db, actor=user, category="framework", action="framework_imported", target_type="intellect_import",
          target_id=rec.id, outcome="success" if rec.status == "draft" else "failed",
          detail={"filename": file.filename, "status": rec.status, "sha256": rec.file_sha256}, request=request)
    db.commit()
    return {"id": rec.id, "status": rec.status, "report": rec.report, "draft_version_id": rec.draft_version_id}


@router.get("/imports")
def list_imports(db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    return [{"id": i.id, "filename": i.filename, "format": i.file_format, "status": i.status, "report": i.report,
             "draft_version_id": i.draft_version_id, "created_at": i.created_at}
            for i in db.scalars(select(IntellectImport).order_by(IntellectImport.created_at.desc()))]


@router.get("/frameworks/{fid}/library")
def library(fid: str, db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    return [{"id": d.id, "filename": d.filename, "description": d.description, "use_for": d.use_for,
             "has_content": bool(d.content), "executable": d.executable}
            for d in db.scalars(select(IntellectReferenceDocument)
                                .where(IntellectReferenceDocument.framework_id == fid))]


@router.put("/library/{doc_id}")
async def upload_library_doc(doc_id: str, request: Request, file: UploadFile = File(...),
                             db: Session = Depends(get_db), user: User = Depends(require("intellect.write"))):
    d = db.get(IntellectReferenceDocument, doc_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Reference document not found.")
    raw = await file.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024 or not (file.filename or "").lower().endswith((".md", ".txt")):
        raise HTTPException(status_code=422, detail="Reference documents must be .md or .txt under 2 MB.")
    try:
        d.content = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=422, detail="File must be UTF-8 text.") from e
    audit(db, actor=user, category="framework", action="reference_document_uploaded",
          target_type="intellect_reference_document", target_id=doc_id, request=request)
    db.commit()
    return {"ok": True, "executable": False}


@router.get("/library/{doc_id}")
def read_library_doc(doc_id: str, db: Session = Depends(get_db), _: User = Depends(require("intellect.read"))):
    d = db.get(IntellectReferenceDocument, doc_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Reference document not found.")
    return {"filename": d.filename, "content": d.content, "executable": d.executable}
