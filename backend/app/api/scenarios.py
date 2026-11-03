from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qos.formulations.library import TEMPLATES

from ..db import get_db
from ..deps import current_user, require
from ..models import (EXECUTION_MODES, Scenario, ScenarioCategory, ScenarioExecutionPolicy, ScenarioInputSchema,
                      ScenarioVersion, User)
from ..services.audit import audit

router = APIRouter(prefix="/api", tags=["scenarios"])
FIELD_TYPES = {"number", "text", "textarea", "matrix", "list_number", "list_text", "json"}


def scenario_out(db: Session, s: Scenario, full: bool = True) -> dict:
    v = s.current_version
    schema = db.scalar(select(ScenarioInputSchema).where(ScenarioInputSchema.version_id == v.id)) if v else None
    pol = db.scalar(select(ScenarioExecutionPolicy).where(ScenarioExecutionPolicy.scenario_id == s.id))
    out = {"id": s.id, "slug": s.slug, "status": s.status, "is_demo": s.is_demo,
           "category": {"slug": s.category.slug, "name": s.category.name, "notice": s.category.notice},
           "version_no": v.version_no if v else None, "name": v.name if v else s.slug,
           "tagline": v.tagline if v else "", "engines": v.engines if v else [],
           "solver_template": v.solver_template if v else "",
           "quantum_eligibility": v.quantum_eligibility if v else "never",
           "modes": pol.allowed_modes if pol else list(EXECUTION_MODES),
           "default_mode": pol.default_mode if pol else "hybrid",
           "expected_output": v.expected_output if v else ""}
    if full and v:
        out.update({"description": v.description, "problem_statement": v.problem_statement, "context": v.context,
                    "demonstrates": v.demonstrates, "output_structure": v.output_structure,
                    "recommended_models": v.recommended_models,
                    "recommended_framework_slug": v.recommended_framework_slug,
                    "classical_config": v.classical_config, "benchmark_config": v.benchmark_config,
                    "visualizations": v.visualizations, "notes": v.notes,
                    "fields": schema.fields if schema else [], "defaults": schema.defaults if schema else {},
                    "policy": {"allowed_modes": pol.allowed_modes, "default_mode": pol.default_mode,
                               "max_cost_usd": pol.max_cost_usd, "allow_quantum_hardware": pol.allow_quantum_hardware,
                               "demo_enabled": pol.demo_enabled} if pol else None})
    return out


@router.get("/scenario-categories")
def categories(db: Session = Depends(get_db), _: User = Depends(require("scenarios.read"))):
    return [{"slug": c.slug, "name": c.name, "description": c.description, "notice": c.notice}
            for c in db.scalars(select(ScenarioCategory).order_by(ScenarioCategory.position))]


@router.get("/scenarios")
def list_scenarios(all: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if "scenarios.read" not in user.permission_codes:
        raise HTTPException(status_code=403, detail="Missing permission: scenarios.read")
    q = select(Scenario).order_by(Scenario.position)
    if not (all and "scenarios.write" in user.permission_codes):
        q = q.where(Scenario.status == "published")
    return [scenario_out(db, s) for s in db.scalars(q)]


@router.get("/scenarios/{slug}")
def get_scenario(slug: str, db: Session = Depends(get_db), user: User = Depends(require("scenarios.read"))):
    s = db.scalar(select(Scenario).where(Scenario.slug == slug))
    if s is None or (s.status != "published" and "scenarios.write" not in user.permission_codes):
        raise HTTPException(status_code=404, detail="Scenario not found.")
    return scenario_out(db, s)


class ScenarioIn(BaseModel):
    slug: str = Field(max_length=120)
    category: str
    name: str = Field(max_length=200)
    tagline: str = Field("", max_length=300)
    description: str = ""
    problem_statement: str = ""
    context: str = ""
    demonstrates: str = ""
    solver_template: str = ""
    quantum_eligibility: str = "evaluate"
    engines: list[str] = []
    expected_output: str = ""
    visualizations: list[str] = []
    output_structure: dict = {}
    recommended_models: list[str] = []
    classical_config: dict = {}
    benchmark_config: dict = {}
    notes: str = ""
    fields: list[dict] = []
    defaults: dict = {}
    is_demo: bool = False


class PolicyIn(BaseModel):
    allowed_modes: list[str]
    default_mode: str
    max_cost_usd: float = Field(0.0, ge=0)
    allow_quantum_hardware: bool = False
    demo_enabled: bool = True


def _validate(body: ScenarioIn) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,119}", body.slug):
        raise HTTPException(status_code=422, detail="Slug must be lowercase letters, digits and hyphens.")
    if body.solver_template and body.solver_template not in TEMPLATES:
        raise HTTPException(status_code=422, detail=f"Unknown solver template; known: {sorted(TEMPLATES)}")
    if body.quantum_eligibility not in ("evaluate", "never", "simulation_only"):
        raise HTTPException(status_code=422, detail="quantum_eligibility must be evaluate, never or simulation_only")
    keys = set()
    for f in body.fields:
        if not f.get("key") or f.get("type") not in FIELD_TYPES:
            raise HTTPException(status_code=422, detail=f"Each field needs a key and a type in {sorted(FIELD_TYPES)}")
        if f["key"] in keys:
            raise HTTPException(status_code=422, detail=f"Duplicate field key {f['key']}")
        keys.add(f["key"])


