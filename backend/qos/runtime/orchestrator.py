"""The orchestrator: goal in, answer out.

    solve("pick the 4 best assets from these returns", data={...})

Pipeline:

    parse -> compile -> estimate -> plan -> execute (+fallbacks)
          -> classical baseline -> decode -> verify -> report

Design commitments:

* **Fail soft on infrastructure, loud on data.** A provider going down moves
  to the next fallback silently; a missing distance matrix stops the run and
  says what is needed. Infrastructure problems are the platform's job to
  absorb; missing data is the user's to supply, and guessing it would be
  worse than asking.

* **Always run the baseline.** Cheap relative to a quantum run, and it is the
  only way to make the result interpretable.

* **Trace everything.** Every decision lands in ``Solution.trace`` so a user
  can audit why their job went where it went.
"""

from __future__ import annotations

import time

import numpy as np

from ..algorithms import classical
from ..broker.selector import NoViableBackend, plan as build_plan
from ..formulations.library import TEMPLATES
from ..formulations.qubo import QUBOBuilder
from ..intent.parser import parse
from ..interpret.decoder import interpret
from ..models import (
    ExecutionPlan,
    Formulation,
    FormulationKind,
    Job,
    Policy,
    ProblemClass,
    ProblemSpec,
    RawResult,
    Solution,
)
from ..providers.base import ProviderExecutionError, ProviderUnavailable
from ..providers.registry import Registry


class MissingProblemData(ValueError):
    """The goal was understood, but required problem data was not supplied.

    Carries the specific fields needed so the caller can prompt for exactly
    those rather than re-asking the whole question.
    """

    def __init__(self, spec: ProblemSpec) -> None:
        self.spec = spec
        fields = "\n".join(f"  - {m}" for m in spec.missing_data)
        template = spec.template or spec.problem_class.value
        super().__init__(
            f"Understood the goal as '{template}'"
            + (f" ({spec.rationale})" if spec.rationale else "")
            + f", but this data is still needed:\n{fields}"
        )


def compile_problem(spec: ProblemSpec) -> Formulation:
    """ProblemSpec -> Formulation, via the template library or a direct payload."""
    if spec.template:
        template = TEMPLATES.get(spec.template)
        if template is None:
            raise ValueError(f"unknown template {spec.template!r}")
        return template.build(spec.data)

    if spec.problem_class is ProblemClass.SEARCH:
        predicate = spec.data.get("predicate")
        n = int(spec.data.get("n", 0))
        if predicate is None or n <= 0:
            raise ValueError("search problems need a 'predicate' callable and bit width 'n'")
        return Formulation(
            kind=FormulationKind.ORACLE,
            num_vars=n,
            predicate=predicate,
            decode={"template": None, "n": n},
            notes=[f"oracle search over 2^{n} = {2**n:,} candidates"],
        )

    if spec.problem_class is ProblemClass.GROUND_STATE:
        terms = spec.data.get("terms")
        if not terms:
            raise ValueError("ground-state problems need 'terms' as [[coeff, pauli], ...]")
        norm = [(float(c), str(p)) for c, p in terms]
        return Formulation(
            kind=FormulationKind.PAULI_SUM,
            num_vars=len(norm[0][1]),
            terms=norm,
            decode={"template": None},
            notes=[f"Hamiltonian with {len(norm)} Pauli terms"],
        )

    if "Q" in spec.data:
        Q = np.asarray(spec.data["Q"], dtype=float)
        return Formulation(
            kind=FormulationKind.QUBO,
            num_vars=int(Q.shape[0]),
            Q=(Q + Q.T) / 2.0,
            offset=float(spec.data.get("offset", 0.0)),
            decode={"template": None, "n": int(Q.shape[0])},
            notes=["raw QUBO supplied by caller"],
        )

    raise ValueError(
        f"cannot compile a {spec.problem_class.value} problem without a template "
        "or an explicit Q matrix / Hamiltonian"
    )


