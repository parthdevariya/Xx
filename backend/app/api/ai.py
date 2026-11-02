from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai import service as ai_svc
from ..ai.providers import ADAPTERS, build_adapter
from ..ai.providers.base import ProviderError
from ..ai.router import RouteRequest, rank
from ..db import get_db
from ..deps import require
from ..models import AICapability, AICredential, AIExecutionLog, AIModel, AIProvider, AIRoutingPolicy, User
from ..security import encrypt_secret, secret_hint
from ..services.audit import audit

router = APIRouter(prefix="/api/ai", tags=["ai"])
AUTH_SCHEMES = {"bearer", "x-api-key", "api-key", "none"}


class ProviderIn(BaseModel):
    name: str = Field(max_length=120)
    kind: str
    base_url: str = Field("", max_length=400)
    auth_scheme: str = "bearer"
    is_active: bool = False
    timeout_s: float = Field(60.0, gt=0, le=900)
    rate_limit_rpm: int = Field(60, ge=1, le=100000)
    config: dict = {}


class ProviderPatch(BaseModel):
    name: str | None = Field(None, max_length=120)
    base_url: str | None = Field(None, max_length=400)
    auth_scheme: str | None = None
    is_active: bool | None = None
    timeout_s: float | None = Field(None, gt=0, le=900)
    rate_limit_rpm: int | None = Field(None, ge=1, le=100000)
    config: dict | None = None


class CredentialIn(BaseModel):
    secret: str = Field(min_length=1, max_length=8000)
    extra: str = Field("", max_length=8000)


class ModelIn(BaseModel):
    model_id: str = Field(max_length=160)
    display_name: str = Field("", max_length=160)
    capabilities: list[str] = []
    modalities: list[str] = ["text"]
    context_window: int = Field(128000, ge=1)
    max_output_tokens: int = Field(4096, ge=1)
    input_cost_per_mtok: float = Field(0.0, ge=0)
    output_cost_per_mtok: float = Field(0.0, ge=0)
    quality_rank: int = Field(50, ge=0, le=100)
    latency_class: str = "medium"
    is_active: bool = True


class ModelPatch(BaseModel):
    display_name: str | None = None
    capabilities: list[str] | None = None
    modalities: list[str] | None = None
    context_window: int | None = Field(None, ge=1)
    max_output_tokens: int | None = Field(None, ge=1)
    input_cost_per_mtok: float | None = Field(None, ge=0)
    output_cost_per_mtok: float | None = Field(None, ge=0)
    quality_rank: int | None = Field(None, ge=0, le=100)
    latency_class: str | None = None
    is_active: bool | None = None


class PolicyIn(BaseModel):
    name: str = Field(max_length=120)
    description: str = ""
    is_default: bool = False
    rules: dict = {}


def provider_out(p: AIProvider) -> dict:
    return {"id": p.id, "name": p.name, "kind": p.kind, "base_url": p.base_url, "auth_scheme": p.auth_scheme,
            "is_active": p.is_active, "timeout_s": p.timeout_s, "rate_limit_rpm": p.rate_limit_rpm,
            "config": p.config, "health_status": p.health_status, "last_latency_ms": p.last_latency_ms,
            "last_checked_at": p.last_checked_at, "last_error": p.last_error,
            "credential": {"configured": p.credential is not None,
                           "hint": p.credential.hint if p.credential else ""},
            "is_test_provider": p.kind == "deterministic_test",
            "models": [model_out(m) for m in p.models]}


def model_out(m: AIModel) -> dict:
    return {"id": m.id, "provider_id": m.provider_id, "model_id": m.model_id, "display_name": m.display_name,
            "capabilities": m.capabilities, "modalities": m.modalities, "context_window": m.context_window,
            "max_output_tokens": m.max_output_tokens, "input_cost_per_mtok": m.input_cost_per_mtok,
            "output_cost_per_mtok": m.output_cost_per_mtok, "quality_rank": m.quality_rank,
            "latency_class": m.latency_class, "is_active": m.is_active}


def _provider(db, pid) -> AIProvider:
    p = db.get(AIProvider, pid)
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    return p


@router.get("/meta")
def meta(db: Session = Depends(get_db), _: User = Depends(require("ai.read"))):
    return {"kinds": sorted(ADAPTERS), "auth_schemes": sorted(AUTH_SCHEMES),
            "capabilities": [{"code": c.code, "description": c.description} for c in db.scalars(select(AICapability))]}


@router.get("/providers")
def list_providers(db: Session = Depends(get_db), _: User = Depends(require("ai.read"))):
    return [provider_out(p) for p in db.scalars(select(AIProvider).order_by(AIProvider.name))]


