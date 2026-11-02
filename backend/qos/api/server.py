"""HTTP API.

    POST /solve      {"goal": "...", "data": {...}, "policy": {...}}  -> Solution
    POST /plan       same body, returns the estimate without executing
    POST /explain    same body, returns the decision report as text
    POST /jobs       same body, returns a job id immediately (async)
    GET  /jobs/{id}  poll a job
    GET  /backends   inventory of every backend and its status
    GET  /templates  supported problem types and the data each needs
    GET  /health

Async jobs exist because a real hardware run can queue for minutes to hours.
Jobs live in memory, which is correct for a single-process deployment and
explicitly not durable -- a restart loses them. Swapping the ``JOBS`` dict for
Redis or a database is the intended path to multi-worker operation.

FastAPI is an optional dependency, imported inside ``create_app`` so the rest
of the platform works without it.
"""

from __future__ import annotations

import threading
from typing import Any

from ..models import Job, Policy, Solution


JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


# The request model must live at MODULE level, not inside create_app(). With
# ``from __future__ import annotations`` every annotation is a string, and
# FastAPI resolves ``req: SolveRequest`` against this module's globals. A class
# defined inside create_app() is invisible there, so FastAPI silently falls
# back to treating the body as a query parameter and rejects every request
# with "Field required: query.req". Pydantic ships with fastapi, so this is
# guarded to keep the module importable without the API extras installed.
try:
    from pydantic import BaseModel, Field

    class SolveRequest(BaseModel):
        goal: str = Field(..., description="the computational goal in plain language")
        data: dict[str, Any] | None = Field(None, description="structured problem data")
        policy: dict[str, Any] | None = Field(
            None, description="cost/latency/vendor constraints"
        )
        use_llm: str = Field("auto", description="auto | never | always")

except ImportError:          # pragma: no cover - API extras not installed
    SolveRequest = None      # type: ignore[assignment]


def _policy_from(payload: dict[str, Any] | None) -> Policy:
    p = dict(payload or {})
    return Policy(
        max_cost_usd=float(p.get("max_cost_usd", 0.0)),
        max_wait_s=float(p.get("max_wait_s", 300.0)),
        priority=str(p.get("priority", "balanced")),
        allow_vendors=tuple(p.get("allow_vendors") or ()),
        deny_vendors=tuple(p.get("deny_vendors") or ()),
        allow_hardware=bool(p.get("allow_hardware", False)),
        require_classical_baseline=bool(p.get("require_classical_baseline", True)),
        seed=p.get("seed"),
        force_backend=p.get("force_backend"),
        force_algorithm=p.get("force_algorithm"),
    )


def solution_to_dict(sol: Solution) -> dict[str, Any]:
    out: dict[str, Any] = {
        "goal": sol.goal,
        "answer": _jsonable(sol.answer),
        "summary": sol.summary,
        "objective_value": sol.objective_value,
        "feasible": sol.feasible,
        "violations": sol.violations,
        "confidence": sol.confidence,
        "baseline_value": sol.baseline_value,
        "quantum_advantage": sol.quantum_advantage,
        "trace": sol.trace,
    }
    if sol.spec:
        out["interpretation"] = {
            "problem_class": sol.spec.problem_class.value,
            "template": sol.spec.template,
            "objective": sol.spec.objective.value,
            "confidence": sol.spec.confidence,
            "rationale": sol.spec.rationale,
            "assumptions": sol.spec.assumptions,
        }
    if sol.raw:
        out["execution"] = {
            "backend": sol.raw.backend_id,
            "algorithm": sol.raw.algorithm,
            "shots": sol.raw.shots,
            "iterations": sol.raw.iterations,
            "cost_usd": sol.raw.cost_usd,
            "wall_time_s": sol.raw.wall_time_s,
            "meta": _jsonable(sol.raw.meta),
        }
    if sol.plan:
        out["plan"] = {
            "chosen": f"{sol.plan.primary.backend.id}:{sol.plan.primary.algorithm}",
            "reason": sol.plan.primary.reason,
            "fallbacks": [f"{s.backend.id}:{s.algorithm}" for s in sol.plan.fallbacks],
            "considered": [
                {"candidate": c, "score": round(s, 4), "reason": r}
                for c, s, r in sol.plan.considered
            ],
            "rejected": [{"candidate": c, "why": w} for c, w in sol.plan.rejected],
        }
    return out


def _jsonable(v: Any) -> Any:
    """Make numpy types and callables safe for JSON serialization."""
    import numpy as np

    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if callable(v):
        return f"<callable {getattr(v, '__name__', 'anonymous')}>"
    return v