def solve(
    goal: str,
    data: dict | None = None,
    *,
    policy: Policy | None = None,
    registry: Registry | None = None,
    use_llm: str = "auto",
    job: Job | None = None,
    dry_run: bool = False,
) -> Solution:
    """Solve a plain-language goal end to end.

    ``dry_run`` plans and estimates without executing, which is how a user
    checks what a paid run would cost before authorizing it.
    """
    pol = policy or Policy()
    reg = registry or Registry()
    trace: list[str] = []
    t_start = time.perf_counter()

    def log(msg: str) -> None:
        trace.append(msg)
        if job is not None:
            job.log(msg)

    # ----------------------------------------------------------- 1. intent
    if job:
        job.status = "planning"
    spec = parse(goal, data, use_llm=use_llm)
    log(
        f"intent: {spec.template or spec.problem_class.value} "
        f"(confidence {spec.confidence:.2f}) -- {spec.rationale}"
    )
    if spec.problem_class is ProblemClass.UNKNOWN or spec.missing_data:
        raise MissingProblemData(spec)

    # ---------------------------------------------------------- 2. compile
    f = compile_problem(spec)
    log(f"compiled to {f.kind.value} with {f.num_vars} variables" +
        (f" ({'; '.join(f.notes)})" if f.notes else ""))
    if f.penalties:
        log("constraint penalty weights: " +
            ", ".join(f"{k}={v:.3g}" for k, v in f.penalties.items()))

    # ------------------------------------------------------------- 3. plan
    if pol.allow_hardware:
        reg.refresh()
        log("refreshed live device status from credentialed providers")
    try:
        plan = build_plan(spec, f, reg, pol)
    except NoViableBackend as e:
        log("planning failed: no viable backend")
        raise
    log(
        f"plan: {plan.primary.algorithm} on {plan.primary.backend.id} "
        f"(score {plan.primary.score:.3f}) -- {plan.primary.reason}"
    )
    for fb in plan.fallbacks:
        log(f"fallback: {fb.algorithm} on {fb.backend.id} (score {fb.score:.3f})")

    if dry_run:
        return _dry_run_solution(spec, f, plan, trace)

    # ---------------------------------------------------------- 4. execute
    if job:
        job.status = "running"
    raw = _execute_with_fallbacks(reg, plan, f, pol, log)

    # --------------------------------------------------------- 5. baseline
    baseline = None
    if pol.require_classical_baseline and f.kind in (FormulationKind.QUBO, FormulationKind.ISING):
        if plan.primary.backend.modality.value != "classical":
            try:
                baseline = classical.best_classical(
                    np.asarray(f.Q), f.offset, seed=pol.seed
                )
                log(
                    f"classical baseline: {baseline.algorithm} reached "
                    f"energy {baseline.best_energy:.6g} in {baseline.wall_time_s:.2f}s"
                )
            except Exception as e:
                log(f"classical baseline unavailable: {e}")
        else:
            # The primary route is already classical; compare against a
            # different classical method so the number still means something.
            try:
                # Kept deliberately light: this is a corroboration check on a
                # route that already succeeded, so it must not cost more than
                # the solve it is checking.
                alt = (
                    classical.simulated_annealing(
                        np.asarray(f.Q), f.offset, seed=pol.seed, reads=8, sweeps=600
                    )
                    if plan.primary.algorithm != "simulated_annealing"
                    else classical.tabu_search(
                        np.asarray(f.Q), f.offset, seed=pol.seed, iterations=2000
                    )
                )
                baseline = alt
                log(f"cross-check: {alt.algorithm} reached energy {alt.best_energy:.6g}")
            except Exception:
                pass

    # -------------------------------------------------------- 6. interpret
    sol = interpret(spec, f, raw, plan, baseline, trace)
    log(f"total wall time {time.perf_counter() - t_start:.2f}s")
    sol.trace = trace
    if job:
        job.status = "done"
        job.finished_at = time.time()
        job.solution = sol
    return sol