@router.post("/providers")
def create_provider(body: ProviderIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("ai.write"))):
    if body.kind not in ADAPTERS:
        raise HTTPException(status_code=422, detail=f"Unknown provider kind; known: {sorted(ADAPTERS)}")
    if body.auth_scheme not in AUTH_SCHEMES:
        raise HTTPException(status_code=422, detail="Unknown auth scheme.")
    if db.scalar(select(AIProvider).where(AIProvider.name == body.name)):
        raise HTTPException(status_code=409, detail="A provider with that name exists.")
    p = AIProvider(**body.model_dump(), health_status="unconfigured")
    db.add(p)
    db.flush()
    audit(db, actor=user, category="provider", action="ai_provider_created", target_type="ai_provider",
          target_id=p.id, detail=body.model_dump(), request=request)
    db.commit()
    db.refresh(p)
    return provider_out(p)


@router.patch("/providers/{pid}")
def update_provider(pid: str, body: ProviderPatch, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("ai.write"))):
    p = _provider(db, pid)
    changes = body.model_dump(exclude_none=True)
    if "auth_scheme" in changes and changes["auth_scheme"] not in AUTH_SCHEMES:
        raise HTTPException(status_code=422, detail="Unknown auth scheme.")
    for k, v in changes.items():
        setattr(p, k, v)
    audit(db, actor=user, category="provider", action="ai_provider_updated", target_type="ai_provider",
          target_id=p.id, detail=changes, request=request)
    db.commit()
    db.refresh(p)
    return provider_out(p)


@router.delete("/providers/{pid}")
def delete_provider(pid: str, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("ai.write"))):
    p = _provider(db, pid)
    audit(db, actor=user, category="provider", action="ai_provider_deleted", target_type="ai_provider",
          target_id=p.id, detail={"name": p.name}, request=request)
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.put("/providers/{pid}/credential")
def set_credential(pid: str, body: CredentialIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require("ai.write"))):
    p = _provider(db, pid)
    enc = encrypt_secret(body.secret.strip())
    extra = encrypt_secret(body.extra) if body.extra else ""
    if p.credential:
        p.credential.secret_encrypted, p.credential.hint, p.credential.extra_encrypted = \
            enc, secret_hint(body.secret.strip()), extra
    else:
        db.add(AICredential(provider_id=p.id, secret_encrypted=enc, hint=secret_hint(body.secret.strip()),
                            extra_encrypted=extra))
    p.health_status = "unknown"
    audit(db, actor=user, category="provider", action="ai_credential_set", target_type="ai_provider",
          target_id=p.id, request=request)
    db.commit()
    db.refresh(p)
    return provider_out(p)


@router.delete("/providers/{pid}/credential")
def delete_credential(pid: str, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require("ai.write"))):
    p = _provider(db, pid)
    if p.credential:
        db.delete(p.credential)
    p.health_status = "unconfigured"
    audit(db, actor=user, category="provider", action="ai_credential_deleted", target_type="ai_provider",
          target_id=p.id, request=request)
    db.commit()
    db.refresh(p)
    return provider_out(p)


@router.post("/providers/{pid}/health")
def check_health(pid: str, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require("ai.write"))):
    p = _provider(db, pid)
    rec = ai_svc.health_check(db, p)
    audit(db, actor=user, category="provider", action="ai_health_check", target_type="ai_provider",
          target_id=p.id, detail={"status": rec.status}, request=request)
    db.commit()
    return {"status": rec.status, "latency_ms": rec.latency_ms, "detail": rec.detail}


@router.post("/providers/{pid}/discover-models")
def discover_models(pid: str, db: Session = Depends(get_db), _: User = Depends(require("ai.write"))):
    p = _provider(db, pid)
    try:
        ids = build_adapter(ai_svc.provider_config(p)).list_models()
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    known = {m.model_id for m in p.models}
    return {"available": sorted(ids), "not_registered": sorted(set(ids) - known)}


@router.post("/providers/{pid}/models")
def add_model(pid: str, body: ModelIn, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require("ai.write"))):
    p = _provider(db, pid)
    if any(m.model_id == body.model_id for m in p.models):
        raise HTTPException(status_code=409, detail="Model already registered for this provider.")
    m = AIModel(provider_id=p.id, **body.model_dump())
    db.add(m)
    audit(db, actor=user, category="provider", action="ai_model_added", target_type="ai_model",
          detail=body.model_dump(), request=request)
    db.commit()
    db.refresh(m)
    return model_out(m)


