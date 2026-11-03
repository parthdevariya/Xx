from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import timedelta

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal, get_db
from ..deps import current_user, require
from ..intellect.importer import ImportRejected, extract_text
from ..models import (BackgroundJob, BenchmarkRun, Execution, ExecutionArtifact, ExecutionEvent, ExecutionResult,
                      IntellectRun, Scenario, SystemSetting, User, utcnow)
from ..orchestration import executor
from ..orchestration.events import emit
from ..orchestration.intake import InputValidationError
from ..orchestration.planner import MODES
from ..ratelimit import limit
from ..security import create_ws_ticket, decode_token
from ..services.audit import audit

router = APIRouter(prefix="/api", tags=["executions"])
MAX_FILES = 3

DEFAULT_ORCHESTRATION = {"default_mode": "hybrid", "max_cost_usd": 0.0, "allow_hardware": False,
                         "executions_per_user_per_day": 200, "available_modes": list(MODES)}


def orchestration_settings(db: Session) -> dict:
    row = db.get(SystemSetting, "orchestration")
    return {**DEFAULT_ORCHESTRATION, **(row.value if row else {})}


class SubmitIn(BaseModel):
    text: str = Field("", max_length=20000)
    inputs: dict = {}
    scenario_slug: str | None = None
    mode: str = "hybrid"
    allow_hardware: bool = False
    max_cost_usd: float | None = Field(None, ge=0)
    layer_switches: dict = {}
    auto_run: bool = True


def _visible(db: Session, user: User, eid: str) -> Execution:
    ex = db.get(Execution, eid)
    if ex is None or (ex.user_id != user.id and "executions.read_all" not in user.permission_codes):
        raise HTTPException(status_code=404, detail="Execution not found.")
    return ex


def execution_out(db: Session, ex: Execution, full: bool = False) -> dict:
    out = {"id": ex.id, "mode": ex.mode, "mode_label": MODES.get(ex.mode, ex.mode), "status": ex.status,
           "scenario_id": ex.scenario_id, "is_demo": ex.is_demo, "result_source": ex.result_source,
           "created_at": ex.created_at, "started_at": ex.started_at, "finished_at": ex.finished_at,
           "ai_provider": ex.ai_provider, "ai_model": ex.ai_model, "quantum_backend": ex.quantum_backend,
           "algorithm": ex.algorithm, "estimated_cost_usd": ex.estimated_cost_usd,
           "actual_cost_usd": ex.actual_cost_usd, "error": ex.error, "event_seq": ex.event_seq,
           "problem_summary": (ex.problem.text or (ex.problem.structured or {}).get("scenario_name", ""))[:200]}
    if full:
        out["problem"] = {"text": ex.problem.text, "inputs": ex.problem.inputs, "attachments": ex.problem.attachments,
                          "structured": ex.problem.structured}
        out["plan"] = {"mode": ex.plan.mode, "steps": ex.plan.steps, "quantum_decision": ex.plan.quantum_decision,
                       "estimates": ex.plan.estimates, "baselines": ex.plan.baselines} if ex.plan else None
        out["final_output"] = ex.final_output
        out["resource_usage"] = ex.resource_usage
        out["results"] = [{"step": r.step_key, "engine": r.engine, "content_class": r.content_class,
                           "execution_class": r.execution_class, "title": r.title, "content": r.content,
                           "created_at": r.created_at}
                          for r in db.scalars(select(ExecutionResult).where(ExecutionResult.execution_id == ex.id)
                                              .order_by(ExecutionResult.created_at))]
        bench = db.scalar(select(BenchmarkRun).where(BenchmarkRun.execution_id == ex.id))
        out["benchmark"] = ({"id": bench.id, "objective": bench.objective, "conclusion": bench.conclusion,
                             "methodology": bench.methodology, "environment": bench.environment,
                             "input_sha256": bench.input_sha256,
                             "metrics": [{"approach": m.approach, "metric": m.metric, "value": m.value,
                                          "text": m.text_value, "unit": m.unit, "notes": m.notes}
                                         for m in bench.metrics]} if bench else None)
        out["intellect_runs"] = [r.id for r in db.scalars(select(IntellectRun).where(IntellectRun.execution_id == ex.id))]
        out["artifacts"] = [{"kind": a.kind, "name": a.name} for a in
                            db.scalars(select(ExecutionArtifact).where(ExecutionArtifact.execution_id == ex.id))]
        if ex.framework_version_id:
            from ..models import IntellectVersion
            v = db.get(IntellectVersion, ex.framework_version_id)
            out["framework_version"] = v.label if v else None
    return out