def _execute_with_fallbacks(
    reg: Registry, plan: ExecutionPlan, f: Formulation, pol: Policy, log
) -> RawResult:
    """Run the primary route, falling back on infrastructure failure."""
    attempts = [plan.primary, *plan.fallbacks]
    errors: list[str] = []
    for i, step in enumerate(attempts):
        label = f"{step.algorithm} on {step.backend.id}"
        try:
            log(f"executing {label}" + (" (fallback)" if i else ""))
            raw = reg.run(step.backend, f, step.need, pol)
            if raw.error:
                raise ProviderExecutionError(raw.error)
            log(
                f"completed on {step.backend.id}: energy="
                f"{raw.best_energy if raw.best_energy is not None else 'n/a'}"
                f", {raw.wall_time_s:.2f}s, cost=${raw.cost_usd:.2f}"
            )
            return raw
        except (ProviderUnavailable, ProviderExecutionError) as e:
            errors.append(f"{label}: {e}")
            log(f"failed on {step.backend.id}: {e}")
        except Exception as e:                      # unexpected adapter bug
            errors.append(f"{label}: unexpected {type(e).__name__}: {e}")
            log(f"unexpected failure on {step.backend.id}: {type(e).__name__}: {e}")

    # Last resort: the built-in classical solver, which has no dependencies
    # and cannot be unavailable.
    if f.kind in (FormulationKind.QUBO, FormulationKind.ISING):
        log("all planned routes failed; falling back to built-in classical solver")
        raw = classical.best_classical(np.asarray(f.Q), f.offset, seed=pol.seed)
        raw.meta["fallback_of_last_resort"] = True
        raw.meta["prior_failures"] = errors
        return raw

    raise RuntimeError("every execution route failed:\n" + "\n".join(f"  - {e}" for e in errors))


def _dry_run_solution(
    spec: ProblemSpec, f: Formulation, plan: ExecutionPlan, trace: list[str]
) -> Solution:
    p = plan.primary
    answer = {
        "would_run": p.algorithm,
        "on_backend": p.backend.id,
        "backend_name": p.backend.name,
        "variables": f.num_vars,
        "qubits_required": p.need.logical_qubits,
        "circuit_depth": p.need.circuit_depth,
        "two_qubit_gates": p.need.two_qubit_gates,
        "shots": p.need.shots,
        "circuit_executions": p.need.circuit_executions,
        "estimated_cost_usd": round(p.need.est_cost_usd, 4),
        "estimated_runtime_s": round(p.need.est_runtime_s, 2),
        "notes": p.need.notes,
        "fallbacks": [f"{s.algorithm} on {s.backend.id}" for s in plan.fallbacks],
    }
    return Solution(
        goal=spec.raw_goal,
        answer=answer,
        summary=(
            f"Dry run: would execute {p.algorithm} on {p.backend.name} "
            f"({f.num_vars} variables, {p.need.shots} shots), "
            f"estimated ${p.need.est_cost_usd:,.2f} and {p.need.est_runtime_s:.1f}s. "
            f"Reason: {p.reason}"
        ),
        feasible=True,
        confidence=0.0,
        plan=plan,
        spec=spec,
        trace=trace,
    )


def explain(goal: str, data: dict | None = None, *, policy: Policy | None = None,
            registry: Registry | None = None, use_llm: str = "auto") -> str:
    """Produce the full decision report without executing anything."""
    pol = policy or Policy()
    reg = registry or Registry()
    spec = parse(goal, data, use_llm=use_llm)
    lines = [
        f"Goal: {spec.raw_goal}",
        f"Read as: {spec.template or spec.problem_class.value} "
        f"({spec.objective.value}), confidence {spec.confidence:.2f}",
        f"Why: {spec.rationale}",
    ]
    if spec.assumptions:
        lines.append("Assumptions: " + "; ".join(spec.assumptions))
    if spec.missing_data:
        lines.append("Missing data:")
        lines += [f"  - {m}" for m in spec.missing_data]
        return "\n".join(lines)

    f = compile_problem(spec)
    lines.append(f"Formulation: {f.kind.value}, {f.num_vars} variables")
    for note in f.notes:
        lines.append(f"  - {note}")

    try:
        plan = build_plan(spec, f, reg, pol)
    except NoViableBackend as e:
        lines.append("")
        lines.append(e.explain())
        return "\n".join(lines)

    lines.append("")
    lines.append(f"Chosen: {plan.primary.algorithm} on {plan.primary.backend.id}")
    lines.append(f"  {plan.primary.reason}")
    lines.append("")
    lines.append("All candidates considered:")
    for bid, score, reason in plan.considered[:12]:
        lines.append(f"  {score:.3f}  {bid:34s} {reason}")
    if plan.rejected:
        lines.append("")
        lines.append("Rejected:")
        for bid, why in plan.rejected[:14]:
            lines.append(f"  {bid:34s} {why}")
        if len(plan.rejected) > 14:
            lines.append(f"  ... and {len(plan.rejected) - 14} more")
    return "\n".join(lines)
