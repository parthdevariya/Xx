"""Quantum Engine service over the vendored quantum-os library.

Every result carries an execution_class derived from the backend's declared modality —
never from the caller — so simulated results cannot be presented as hardware results.
Quantum steps never fall back silently to a classical solver: if no quantum route works the
step fails and says why; classical computation is a separate, separately labelled step.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from qos.algorithms import classical
from qos.broker.selector import NoViableBackend
from qos.broker.selector import plan as build_plan
from qos.formulations.library import TEMPLATES
from qos.interpret.decoder import interpret
from qos.models import (BackendCapability, Formulation, Modality, Objective, Policy, ProblemClass, ProblemSpec,
                        RawResult)
from qos.providers.base import ProviderExecutionError, ProviderUnavailable
from qos.providers.registry import Registry
from qos.runtime.orchestrator import compile_problem

from ..models import QuantumBackend, QuantumCredential, QuantumExecutionLog, QuantumJob, QuantumProvider, utcnow
from ..security import decrypt_secret

LOCAL_SIM_MAX_QUBITS = 22
EXACT_CLASSICAL_MAX_VARS = 24

# Environment variables each qos adapter reads. extra JSON keys map 1:1 to env names.
CREDENTIAL_ENV = {
    "ibm": "IBM_QUANTUM_TOKEN",
    "dwave": "DWAVE_API_TOKEN",
    "aws": "AWS_SECRET_ACCESS_KEY",   # extra: AWS_ACCESS_KEY_ID, AWS_DEFAULT_REGION
    "azure": "AZURE_CLIENT_SECRET",   # extra: AZURE_QUANTUM_SUBSCRIPTION_ID, ..._RESOURCE_GROUP, ...
    "google": "GOOGLE_APPLICATION_CREDENTIALS_JSON",  # extra: GOOGLE_QUANTUM_PROCESSOR_ID
}


class QuantumRouteUnavailable(RuntimeError):
    def __init__(self, message: str, rejected: list[tuple[str, str]] | None = None):
        super().__init__(message)
        self.rejected = rejected or []


def execution_class_for(cap: BackendCapability) -> str:
    if cap.modality is Modality.CLASSICAL:
        return "classical"
    if cap.modality is Modality.GATE_SIMULATOR:
        return "local_simulator" if cap.vendor == "local" else "cloud_simulator"
    return "hardware"  # gate_qpu, annealer


def db_modality(cap: BackendCapability) -> str:
    if cap.modality is Modality.CLASSICAL:
        return "classical"
    if cap.modality is Modality.GATE_SIMULATOR:
        return "local_simulator" if cap.vendor == "local" else "cloud_simulator"
    return "annealer" if cap.modality is Modality.ANNEALER else "gate_hardware"


@contextmanager
def credential_env(db: Session):
    """Expose stored, decrypted quantum credentials to the SDK adapters for the duration of a job.

    Worker processes run one job at a time, so process environment is not shared across jobs.
    """
    previous: dict[str, str | None] = {}
    try:
        for cred in db.scalars(select(QuantumCredential)):
            prov = db.get(QuantumProvider, cred.provider_id)
            if not prov or not prov.is_active:
                continue
            env = {}
            if prov.vendor in CREDENTIAL_ENV:
                env[CREDENTIAL_ENV[prov.vendor]] = decrypt_secret(cred.secret_encrypted)
            if cred.extra_encrypted:
                import json
                env.update({k: str(v) for k, v in json.loads(decrypt_secret(cred.extra_encrypted)).items()})
            for k, v in env.items():
                previous.setdefault(k, os.environ.get(k))
                os.environ[k] = v
        yield
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class FilteredRegistry(Registry):
    """qos registry restricted to backends that are active in X's database (and optionally to a modality set)."""

    def __init__(self, allowed: set[str] | None, quantum_only: bool = False):
        super().__init__()
        self.allowed = allowed
        self.quantum_only = quantum_only

    def capabilities(self, *, refresh: bool = False) -> list[BackendCapability]:
        caps = super().capabilities(refresh=refresh)
        out = []
        for c in caps:
            if self.allowed is not None and c.id not in self.allowed:
                continue
            if self.quantum_only and c.modality is Modality.CLASSICAL:
                continue
            out.append(c)
        return out


def active_backend_keys(db: Session) -> set[str]:
    rows = db.execute(select(QuantumBackend.backend_key, QuantumProvider.is_active, QuantumBackend.is_active)
                      .join(QuantumProvider, QuantumBackend.provider_id == QuantumProvider.id)).all()
    return {k for k, p_on, b_on in rows if p_on and b_on}


# ---------------------------------------------------------------------------
# registry sync (health)
# ---------------------------------------------------------------------------