def _new_version(db: Session, s: Scenario, body: ScenarioIn) -> ScenarioVersion:
    n = (db.scalar(select(func.max(ScenarioVersion.version_no)).where(ScenarioVersion.scenario_id == s.id)) or 0) + 1
    data = body.model_dump(exclude={"slug", "category", "fields", "defaults", "is_demo"})
    v = ScenarioVersion(scenario_id=s.id, version_no=n, **data)
    db.add(v)
    db.flush()
    db.add(ScenarioInputSchema(version_id=v.id, fields=body.fields, defaults=body.defaults))
    s.current_version_id = v.id
    return v


@router.post("/scenarios")
def create_scenario(body: ScenarioIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("scenarios.write"))):
    _validate(body)
    cat = db.scalar(select(ScenarioCategory).where(ScenarioCategory.slug == body.category))
    if cat is None:
        raise HTTPException(status_code=422, detail="Unknown category.")
    if db.scalar(select(Scenario).where(Scenario.slug == body.slug)):
        raise HTTPException(status_code=409, detail="Slug already used.")
    s = Scenario(slug=body.slug, category_id=cat.id, status="draft", is_demo=body.is_demo,
                 position=(db.scalar(select(func.max(Scenario.position))) or 0) + 1)
    db.add(s)
    db.flush()
    _new_version(db, s, body)
    modes = list(EXECUTION_MODES) if body.solver_template else ["ai_only", "ai_intellect", "intellect_vs_ai",
                                                                  "benchmark"]
    db.add(ScenarioExecutionPolicy(scenario_id=s.id, allowed_modes=modes, default_mode=modes[-1]
                                   if "hybrid" not in modes else "hybrid"))
    audit(db, actor=user, category="scenario", action="scenario_created", target_type="scenario", target_id=s.id,
          detail={"slug": body.slug}, request=request)
    db.commit()
    db.refresh(s)
    return scenario_out(db, s)


@router.put("/scenarios/{sid}")
def update_scenario(sid: str, body: ScenarioIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("scenarios.write"))):
    s = db.get(Scenario, sid)
    if s is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    _validate(body)
    cat = db.scalar(select(ScenarioCategory).where(ScenarioCategory.slug == body.category))
    if cat is None:
        raise HTTPException(status_code=422, detail="Unknown category.")
    s.category_id, s.is_demo = cat.id, body.is_demo
    v = _new_version(db, s, body)
    audit(db, actor=user, category="scenario", action="scenario_versioned", target_type="scenario", target_id=sid,
          detail={"version_no": v.version_no}, request=request)
    db.commit()
    db.refresh(s)
    return scenario_out(db, s)


@router.post("/scenarios/{sid}/status")
def set_status(sid: str, body: dict, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require("scenarios.write"))):
    s = db.get(Scenario, sid)
    if s is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    status = body.get("status")
    if status not in ("draft", "published", "retired"):
        raise HTTPException(status_code=422, detail="status must be draft, published or retired")
    s.status = status
    audit(db, actor=user, category="scenario", action=f"scenario_{status}", target_type="scenario", target_id=sid,
          request=request)
    db.commit()
    return {"ok": True}


@router.put("/scenarios/{sid}/policy")
def set_policy(sid: str, body: PolicyIn, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require("scenarios.write"))):
    bad = set(body.allowed_modes) - set(EXECUTION_MODES)
    if bad or not body.allowed_modes or body.default_mode not in body.allowed_modes:
        raise HTTPException(status_code=422, detail="Modes must be known, non-empty, and include the default.")
    pol = db.scalar(select(ScenarioExecutionPolicy).where(ScenarioExecutionPolicy.scenario_id == sid))
    if pol is None:
        pol = ScenarioExecutionPolicy(scenario_id=sid)
        db.add(pol)
    for k, v in body.model_dump().items():
        setattr(pol, k, v)
    audit(db, actor=user, category="scenario", action="scenario_policy_updated", target_type="scenario",
          target_id=sid, detail=body.model_dump(), request=request)
    db.commit()
    return {"ok": True}