async def _read_attachments(files: list[UploadFile]) -> tuple[list[dict], str]:
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=422, detail=f"At most {MAX_FILES} files per problem.")
    meta, texts = [], []
    for f in files:
        raw = await f.read(get_settings().upload_max_bytes + 1)
        if len(raw) > get_settings().upload_max_bytes:
            raise HTTPException(status_code=413, detail=f"{f.filename} exceeds the upload size limit.")
        try:
            ext, text = extract_text(f.filename or "file.txt", raw)
        except ImportRejected as e:
            raise HTTPException(status_code=422, detail=f"{f.filename}: {e}") from e
        text = text.replace("=====PAGE=====", "")[:50000]
        meta.append({"name": (f.filename or "")[:200], "size": len(raw), "kind": ext,
                     "sha256": hashlib.sha256(raw).hexdigest(), "extracted_chars": len(text)})
        texts.append(f"--- {f.filename} ---\n{text}")
    return meta, "\n\n".join(texts)


def _submit(db: Session, request: Request, user: User, body: SubmitIn, attachments: list[dict], att_text: str,
            is_demo: bool = False) -> dict:
    limit(request, "submit", 30)
    orch = orchestration_settings(db)
    if body.mode not in MODES or body.mode not in orch["available_modes"]:
        raise HTTPException(status_code=422, detail=f"Mode unavailable; choose from {orch['available_modes']}")
    since = utcnow() - timedelta(days=1)
    n_today = db.scalar(select(func.count()).select_from(Execution)
                        .where(Execution.user_id == user.id, Execution.created_at >= since))
    if n_today >= orch["executions_per_user_per_day"] and user.role.code not in ("super_admin", "admin"):
        raise HTTPException(status_code=429, detail="Daily execution quota reached.")
    scenario = None
    if body.scenario_slug:
        scenario = db.scalar(select(Scenario).where(Scenario.slug == body.scenario_slug))
        if scenario is None or scenario.status != "published":
            raise HTTPException(status_code=404, detail="Scenario not found or not published.")
    elif not body.text.strip() and not att_text:
        raise HTTPException(status_code=422, detail="Describe the problem or choose a scenario.")
    allow_hw = body.allow_hardware and orch["allow_hardware"]
    # The orchestration policy caps what any single execution may spend; 0 means free routes only.
    max_cost = min(body.max_cost_usd or 0.0, float(orch["max_cost_usd"]))
    try:
        ex = executor.create_execution(db, user_id=user.id, text=body.text, inputs=body.inputs, scenario=scenario,
                                       mode=body.mode, attachments=attachments, attachments_text=att_text,
                                       allow_hardware=allow_hw, max_cost_usd=max_cost,
                                       layer_switches=body.layer_switches, is_demo=is_demo)
    except InputValidationError as e:
        raise HTTPException(status_code=422, detail={"message": "Invalid inputs", "errors": e.errors}) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    audit(db, actor=user, category="execution", action="execution_created", target_type="execution",
          target_id=ex.id, detail={"mode": body.mode, "scenario": body.scenario_slug, "demo": is_demo},
          request=request)
    db.commit()
    if body.auto_run and ex.status == "planned" and ex.estimated_cost_usd <= 0:
        executor.enqueue(db, ex)
    db.refresh(ex)
    return execution_out(db, ex, full=True)


@router.post("/executions")
def submit_json(body: SubmitIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require("executions.run"))):
    return _submit(db, request, user, body, [], "")


@router.post("/executions/upload")
async def submit_multipart(request: Request, payload: str = Form(...), files: list[UploadFile] = File(default=[]),
                           db: Session = Depends(get_db), user: User = Depends(require("executions.run"))):
    try:
        body = SubmitIn(**json.loads(payload))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid payload: {e}") from e
    meta, text = await _read_attachments(files)
    return _submit(db, request, user, body, meta, text)