VENDOR_NAMES = {"local": "Local simulators (built in)", "ibm": "IBM Quantum (Qiskit Runtime)",
                "aws": "Amazon Braket", "azure": "Azure Quantum", "dwave": "D-Wave Leap",
                "google": "Google Quantum AI (Cirq)"}


def sync_registry(db: Session, refresh_live: bool = False) -> dict:
    """Mirror qos provider/backends into the DB with their real availability. Never marks a provider
    healthy that has not reported ready."""
    with credential_env(db):
        reg = Registry()
        statuses = {s.vendor: s for s in reg.statuses()}
        if refresh_live:
            reg.refresh()
        caps = reg.capabilities()
    summary = {}
    for vendor, st in statuses.items():
        prov = db.scalar(select(QuantumProvider).where(QuantumProvider.vendor == vendor))
        if prov is None:
            prov = QuantumProvider(name=VENDOR_NAMES.get(vendor, vendor), vendor=vendor,
                                   is_active=(vendor == "local"))
            db.add(prov)
            db.flush()
        prov.sdk_available = st.status != "sdk_missing"
        prov.health_status = {"ready": "healthy", "sdk_missing": "unavailable",
                              "no_credentials": "unconfigured"}.get(st.status, "down")
        prov.health_detail = st.detail if hasattr(st, "detail") else str(getattr(st, "message", ""))
        prov.last_checked_at = utcnow()
        summary[vendor] = prov.health_status
    by_key = {b.backend_key: b for b in db.scalars(select(QuantumBackend))}
    providers = {p.vendor: p for p in db.scalars(select(QuantumProvider))}
    for c in caps:
        b = by_key.get(c.id)
        if b is None:
            b = QuantumBackend(provider_id=providers[c.vendor].id, backend_key=c.id, name=c.name,
                               modality=db_modality(c), is_hardware=execution_class_for(c) == "hardware",
                               is_active=True)
            db.add(b)
        b.max_qubits = c.max_qubits
        b.supported_formulations = [k.value for k in c.supports]
        b.max_shots = c.max_shots
        b.pricing = {"per_shot_usd": c.cost_per_shot_usd, "per_task_usd": c.cost_per_task_usd,
                     "per_second_usd": c.cost_per_second_usd}
        b.two_qubit_error = c.two_qubit_error
        b.queue_depth = c.queue_depth or None
        b.status = "online" if (c.available and c.credentialed) else "unavailable"
        b.status_detail = c.unavailable_reason or ("" if c.credentialed else "no credentials")
    db.flush()
    return summary


# ---------------------------------------------------------------------------
# formulation
# ---------------------------------------------------------------------------

def build_spec(template: str, data: dict, goal: str = "") -> ProblemSpec:
    t = TEMPLATES.get(template)
    if t is None:
        raise ValueError(f"unknown solver template {template!r}")
    objective = {"max": Objective.MAXIMIZE, "min": Objective.MINIMIZE}.get(t.sense, Objective.SATISFY)
    if template == "graph_coloring":
        objective = Objective.SATISFY
    return ProblemSpec(raw_goal=goal or t.description, problem_class=ProblemClass.QUBO, objective=objective,
                       template=template, data=data, confidence=1.0, rationale="explicit template")


def formulate(template: str, data: dict, goal: str = "") -> tuple[ProblemSpec, Formulation]:
    spec = build_spec(template, data, goal)
    return spec, compile_problem(spec)


@dataclass
class SolveOutcome:
    answer: dict
    objective_value: float | None
    feasible: bool
    violations: list[str]
    energy: float | None
    backend_key: str
    algorithm: str
    execution_class: str
    wall_time_s: float
    cost_usd: float
    shots: int
    qubits: int
    circuit_depth: int
    num_vars: int
    proven_optimal: bool
    top_counts: list[tuple[str, int]]
    trace: list[str]
    meta: dict

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _outcome(spec, f, raw: RawResult, exec_class: str, trace: list[str], *, qubits=0, depth=0,
             proven=False, plan=None) -> SolveOutcome:
    sol = interpret(spec, f, raw, plan, None, list(trace))
    counts = sorted((raw.counts or {}).items(), key=lambda kv: -kv[1])[:8]
    ans = sol.answer if isinstance(sol.answer, dict) else {"value": sol.answer}
    return SolveOutcome(answer=_jsonable(ans), objective_value=sol.objective_value, feasible=sol.feasible,
                        violations=list(sol.violations), energy=raw.best_energy, backend_key=raw.backend_id,
                        algorithm=raw.algorithm, execution_class=exec_class, wall_time_s=raw.wall_time_s,
                        cost_usd=raw.cost_usd, shots=raw.shots, qubits=qubits, circuit_depth=depth,
                        num_vars=f.num_vars, proven_optimal=proven, top_counts=counts, trace=trace,
                        meta=_jsonable({k: v for k, v in raw.meta.items() if k != "prior_failures"}))