def create_app():
    """Build the FastAPI application."""
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "the HTTP API needs fastapi: pip install 'quantum-os[api]'"
        ) from e
    if SolveRequest is None:  # pragma: no cover
        raise RuntimeError(
            "the HTTP API needs pydantic: pip install 'quantum-os[api]'"
        )

    from ..providers.registry import Registry
    from ..runtime.orchestrator import MissingProblemData, explain, solve

    app = FastAPI(
        title="Quantum OS",
        description="State a computational goal; the platform selects quantum or "
                    "classical resources and returns the answer.",
        version="0.1.0",
    )
    registry = Registry()

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        """The browser console. The root URL is the first thing anyone opens,
        and a bare 404 there makes a working service look broken."""
        from .ui import INDEX_HTML

        return INDEX_HTML

    @app.get("/health")
    def health() -> dict:
        usable = registry.usable()
        return {
            "status": "ok",
            "backends_usable": len(usable),
            "backends_known": len(registry.capabilities()),
            "providers": registry.summary(),
        }

    @app.get("/backends")
    def backends(refresh: bool = False) -> dict:
        if refresh:
            registry.refresh()
        return {
            "providers": [
                {
                    "vendor": s.vendor,
                    "status": s.status,
                    "detail": s.detail,
                    "hint": s.install_hint or s.credential_hint,
                }
                for s in registry.statuses()
            ],
            "backends": [
                {
                    "id": c.id,
                    "vendor": c.vendor,
                    "name": c.name,
                    "modality": c.modality.value,
                    "max_qubits": c.max_qubits,
                    "two_qubit_error": c.two_qubit_error,
                    "cost_per_shot_usd": c.cost_per_shot_usd,
                    "cost_per_second_usd": c.cost_per_second_usd,
                    "usable": c.available and c.credentialed,
                    "credentialed": c.credentialed,
                    "unavailable_reason": c.unavailable_reason,
                    "queue_wait_s": c.est_queue_wait_s,
                    "tags": list(c.tags),
                }
                for c in registry.capabilities()
            ],
        }

    @app.get("/templates")
    def templates() -> dict:
        from ..formulations.library import TEMPLATES
        from ..intent.patterns import PATTERNS

        by_template = {p.template: p for p in PATTERNS if p.template}
        return {
            "templates": [
                {
                    "name": name,
                    "description": t.description,
                    "sense": t.sense,
                    "required_data": list(by_template[name].requires)
                    if name in by_template else [],
                    "field_help": by_template[name].field_help if name in by_template else {},
                }
                for name, t in sorted(TEMPLATES.items())
            ]
        }

    @app.post("/solve")
    def post_solve(req: SolveRequest) -> dict:
        try:
            sol = solve(
                req.goal, req.data,
                policy=_policy_from(req.policy),
                registry=registry,
                use_llm=req.use_llm,
            )
        except MissingProblemData as e:
            # 422: the request was understood but is not actionable as given.
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "missing_problem_data",
                    "message": str(e),
                    "template": e.spec.template,
                    "missing": e.spec.missing_data,
                },
            ) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e
        return solution_to_dict(sol)

    @app.post("/plan")
    def post_plan(req: SolveRequest) -> dict:
        try:
            sol = solve(
                req.goal, req.data,
                policy=_policy_from(req.policy),
                registry=registry,
                use_llm=req.use_llm,
                dry_run=True,
            )
        except MissingProblemData as e:
            raise HTTPException(
                status_code=422,
                detail={"error": "missing_problem_data", "message": str(e),
                        "missing": e.spec.missing_data},
            ) from e
        return solution_to_dict(sol)

    @app.post("/explain")
    def post_explain(req: SolveRequest) -> dict:
        return {
            "report": explain(
                req.goal, req.data,
                policy=_policy_from(req.policy),
                registry=registry,
                use_llm=req.use_llm,
            )
        }

    @app.post("/jobs", status_code=202)
    def post_job(req: SolveRequest) -> dict:
        job = Job(goal=req.goal)
        with _LOCK:
            JOBS[job.id] = job

        def worker() -> None:
            try:
                solve(
                    req.goal, req.data,
                    policy=_policy_from(req.policy),
                    registry=registry,
                    use_llm=req.use_llm,
                    job=job,
                )
            except Exception as e:
                job.status = "failed"
                job.error = f"{type(e).__name__}: {e}"
                job.log(job.error)

        threading.Thread(target=worker, daemon=True).start()
        return {"job_id": job.id, "status": job.status, "poll": f"/jobs/{job.id}"}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no job {job_id}")
        out: dict[str, Any] = {
            "job_id": job.id,
            "goal": job.goal,
            "status": job.status,
            "created_at": job.created_at,
            "finished_at": job.finished_at,
            "events": [{"at": t, "message": m} for t, m in job.events],
        }
        if job.error:
            out["error"] = job.error
        if job.solution is not None:
            out["solution"] = solution_to_dict(job.solution)
        return out

    @app.get("/jobs")
    def list_jobs() -> dict:
        return {
            "jobs": [
                {"job_id": j.id, "goal": j.goal, "status": j.status,
                 "created_at": j.created_at}
                for j in sorted(JOBS.values(), key=lambda j: -j.created_at)
            ]
        }

    return app
