from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import (AIExecutionLog, AIProvider, AuditLog, BackgroundJob, CostRecord, Execution,
                      IntellectFramework, IntellectRule, IntellectVersion, QuantumJob, QuantumProvider, Scenario,
                      SystemSetting, User, utcnow)
from ..services.audit import audit
from .executions import DEFAULT_ORCHESTRATION, orchestration_settings

router = APIRouter(prefix="/api", tags=["admin"])


def _count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


@router.get("/system/status")
def system_status(db: Session = Depends(get_db)):
    """Public, non-sensitive readiness used by the initialisation sequence. Reports real state only."""
    ai_ready = [p.name for p in db.scalars(select(AIProvider).where(AIProvider.is_active.is_(True)))
                if p.kind != "deterministic_test" and (p.credential is not None or p.auth_scheme == "none")]
    test_active = db.scalar(select(AIProvider).where(AIProvider.kind == "deterministic_test",
                                                     AIProvider.is_active.is_(True))) is not None
    qp = [{"vendor": p.vendor, "name": p.name, "status": p.health_status, "active": p.is_active}
          for p in db.scalars(select(QuantumProvider).order_by(QuantumProvider.vendor))]
    fw = db.scalar(select(IntellectFramework).where(IntellectFramework.slug == "x-layers"))
    v = db.get(IntellectVersion, fw.active_version_id) if fw and fw.active_version_id else None
    workers_recent = _count(db, BackgroundJob, BackgroundJob.heartbeat_at >= utcnow() - timedelta(minutes=10))
    return {
        "database": "ok",
        "ai": {"configured_providers": ai_ready, "status": "ready" if ai_ready else "unconfigured",
               "test_provider_active": test_active},
        "quantum": {"providers": qp,
                    "status": "ready" if any(p["status"] == "healthy" and p["active"] for p in qp) else "unavailable"},
        "intellect": {"framework": fw.name if fw else None, "version": v.label if v else None,
                      "layers": len(v.layers) if v else 0, "rules": len(v.rules) if v else 0,
                      "protected": sum(1 for r in v.rules if r.is_protected) if v else 0,
                      "status": "ready" if v else "missing"},
        "scenarios": {"published": _count(db, Scenario, Scenario.status == "published")},
        "worker": {"recently_active_jobs": workers_recent},
    }


@router.get("/admin/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(require("dashboard.read"))):
    since = utcnow() - timedelta(days=30)
    by_status = dict(db.execute(select(Execution.status, func.count()).group_by(Execution.status)).all())
    by_mode = dict(db.execute(select(Execution.mode, func.count()).group_by(Execution.mode)).all())
    ai_calls = _count(db, AIExecutionLog)
    ai_tokens = db.execute(select(func.sum(AIExecutionLog.input_tokens), func.sum(AIExecutionLog.output_tokens))).one()
    q_by_class = dict(db.execute(select(QuantumJob.execution_class, func.count())
                                 .group_by(QuantumJob.execution_class)).all())
    cost_ai = db.scalar(select(func.sum(CostRecord.amount_usd)).where(CostRecord.category == "ai")) or 0.0
    cost_q = db.scalar(select(func.sum(CostRecord.amount_usd)).where(CostRecord.category == "quantum")) or 0.0
    daily = db.execute(select(func.date(Execution.created_at), func.count()).where(Execution.created_at >= since)
                       .group_by(func.date(Execution.created_at)).order_by(func.date(Execution.created_at))).all()
    return {
        "users": {"total": _count(db, User), "active": _count(db, User, User.is_active.is_(True))},
        "executions": {"total": sum(by_status.values()), "by_status": by_status, "by_mode": by_mode,
                       "successful": by_status.get("completed", 0), "failed": by_status.get("failed", 0),
                       "daily_30d": [{"date": str(d), "count": c} for d, c in daily]},
        "ai": {"calls": ai_calls, "input_tokens": ai_tokens[0] or 0, "output_tokens": ai_tokens[1] or 0,
               "errors": _count(db, AIExecutionLog, AIExecutionLog.status == "error")},
        "quantum": {"jobs": sum(q_by_class.values()), "by_execution_class": q_by_class,
                    "failed": _count(db, QuantumJob, QuantumJob.status == "failed")},
        "scenarios": {"published": _count(db, Scenario, Scenario.status == "published"),
                      "draft": _count(db, Scenario, Scenario.status == "draft")},
        "frameworks": {"frameworks": _count(db, IntellectFramework), "versions": _count(db, IntellectVersion),
                       "rules": _count(db, IntellectRule)},
        "providers": {"ai": [{"name": p.name, "active": p.is_active, "health": p.health_status}
                             for p in db.scalars(select(AIProvider))],
                      "quantum": [{"name": p.name, "active": p.is_active, "health": p.health_status}
                                  for p in db.scalars(select(QuantumProvider))]},
        "costs": {"ai_usd_estimated": round(cost_ai, 4), "quantum_usd": round(cost_q, 4)},
        "jobs": {"queued": _count(db, BackgroundJob, BackgroundJob.status == "queued"),
                 "running": _count(db, BackgroundJob, BackgroundJob.status == "running"),
                 "failed": _count(db, BackgroundJob, BackgroundJob.status == "failed")},
    }


@router.get("/admin/audit")
def audit_logs(category: str | None = None, outcome: str | None = None, q: str | None = None, limit: int = 200,
               db: Session = Depends(get_db), _: User = Depends(require("audit.read"))):
    stmt = select(AuditLog).order_by(AuditLog.at.desc()).limit(min(limit, 1000))
    if category:
        stmt = stmt.where(AuditLog.category == category)
    if outcome:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(AuditLog.action.ilike(like), AuditLog.actor_email.ilike(like),
                              AuditLog.target_id.ilike(like), AuditLog.target_type.ilike(like)))
    return [{"id": a.id, "at": a.at, "actor": a.actor_email, "category": a.category, "action": a.action,
             "target_type": a.target_type, "target_id": a.target_id, "outcome": a.outcome, "detail": a.detail,
             "ip": a.ip} for a in db.scalars(stmt)]


@router.get("/modes")
def modes(_: User = Depends(require("scenarios.read"))):
    """Catalogue of every execution mode: label, engines involved, requirements and description."""
    from ..orchestration.planner import MODE_INFO, MODES
    return [{"key": k, "label": MODES[k], **MODE_INFO[k]} for k in MODES]


@router.get("/admin/settings/orchestration")
def get_orchestration(db: Session = Depends(get_db), _: User = Depends(require("dashboard.read"))):
    return orchestration_settings(db)


@router.put("/admin/settings/orchestration")
def put_orchestration(body: dict, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require("policies.write"))):
    unknown = set(body) - set(DEFAULT_ORCHESTRATION)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown settings: {sorted(unknown)}")
    if "max_cost_usd" in body and (not isinstance(body["max_cost_usd"], (int, float)) or body["max_cost_usd"] < 0):
        raise HTTPException(status_code=422, detail="max_cost_usd must be ≥ 0")
    row = db.get(SystemSetting, "orchestration")
    if row is None:
        row = SystemSetting(key="orchestration", value={}, description="Orchestration policies")
        db.add(row)
    row.value = {**row.value, **body}
    row.updated_by = user.id
    audit(db, actor=user, category="config", action="orchestration_policy_updated", detail=body, request=request)
    db.commit()
    return orchestration_settings(db)