def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, np.ndarray):
        return x.tolist()
    return x


def classical_solve(template: str, data: dict, seed: int | None = 7) -> SolveOutcome:
    """Classical baseline: exhaustive (proven optimum) up to 20 vars, otherwise best of SA and tabu."""
    spec, f = formulate(template, data)
    Q = np.asarray(f.Q)
    trace = [f"formulated {template} as {f.kind.value} with {f.num_vars} binary variables"]
    t0 = time.perf_counter()
    raw = classical.best_classical(Q, f.offset, seed=seed)
    raw.wall_time_s = raw.wall_time_s or (time.perf_counter() - t0)
    proven = raw.algorithm.startswith("exact") or f.num_vars <= 20
    trace.append(f"classical solver {raw.algorithm} reached energy {raw.best_energy:.6g}"
                 + (" (exhaustive: proven optimum of the encoding)" if proven else " (heuristic: best found)"))
    raw.backend_id = raw.backend_id or "local.classical"
    return _outcome(spec, f, raw, "classical", trace, proven=proven)


def quantum_solve(db: Session, template: str, data: dict, *, allow_hardware: bool = False,
                  max_cost_usd: float = 0.0, seed: int | None = 7, execution_id: str | None = None,
                  backend_key: str | None = None, on_event=None) -> SolveOutcome:
    """Run on a quantum backend (simulator or hardware). Raises QuantumRouteUnavailable if none fits."""
    spec, f = formulate(template, data)
    emit = on_event or (lambda *a, **k: None)
    with credential_env(db):
        reg = FilteredRegistry(active_backend_keys(db), quantum_only=True)
        pol = Policy(max_cost_usd=max_cost_usd, allow_hardware=allow_hardware, seed=seed,
                     require_classical_baseline=False, force_backend=backend_key)
        if allow_hardware:
            reg.refresh()
        try:
            plan = build_plan(spec, f, reg, pol)
        except NoViableBackend as e:
            raise QuantumRouteUnavailable(
                f"no quantum backend can run this {f.num_vars}-variable problem under the current policy",
                e.rejected) from e
        trace = [f"formulated {template} as {f.kind.value} with {f.num_vars} binary variables",
                 f"quantum plan: {plan.primary.algorithm} on {plan.primary.backend.id} — {plan.primary.reason}"]
        errors = []
        for step in [plan.primary, *plan.fallbacks]:
            cap = step.backend
            exec_class = execution_class_for(cap)
            job = QuantumJob(execution_id=execution_id, backend_key=cap.id, algorithm=step.algorithm,
                             execution_class=exec_class, status="running", qubits=step.need.logical_qubits,
                             circuit_depth=step.need.circuit_depth, shots=step.need.shots)
            db.add(job)
            db.flush()
            emit("quantum.job_submitted", f"Quantum job submitted: {step.algorithm} on {cap.name} "
                 f"[{exec_class.replace('_', ' ')}]", {"job_id": job.id, "backend": cap.id,
                                                      "execution_class": exec_class,
                                                      "qubits": step.need.logical_qubits,
                                                      "shots": step.need.shots})
            try:
                raw = reg.run(cap, f, step.need, pol)
                if raw.error:
                    raise ProviderExecutionError(raw.error)
            except (ProviderUnavailable, ProviderExecutionError, Exception) as e:  # noqa: BLE001
                job.status, job.error, job.completed_at = "failed", str(e)[:2000], utcnow()
                db.add(QuantumExecutionLog(job_id=job.id, level="error", message=str(e)[:2000]))
                errors.append(f"{cap.id}: {e}")
                trace.append(f"failed on {cap.id}: {e}")
                db.flush()
                continue
            job.status, job.completed_at = "completed", utcnow()
            job.wall_time_s, job.cost_usd = raw.wall_time_s, raw.cost_usd
            raw.backend_id = cap.id
            trace.append(f"completed on {cap.id} ({exec_class}): energy {raw.best_energy}, {raw.wall_time_s:.2f}s")
            out = _outcome(spec, f, raw, exec_class, trace, qubits=step.need.logical_qubits,
                           depth=step.need.circuit_depth, plan=plan)
            job.result = {"objective_value": out.objective_value, "feasible": out.feasible,
                          "energy": out.energy, "top_counts": out.top_counts}
            db.add(QuantumExecutionLog(job_id=job.id, message=f"completed: objective {out.objective_value}"))
            db.flush()
            return out
    raise QuantumRouteUnavailable("every quantum route failed: " + "; ".join(errors))