@router.post("/executions/{eid}/run")
def run(eid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require("executions.run"))):
    ex = _visible(db, user, eid)
    try:
        executor.enqueue(db, ex)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    audit(db, actor=user, category="execution", action="execution_started", target_type="execution",
          target_id=eid, detail={"estimated_cost_usd": ex.estimated_cost_usd}, request=request)
    db.commit()
    return execution_out(db, ex)


@router.post("/executions/{eid}/cancel")
def cancel(eid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require("executions.run"))):
    ex = _visible(db, user, eid)
    if ex.status in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Execution already {ex.status}.")
    if ex.status in ("planned", "queued", "awaiting_input"):
        ex.status = "cancelled"
        for job in db.scalars(select(BackgroundJob).where(BackgroundJob.execution_id == eid,
                                                          BackgroundJob.status == "queued")):
            job.status = "cancelled"
        emit(db, ex, "system", "execution.cancelled", "Execution cancelled before it started", {}, commit=False)
    else:
        ex.cancel_requested = True
        emit(db, ex, "system", "execution.cancel_requested", "Cancellation requested; stopping after the current step",
             {}, commit=False)
    audit(db, actor=user, category="execution", action="execution_cancelled", target_type="execution",
          target_id=eid, request=request)
    db.commit()
    return execution_out(db, ex)


