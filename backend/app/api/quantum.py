from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from qos.formulations.library import TEMPLATES

from ..db import get_db
from ..deps import require
from ..models import (QuantumAlgorithm, QuantumBackend, QuantumCredential, QuantumExecutionLog, QuantumJob,
                      QuantumProvider, User)
from ..quantum import selection
from ..quantum.service import CREDENTIAL_ENV, sync_registry
from ..security import encrypt_secret, secret_hint
from ..services.audit import audit

router = APIRouter(prefix="/api/quantum", tags=["quantum"])


class ProviderPatch(BaseModel):
    is_active: bool | None = None
    endpoint: str | None = Field(None, max_length=400)
    max_execution_s: float | None = Field(None, gt=0)
    max_cost_per_job_usd: float | None = Field(None, ge=0)
    config: dict | None = None


class CredentialIn(BaseModel):
    secret: str = Field(min_length=1, max_length=20000)
    extra: dict = {}  # additional env values, e.g. AWS_ACCESS_KEY_ID, AZURE_QUANTUM_SUBSCRIPTION_ID


class BackendPatch(BaseModel):
    is_active: bool | None = None
    default_shots: int | None = Field(None, ge=1, le=1_000_000)


class AlgorithmPatch(BaseModel):
    description: str | None = None
    known_limitations: list[str] | None = None
    execution_config: dict | None = None
    benefit_evidence: list[dict] | None = None
    is_active: bool | None = None


class EvaluateIn(BaseModel):
    template: str | None = None
    data: dict = {}
    mode: str = "hybrid"
    allow_hardware: bool = False
    max_cost_usd: float = 0.0


def provider_out(p: QuantumProvider) -> dict:
    return {"id": p.id, "name": p.name, "vendor": p.vendor, "endpoint": p.endpoint, "is_active": p.is_active,
            "sdk_available": p.sdk_available, "health_status": p.health_status, "health_detail": p.health_detail,
            "last_checked_at": p.last_checked_at, "max_execution_s": p.max_execution_s,
            "max_cost_per_job_usd": p.max_cost_per_job_usd, "config": p.config,
            "credential": {"configured": p.credential is not None, "hint": p.credential.hint if p.credential else "",
                           "env": CREDENTIAL_ENV.get(p.vendor)},
            "backends": [backend_out(b) for b in p.backends]}


def backend_out(b: QuantumBackend) -> dict:
    return {"id": b.id, "backend_key": b.backend_key, "name": b.name, "modality": b.modality,
            "is_hardware": b.is_hardware, "max_qubits": b.max_qubits, "supported_formulations":
            b.supported_formulations, "max_shots": b.max_shots, "default_shots": b.default_shots,
            "pricing": b.pricing, "two_qubit_error": b.two_qubit_error, "queue_depth": b.queue_depth,
            "status": b.status, "status_detail": b.status_detail, "is_active": b.is_active}


@router.get("/providers")
def list_providers(db: Session = Depends(get_db), _: User = Depends(require("quantum.read"))):
    return [provider_out(p) for p in db.scalars(select(QuantumProvider).order_by(QuantumProvider.vendor))]


@router.post("/sync")
def sync(request: Request, live: bool = False, db: Session = Depends(get_db),
         user: User = Depends(require("quantum.write"))):
    summary = sync_registry(db, refresh_live=live)
    audit(db, actor=user, category="provider", action="quantum_registry_sync", detail=summary, request=request)
    db.commit()
    return {"summary": summary}


@router.patch("/providers/{pid}")
def update_provider(pid: str, body: ProviderPatch, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require("quantum.write"))):
    p = db.get(QuantumProvider, pid)
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(p, k, v)
    audit(db, actor=user, category="provider", action="quantum_provider_updated", target_type="quantum_provider",
          target_id=pid, detail=changes, request=request)
    db.commit()
    db.refresh(p)
    return provider_out(p)