@router.patch("/models/{mid}")
def update_model(mid: str, body: ModelPatch, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require("ai.write"))):
    m = db.get(AIModel, mid)
    if m is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(m, k, v)
    audit(db, actor=user, category="provider", action="ai_model_updated", target_type="ai_model", target_id=mid,
          detail=changes, request=request)
    db.commit()
    db.refresh(m)
    return model_out(m)


@router.delete("/models/{mid}")
def delete_model(mid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require("ai.write"))):
    m = db.get(AIModel, mid)
    if m is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    audit(db, actor=user, category="provider", action="ai_model_deleted", target_type="ai_model", target_id=mid,
          request=request)
    db.delete(m)
    db.commit()
    return {"ok": True}


@router.get("/routing-policies")
def list_policies(db: Session = Depends(get_db), _: User = Depends(require("ai.read"))):
    return [{"id": p.id, "name": p.name, "description": p.description, "is_default": p.is_default, "rules": p.rules}
            for p in db.scalars(select(AIRoutingPolicy))]


@router.post("/routing-policies")
def save_policy(body: PolicyIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require("ai.write"))):
    p = db.scalar(select(AIRoutingPolicy).where(AIRoutingPolicy.name == body.name))
    if p is None:
        p = AIRoutingPolicy(name=body.name)
        db.add(p)
    p.description, p.rules = body.description, body.rules
    if body.is_default:
        for other in db.scalars(select(AIRoutingPolicy)):
            other.is_default = False
        p.is_default = True
    audit(db, actor=user, category="config", action="ai_routing_policy_saved", target_type="ai_routing_policy",
          detail=body.model_dump(), request=request)
    db.commit()
    return {"ok": True, "id": p.id}


@router.delete("/routing-policies/{policy_id}")
def delete_policy(policy_id: str, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require("ai.write"))):
    p = db.get(AIRoutingPolicy, policy_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Policy not found.")
    if p.is_default:
        raise HTTPException(status_code=409, detail="Make another policy the default before deleting this one.")
    audit(db, actor=user, category="config", action="ai_routing_policy_deleted", target_type="ai_routing_policy",
          target_id=policy_id, detail={"name": p.name}, request=request)
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/route-preview")
def route_preview(body: dict, db: Session = Depends(get_db), _: User = Depends(require("ai.read"))):
    req = RouteRequest(capability=body.get("capability", "text_reasoning"), category=body.get("category", ""),
                       allow_test_provider=ai_svc.test_provider_allowed(db))
    res = rank(list(db.scalars(select(AIModel))), req, ai_svc.default_policy(db))
    return {"candidates": [{"provider": c.provider.name, "model": c.model.model_id, "score": c.score,
                            "est_cost_usd": c.est_cost_usd, "reason": c.reason} for c in res.candidates],
            "rejected": [{"model": m, "reason": r} for m, r in res.rejected]}


@router.get("/logs")
def logs(limit: int = 100, status: str | None = None, db: Session = Depends(get_db),
         _: User = Depends(require("ai.read"))):
    q = select(AIExecutionLog).order_by(AIExecutionLog.at.desc()).limit(min(limit, 500))
    if status:
        q = q.where(AIExecutionLog.status == status)
    return [{"id": l.id, "at": l.at, "execution_id": l.execution_id, "model": l.model_id, "kind": l.provider_kind,
             "purpose": l.purpose, "status": l.status, "input_tokens": l.input_tokens,
             "output_tokens": l.output_tokens, "cost_usd": l.cost_usd, "latency_ms": l.latency_ms, "error": l.error}
            for l in db.scalars(q)]


@router.get("/usage")
def usage(db: Session = Depends(get_db), _: User = Depends(require("ai.read"))):
    rows = db.execute(select(AIExecutionLog.model_id, func.count(), func.sum(AIExecutionLog.input_tokens),
                             func.sum(AIExecutionLog.output_tokens), func.sum(AIExecutionLog.cost_usd),
                             func.avg(AIExecutionLog.latency_ms))
                      .where(AIExecutionLog.status != "error").group_by(AIExecutionLog.model_id)).all()
    errors = db.scalar(select(func.count()).select_from(AIExecutionLog).where(AIExecutionLog.status == "error"))
    return {"by_model": [{"model": r[0], "calls": r[1], "input_tokens": r[2] or 0, "output_tokens": r[3] or 0,
                          "cost_usd": round(r[4] or 0, 6), "avg_latency_ms": round(r[5] or 0, 1)} for r in rows],
            "errors": errors}