@router.get("/executions")
def list_executions(limit_: int = Query(50, alias="limit"), all: bool = False, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    q = select(Execution).order_by(Execution.created_at.desc()).limit(min(limit_, 200))
    if not (all and "executions.read_all" in user.permission_codes):
        q = q.where(Execution.user_id == user.id)
    return [execution_out(db, e) for e in db.scalars(q)]


@router.get("/executions/{eid}")
def get_execution(eid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return execution_out(db, _visible(db, user, eid), full=True)


@router.get("/executions/{eid}/events")
def events(eid: str, after: int = 0, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _visible(db, user, eid)
    rows = db.scalars(select(ExecutionEvent).where(ExecutionEvent.execution_id == eid, ExecutionEvent.seq > after)
                      .order_by(ExecutionEvent.seq).limit(500))
    return [event_out(e) for e in rows]


def event_out(e: ExecutionEvent) -> dict:
    return {"seq": e.seq, "at": e.at.isoformat() if e.at else None, "engine": e.engine, "type": e.type,
            "message": e.message, "data": e.data}


@router.get("/executions/{eid}/trace")
def execution_trace(eid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Everything each engine did in this execution, for the engine inspector. Visible to the execution owner."""
    from ..models import AIExecutionLog, QuantumExecutionLog, QuantumJob
    from .intellect import run_out
    ex = _visible(db, user, eid)
    runs = db.scalars(select(IntellectRun).where(IntellectRun.execution_id == ex.id).order_by(IntellectRun.started_at))
    ai_logs = db.scalars(select(AIExecutionLog).where(AIExecutionLog.execution_id == ex.id).order_by(AIExecutionLog.at))
    jobs = db.scalars(select(QuantumJob).where(QuantumJob.execution_id == ex.id).order_by(QuantumJob.submitted_at)).all()
    return {
        "intellect_runs": [run_out(db, r, full=True) for r in runs],
        "ai_calls": [{"at": l.at, "model": l.model_id, "kind": l.provider_kind, "purpose": l.purpose,
                      "status": l.status, "input_tokens": l.input_tokens, "output_tokens": l.output_tokens,
                      "cost_usd": l.cost_usd, "latency_ms": l.latency_ms, "error": l.error} for l in ai_logs],
        "quantum_jobs": [{**{c.name: getattr(j, c.name) for c in QuantumJob.__table__.columns},
                          "logs": [{"at": q.at, "level": q.level, "message": q.message} for q in
                                   db.scalars(select(QuantumExecutionLog).where(QuantumExecutionLog.job_id == j.id))]}
                         for j in jobs],
    }


class SwarmChatIn(BaseModel):
    target: str = Field(max_length=40)  # agent id or "report"
    message: str = Field(min_length=1, max_length=4000)
    history: list[dict] = []


@router.post("/executions/{eid}/swarm/chat")
def swarm_chat(eid: str, body: SwarmChatIn, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require("executions.run"))):
    from ..ai.service import AIUnavailable
    from ..intellect.swarm import chat
    ex = _visible(db, user, eid)
    row = db.scalar(select(ExecutionResult).where(ExecutionResult.execution_id == ex.id,
                                                  ExecutionResult.step_key == "swarm"))
    if row is None or not row.content.get("report"):
        raise HTTPException(status_code=409, detail="Deep Interaction needs a completed swarm simulation.")
    limit(request, "swarm-chat", 30)
    try:
        return chat(db, row.content, target=body.target, message=body.message, history=body.history,
                    execution_id=ex.id, user_id=user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AIUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    finally:
        db.commit()


@router.get("/executions/{eid}/report.{fmt}")
def report(eid: str, fmt: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ex = _visible(db, user, eid)
    kind = {"md": "report_md", "json": "report_json"}.get(fmt)
    if kind is None:
        raise HTTPException(status_code=404, detail="Unknown format.")
    art = db.scalar(select(ExecutionArtifact).where(ExecutionArtifact.execution_id == ex.id,
                                                    ExecutionArtifact.kind == kind))
    if art is None:
        raise HTTPException(status_code=404, detail="Report not available (execution not completed).")
    return PlainTextResponse(art.content, media_type=art.content_type,
                             headers={"Content-Disposition": f'attachment; filename="{art.name}"'})


@router.post("/executions/{eid}/ws-ticket")
def ws_ticket(eid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _visible(db, user, eid)
    return {"ticket": create_ws_ticket(user.id, eid)}


@router.websocket("/ws/executions/{eid}")
async def ws_events(websocket: WebSocket, eid: str, ticket: str, after: int = 0):
    data = decode_token(ticket, "ws")
    if not data or data.get("eid") != eid:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    last = after
    try:
        while True:
            db = SessionLocal()
            try:
                rows = db.scalars(select(ExecutionEvent).where(ExecutionEvent.execution_id == eid,
                                                               ExecutionEvent.seq > last)
                                  .order_by(ExecutionEvent.seq).limit(200)).all()
                ex = db.get(Execution, eid)
                status = ex.status if ex else "missing"
            finally:
                db.close()
            for e in rows:
                await websocket.send_json({"type": "event", "event": event_out(e)})
                last = e.seq
            if status in ("completed", "failed", "cancelled", "awaiting_input", "missing") and not rows:
                await websocket.send_json({"type": "status", "status": status})
                await websocket.close()
                return
            await asyncio.sleep(0.4)
    except WebSocketDisconnect:
        return


# ---------------------------------------------------------------- demo mode

@router.post("/demo/{slug}/run")
def demo_run(slug: str, request: Request, body: dict | None = None, db: Session = Depends(get_db),
             user: User = Depends(require("executions.run"))):
    s = db.scalar(select(Scenario).where(Scenario.slug == slug, Scenario.status == "published"))
    if s is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    from ..models import ScenarioExecutionPolicy
    pol = db.scalar(select(ScenarioExecutionPolicy).where(ScenarioExecutionPolicy.scenario_id == s.id))
    mode = (body or {}).get("mode") or (pol.default_mode if pol else "hybrid")
    return _submit(db, request, user, SubmitIn(scenario_slug=slug, mode=mode), [], "", is_demo=True)


@router.get("/demo/{slug}/cached")
def demo_cached(slug: str, mode: str | None = None, db: Session = Depends(get_db),
                user: User = Depends(require("scenarios.read"))):
    """Most recent completed execution of this scenario, returned explicitly labelled as cached."""
    s = db.scalar(select(Scenario).where(Scenario.slug == slug))
    if s is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    q = select(Execution).where(Execution.scenario_id == s.id, Execution.status == "completed")
    if mode:
        q = q.where(Execution.mode == mode)
    ex = db.scalar(q.order_by(Execution.finished_at.desc()).limit(1))
    if ex is None:
        raise HTTPException(status_code=404, detail="No completed run of this scenario yet.")
    out = execution_out(db, ex, full=True)
    out["cached"] = {"is_cached": True, "original_execution_id": ex.id, "computed_at": ex.finished_at,
                     "original_result_source": ex.result_source,
                     "label": f"Cached result from {ex.finished_at:%Y-%m-%d %H:%M} UTC — not a live run"}
    return out