@router.put("/providers/{pid}/credential")
def set_credential(pid: str, body: CredentialIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require("quantum.write"))):
    p = db.get(QuantumProvider, pid)
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    if p.vendor == "local":
        raise HTTPException(status_code=422, detail="Local simulators need no credentials.")
    enc = encrypt_secret(body.secret.strip())
    extra = encrypt_secret(json.dumps(body.extra)) if body.extra else ""
    if p.credential:
        p.credential.secret_encrypted, p.credential.hint, p.credential.extra_encrypted = \
            enc, secret_hint(body.secret.strip()), extra
    else:
        db.add(QuantumCredential(provider_id=p.id, secret_encrypted=enc, hint=secret_hint(body.secret.strip()),
                                 extra_encrypted=extra))
    audit(db, actor=user, category="provider", action="quantum_credential_set", target_type="quantum_provider",
          target_id=pid, detail={"extra_keys": sorted(body.extra)}, request=request)
    db.commit()
    sync_registry(db)
    db.commit()
    db.refresh(p)
    return provider_out(p)


@router.delete("/providers/{pid}/credential")
def delete_credential(pid: str, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require("quantum.write"))):
    p = db.get(QuantumProvider, pid)
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    if p.credential:
        db.delete(p.credential)
    audit(db, actor=user, category="provider", action="quantum_credential_deleted", target_type="quantum_provider",
          target_id=pid, request=request)
    db.commit()
    sync_registry(db)
    db.commit()
    return {"ok": True}


@router.patch("/backends/{bid}")
def update_backend(bid: str, body: BackendPatch, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require("quantum.write"))):
    b = db.get(QuantumBackend, bid)
    if b is None:
        raise HTTPException(status_code=404, detail="Backend not found.")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(b, k, v)
    audit(db, actor=user, category="provider", action="quantum_backend_updated", target_type="quantum_backend",
          target_id=bid, detail=changes, request=request)
    db.commit()
    return backend_out(b)


@router.get("/algorithms")
def list_algorithms(db: Session = Depends(get_db), _: User = Depends(require("quantum.read"))):
    return [{c.name: getattr(a, c.name) for c in QuantumAlgorithm.__table__.columns}
            for a in db.scalars(select(QuantumAlgorithm).order_by(QuantumAlgorithm.key))]


@router.patch("/algorithms/{aid}")
def update_algorithm(aid: str, body: AlgorithmPatch, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require("quantum.write"))):
    a = db.get(QuantumAlgorithm, aid)
    if a is None:
        raise HTTPException(status_code=404, detail="Algorithm not found.")
    changes = body.model_dump(exclude_none=True)
    for ev in changes.get("benefit_evidence", []):
        if not ev.get("citation") or not ev.get("problem"):
            raise HTTPException(status_code=422, detail="Each evidence entry needs 'problem' and 'citation'.")
    for k, v in changes.items():
        setattr(a, k, v)
    audit(db, actor=user, category="provider", action="quantum_algorithm_updated", target_type="quantum_algorithm",
          target_id=aid, detail=changes, request=request)
    db.commit()
    return {"ok": True}


@router.get("/templates")
def templates(_: User = Depends(require("quantum.read"))):
    return [{"name": k, "description": t.description, "sense": t.sense} for k, t in sorted(TEMPLATES.items())]


@router.post("/evaluate")
def evaluate(body: EvaluateIn, db: Session = Depends(get_db), _: User = Depends(require("quantum.read"))):
    return selection.evaluate(db, template=body.template, data=body.data, mode=body.mode,
                              missing=selection.missing_fields(body.template, body.data) or None,
                              allow_hardware=body.allow_hardware, max_cost_usd=body.max_cost_usd)


@router.get("/jobs")
def jobs(limit: int = 100, db: Session = Depends(get_db), _: User = Depends(require("quantum.read"))):
    rows = db.scalars(select(QuantumJob).order_by(QuantumJob.submitted_at.desc()).limit(min(limit, 500)))
    return [{c.name: getattr(j, c.name) for c in QuantumJob.__table__.columns} for j in rows]


@router.get("/jobs/{jid}/logs")
def job_logs(jid: str, db: Session = Depends(get_db), _: User = Depends(require("quantum.read"))):
    return [{"at": l.at, "level": l.level, "message": l.message}
            for l in db.scalars(select(QuantumExecutionLog).where(QuantumExecutionLog.job_id == jid)
                                .order_by(QuantumExecutionLog.at))]