@router.get("/scenarios/{sid}/versions")
def versions(sid: str, db: Session = Depends(get_db), _: User = Depends(require("scenarios.write"))):
    return [{"id": v.id, "version_no": v.version_no, "name": v.name, "created_at": v.created_at}
            for v in db.scalars(select(ScenarioVersion).where(ScenarioVersion.scenario_id == sid)
                                .order_by(ScenarioVersion.version_no.desc()))]


# ---------------------------------------------------------------- categories

class CategoryIn(BaseModel):
    slug: str = Field(max_length=80)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field("", max_length=2000)
    notice: str = Field("", max_length=1000)
    position: int = 0


@router.get("/scenario-categories/manage")
def manage_categories(db: Session = Depends(get_db), _: User = Depends(require("scenarios.write"))):
    counts = dict(db.execute(select(Scenario.category_id, func.count()).group_by(Scenario.category_id)).all())
    return [{"id": c.id, "slug": c.slug, "name": c.name, "description": c.description, "notice": c.notice,
             "position": c.position, "scenario_count": counts.get(c.id, 0)}
            for c in db.scalars(select(ScenarioCategory).order_by(ScenarioCategory.position, ScenarioCategory.name))]


@router.post("/scenario-categories")
def create_category(body: CategoryIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("scenarios.write"))):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", body.slug):
        raise HTTPException(status_code=422, detail="Slug must be lowercase letters, digits and hyphens.")
    if db.scalar(select(ScenarioCategory).where(ScenarioCategory.slug == body.slug)):
        raise HTTPException(status_code=409, detail="A category with that slug exists.")
    c = ScenarioCategory(**body.model_dump())
    db.add(c)
    audit(db, actor=user, category="scenario", action="category_created", target_type="scenario_category",
          detail=body.model_dump(), request=request)
    db.commit()
    return {"id": c.id}


@router.put("/scenario-categories/{cid}")
def update_category(cid: str, body: CategoryIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("scenarios.write"))):
    c = db.get(ScenarioCategory, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="Category not found.")
    if body.slug != c.slug and db.scalar(select(ScenarioCategory).where(ScenarioCategory.slug == body.slug)):
        raise HTTPException(status_code=409, detail="A category with that slug exists.")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    audit(db, actor=user, category="scenario", action="category_updated", target_type="scenario_category",
          target_id=cid, detail=body.model_dump(), request=request)
    db.commit()
    return {"ok": True}


@router.delete("/scenario-categories/{cid}")
def delete_category(cid: str, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("scenarios.write"))):
    c = db.get(ScenarioCategory, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="Category not found.")
    n = db.scalar(select(func.count()).select_from(Scenario).where(Scenario.category_id == cid))
    if n:
        raise HTTPException(status_code=409, detail=f"{n} scenario(s) use this category; move them first.")
    audit(db, actor=user, category="scenario", action="category_deleted", target_type="scenario_category",
          target_id=cid, detail={"slug": c.slug}, request=request)
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- AI scenario generator

@router.get("/scenarios/generator/models")
def generator_models(db: Session = Depends(get_db), _: User = Depends(require("scenarios.write"))):
    from ..ai import service as ai_svc
    from ..ai.router import RouteRequest, rank
    from ..models import AIModel
    res = rank(list(db.scalars(select(AIModel))), RouteRequest(capability="", allow_test_provider=
                                                               ai_svc.test_provider_allowed(db)), None)
    return [{"id": c.model.id, "provider": c.provider.name, "model": c.model.model_id,
             "label": f"{c.provider.name} · {c.model.display_name or c.model.model_id}",
             "is_test": c.provider.kind == "deterministic_test"} for c in res.candidates]


class GenerateIn(BaseModel):
    brief: str = Field(min_length=10, max_length=4000)
    category: str
    kind: str = "reasoning"  # reasoning | computation
    model_id: str | None = None


@router.post("/scenarios/generate")
def generate_scenario(body: GenerateIn, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require("scenarios.write"))):
    from ..ai import service as ai_svc
    from ..scenarios.generator import generate
    cat = db.scalar(select(ScenarioCategory).where(ScenarioCategory.slug == body.category))
    if cat is None:
        raise HTTPException(status_code=422, detail="Unknown category.")
    if body.kind not in ("reasoning", "computation"):
        raise HTTPException(status_code=422, detail="kind must be reasoning or computation")
    try:
        draft = generate(db, brief=body.brief, category=cat, kind=body.kind, model_id=body.model_id,
                         user_id=user.id)
    except ai_svc.AIUnavailable as e:
        raise HTTPException(status_code=503, detail=f"No AI model available to generate scenarios: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    audit(db, actor=user, category="scenario", action="scenario_generated", target_type="scenario",
          detail={"brief": body.brief[:300], "model": draft.get("_generated_by")}, request=request)
    db.commit()
    return draft
