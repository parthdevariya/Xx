"""Automatic Quantum Selection Engine.

Returns exactly one decision with the 15 evaluated factors and a plain-language explanation:

    quantum_recommended | quantum_experimental | quantum_simulation_recommended
    classical_preferred | quantum_not_applicable | insufficient_information

"quantum_recommended" requires admin-entered benefit evidence on the algorithm record for this
problem class and size. None ships, so out of the box X never recommends quantum.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from qos.broker.selector import NoViableBackend
from qos.broker.selector import plan as build_plan
from qos.formulations.library import TEMPLATES
from qos.models import Policy

from ..models import QuantumAlgorithm
from .service import (EXACT_CLASSICAL_MAX_VARS, FilteredRegistry, active_backend_keys, credential_env,
                      execution_class_for, formulate)

DECISIONS = ("quantum_recommended", "quantum_experimental", "quantum_simulation_recommended",
             "classical_preferred", "quantum_not_applicable", "insufficient_information")
QUANTUM_STUDY_MODES = {"ai_quantum", "benchmark"}


def _decision(decision: str, explanation: str, factors: dict, **extra) -> dict:
    assert decision in DECISIONS
    return {"decision": decision, "explanation": explanation, "factors": factors,
            "run_quantum": decision in ("quantum_recommended", "quantum_experimental",
                                        "quantum_simulation_recommended"), **extra}


def _evidence_for(db: Session, algorithm: str, template: str, n: int) -> list[dict]:
    key = "qaoa" if algorithm.startswith("qaoa") else algorithm.split("_")[0]
    algo = db.scalar(select(QuantumAlgorithm).where(QuantumAlgorithm.key == key))
    if not algo:
        return []
    return [e for e in algo.benefit_evidence or []
            if e.get("problem") in (template, "*") and e.get("min_vars", 0) <= n <= e.get("max_vars", 10 ** 9)]


def missing_fields(template: str | None, data: dict | None) -> list[str]:
    """Required data keys for a template that are absent, using quantum-os's own pattern definitions."""
    from qos.intent.patterns import PATTERNS
    if not template:
        return []
    pat = next((p for p in PATTERNS if p.template == template), None)
    if pat is None:
        return []
    data = data or {}
    return [f"{k}: {pat.field_help.get(k, 'required')}" for k in pat.requires if data.get(k) is None]


def evaluate(db: Session, *, template: str | None, data: dict | None, missing: list[str] | None = None,
             mode: str = "hybrid", allow_hardware: bool = False, max_cost_usd: float = 0.0,
             eligibility: str = "evaluate") -> dict:
    blank = {k: None for k in (
        "problem_type", "mathematical_structure", "problem_size", "computational_complexity",
        "algorithm_compatibility", "available_quantum_resources", "qubit_requirements", "circuit_depth",
        "shots", "hardware_noise", "queue_time", "execution_cost", "expected_solution_quality",
        "classical_alternatives", "potential_quantum_benefit")}

    if eligibility == "never":
        return _decision("quantum_not_applicable", "This scenario is configured as not quantum-eligible.", blank)
    if not template:
        f = dict(blank, problem_type="not mapped to a quantum-compatible formulation (optimisation, search or "
                                     "ground-state)")
        return _decision("quantum_not_applicable",
                         "The problem was not identified as combinatorial optimisation, unstructured search or a "
                         "ground-state calculation, so no quantum algorithm in the library applies. AI and "
                         "Intellect reasoning handle it.", f)
    t = TEMPLATES.get(template)
    if t is None:
        return _decision("quantum_not_applicable", f"Unknown solver template {template!r}.", blank)
    if missing:
        f = dict(blank, problem_type=t.description)
        return _decision("insufficient_information",
                         "The problem matches the " + template + " formulation, but required data is missing: "
                         + "; ".join(missing), f, missing=missing)
    try:
        spec, form = formulate(template, data or {})
    except (KeyError, ValueError, TypeError) as e:
        f = dict(blank, problem_type=t.description)
        return _decision("insufficient_information", f"The supplied data cannot be encoded: {e}", f,
                         missing=[str(e)])

    n = form.num_vars
    factors = dict(blank)
    factors.update({
        "problem_type": f"{template}: {t.description}",
        "mathematical_structure": f"{form.kind.value}" + (f" with constraint penalties "
                                                          f"({', '.join(form.penalties)})" if form.penalties else ""),
        "problem_size": f"{n} binary variables",
        "computational_complexity": f"search space 2^{n} = {2 ** n:,} assignments",
        "classical_alternatives": ("exhaustive enumeration gives a proven optimum of the encoding"
                                   if n <= EXACT_CLASSICAL_MAX_VARS else
                                   "simulated annealing and tabu search (heuristic, no optimality proof)"),
    })

    with credential_env(db):
        reg = FilteredRegistry(active_backend_keys(db), quantum_only=True)
        pol = Policy(max_cost_usd=max_cost_usd, allow_hardware=allow_hardware, require_classical_baseline=False)
        try:
            plan = build_plan(spec, form, reg, pol)
        except NoViableBackend as e:
            factors["available_quantum_resources"] = "none fits: " + "; ".join(
                f"{b}: {why}" for b, why in e.rejected[:6])
            factors["potential_quantum_benefit"] = "none available"
            return _decision("classical_preferred",
                             f"No available quantum backend can run this {n}-variable formulation under the "
                             "current policy (qubits, cost, credentials). Classical computation is used.",
                             factors, rejected=e.rejected[:20])

    p = plan.primary
    need, cap = p.need, p.backend
    exec_class = execution_class_for(cap)
    factors.update({
        "algorithm_compatibility": f"{p.algorithm} supports {form.kind.value}",
        "available_quantum_resources": ", ".join(sorted({s.backend.id for s in [p, *plan.fallbacks]})),
        "qubit_requirements": need.logical_qubits,
        "circuit_depth": need.circuit_depth,
        "shots": need.shots,
        "hardware_noise": (f"two-qubit error {cap.two_qubit_error}" if cap.two_qubit_error else
                           "noise-free simulation" if exec_class.endswith("simulator") else "not reported"),
        "queue_time": f"{cap.est_queue_wait_s:.0f}s estimated" if cap.est_queue_wait_s else "none (local)",
        "execution_cost": f"${need.est_cost_usd:.4f} estimated",
        "expected_solution_quality": f"broker score {p.score:.3f} on {cap.id}",
    })
    evidence = _evidence_for(db, p.algorithm, template, n)
    if evidence:
        factors["potential_quantum_benefit"] = "evidence on record: " + "; ".join(
            e.get("citation", "uncited") for e in evidence)
    else:
        factors["potential_quantum_benefit"] = ("no evidence on record of quantum benefit for this problem class "
                                                "and size; classical methods are expected to match or beat it")
    route = {"backend": cap.id, "backend_name": cap.name, "algorithm": p.algorithm, "execution_class": exec_class,
             "est_cost_usd": round(need.est_cost_usd, 6), "qubits": need.logical_qubits}

    if eligibility != "simulation_only" and evidence and exec_class == "hardware":
        return _decision("quantum_recommended",
                         f"Recorded evidence supports quantum benefit for {template} at {n} variables, and "
                         f"{cap.name} fits the resource and cost limits.", factors, route=route, evidence=evidence)
    if exec_class == "hardware" and eligibility != "simulation_only":
        return _decision("quantum_experimental",
                         f"{cap.name} (real quantum hardware) fits {need.logical_qubits} qubits within the cost "
                         "and queue limits. Results are research data, compared against the classical baseline; "
                         "they are not a claim of quantum advantage.", factors, route=route)
    if mode in QUANTUM_STUDY_MODES:
        return _decision("quantum_simulation_recommended",
                         f"The formulation fits the {exec_class.replace('_', ' ')} {cap.name} "
                         f"({need.logical_qubits} qubits). It runs as a study of quantum algorithm behaviour; "
                         "the classical baseline remains the reference answer.", factors, route=route)
    return _decision("classical_preferred",
                     (f"With {n} variables, exhaustive classical search proves the optimum quickly; " if
                      n <= EXACT_CLASSICAL_MAX_VARS else "Classical heuristics handle this size well; ")
                     + f"a quantum simulation on {cap.name} is available for comparison but is not expected to "
                       "improve the answer.", factors, route=route, simulation_available=True)
