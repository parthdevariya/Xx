"""Result interpretation: bitstrings -> domain answers with an honest verdict.

The final stage, and the one that decides whether the platform is trustworthy.
Three jobs:

1. **Decode** the winning bitstring into the user's own terms (a tour, a
   basket of assets, a shift roster) rather than a binary vector.
2. **Verify** feasibility against the original constraints. A penalized QUBO
   can return a low-energy assignment that violates a constraint; reporting
   that as the answer would be wrong. Infeasible results are labelled, and the
   best *feasible* sample is preferred over a lower-energy infeasible one.
3. **Compare** against the classical baseline and state the verdict plainly --
   including "classical did better", which is frequently the truth today and
   is exactly what a user needs to know before spending on hardware.
"""

from __future__ import annotations

import numpy as np

from ..formulations.library import TEMPLATES
from ..formulations.qubo import qubo_energy
from ..models import (
    ExecutionPlan,
    Formulation,
    FormulationKind,
    ProblemSpec,
    RawResult,
    Solution,
)


def _to_index(bits: str) -> int:
    """Bitstring (position q == qubit q) -> integer basis index."""
    return sum(1 << q for q, ch in enumerate(bits) if ch == "1")


def best_feasible_sample(
    raw: RawResult, spec: ProblemSpec, f: Formulation
) -> tuple[str | None, bool, list[str]]:
    """Pick the best sample that satisfies the constraints.

    Scans measured outcomes in increasing energy order and returns the first
    feasible one. This matters: a QAOA run often produces the true optimum
    somewhere in its samples even when the single lowest-energy bitstring
    violates a one-hot constraint.
    """
    template = TEMPLATES.get(spec.template or "")
    if not raw.counts:
        return raw.best_bitstring, True, []

    # Oracle problems have no energy function to rank samples by -- the
    # predicate is the only arbiter. The algorithm already checked its own
    # answer, so trust it, and fall back to scanning the samples if it has
    # none. Ranking these by a stand-in energy of zero would return an
    # arbitrary sample.
    if f.kind is FormulationKind.ORACLE:
        predicate = f.predicate
        if raw.best_bitstring and (predicate is None or predicate(_to_index(raw.best_bitstring))):
            return raw.best_bitstring, True, []
        if predicate is not None:
            for bits, _count in sorted(raw.counts.items(), key=lambda kv: -kv[1]):
                if predicate(_to_index(bits)):
                    return bits, True, []
            return raw.best_bitstring, False, [
                "no sampled candidate satisfied the predicate"
            ]
        return raw.best_bitstring, True, []

    if f.Q is None:
        return raw.best_bitstring, True, []

    scored: list[tuple[float, str]] = []
    Q = np.asarray(f.Q)
    for bits in raw.counts:
        x = np.array([1.0 if c == "1" else 0.0 for c in bits[: f.num_vars]])
        if len(x) < f.num_vars:
            x = np.concatenate([x, np.zeros(f.num_vars - len(x))])
        scored.append((qubo_energy(Q, x, f.offset), bits))
    scored.sort(key=lambda t: t[0])

    if template is None:
        return scored[0][1], True, []

    first_violations: list[str] = []
    for _energy, bits in scored:
        ans = template.decode(bits, spec.data)
        check = template.verify(ans, spec.data)
        if check.feasible:
            return bits, True, []
        if not first_violations:
            first_violations = check.violations
    # Nothing feasible was sampled; return the lowest-energy attempt and say so.
    return scored[0][1], False, first_violations


def interpret(
    spec: ProblemSpec,
    f: Formulation,
    raw: RawResult,
    plan: ExecutionPlan | None = None,
    baseline: RawResult | None = None,
    trace: list[str] | None = None,
) -> Solution:
    """Build the final Solution from a raw backend result."""
    template = TEMPLATES.get(spec.template or "")
    sense = template.sense if template else "min"

    q_ans, q_obj, q_feas, q_viol = _evaluate(raw, spec, f, template)

    # ------------------------------------------------- baseline comparison
    baseline_value = None
    advantage = "none"
    c_ans = c_feas = None
    c_viol: list[str] = []
    if baseline is not None:
        c_ans, c_obj, c_feas, c_viol = _evaluate(baseline, spec, f, template)
        baseline_value = c_obj if c_feas else None
        if baseline_value is not None and q_obj is not None and q_feas:
            advantage = _compare(q_obj, baseline_value, sense)

    # The platform returns the best answer it found, not merely the one from
    # the route it chose. A user who is told "classical did better" and then
    # handed the worse tour has been given a worse answer than the platform
    # actually has in hand.
    answer, objective_value, feasible, violations = q_ans, q_obj, q_feas, q_viol
    answer_source = "primary"
    if c_ans is not None and _prefer_baseline(q_obj, q_feas, c_obj, c_feas, sense):
        answer, objective_value, feasible, violations = c_ans, c_obj, c_feas, c_viol
        answer_source = "baseline"

    confidence = _confidence(raw, feasible, advantage, baseline)
    summary = _summarize(
        spec, raw, plan, f, objective_value, sense,
        feasible, violations, baseline_value, advantage, baseline,
        answer_source, q_obj,
    )

    return Solution(
        goal=spec.raw_goal,
        answer=answer,
        summary=summary,
        objective_value=objective_value,
        feasible=feasible,
        violations=violations,
        confidence=confidence,
        baseline_value=baseline_value,
        quantum_advantage=advantage,
        raw=raw,
        plan=plan,
        spec=spec,
        trace=list(trace or []) + [f"returned answer came from the {answer_source} route"],
    )


def _evaluate(
    result: RawResult, spec: ProblemSpec, f: Formulation, template
) -> tuple[object, float | None, bool, list[str]]:
    """Decode a raw result into (answer, true objective, feasible, violations)."""
    bits, feasible, violations = best_feasible_sample(result, spec, f)
    if template and bits:
        ans = template.decode(bits, spec.data)
        return ans, template.objective(ans, spec.data), feasible, violations
    return (
        {"bitstring": bits, "energy": result.best_energy},
        result.best_energy,
        feasible,
        violations,
    )


def _compare(a: float, b: float, sense: str) -> str:
    """How ``a`` fares against ``b`` under the objective's sense."""
    if sense == "max":
        if a > b + 1e-9:
            return "better"
        return "worse" if a < b - 1e-9 else "parity"
    if a < b - 1e-9:
        return "better"
    return "worse" if a > b + 1e-9 else "parity"


def _prefer_baseline(
    q_obj: float | None, q_feas: bool, c_obj: float | None, c_feas: bool, sense: str
) -> bool:
    """Should the baseline's answer be the one returned?

    Feasibility dominates: a feasible answer always beats an infeasible one,
    whatever the objective says, because an infeasible answer is unusable.
    """
    if not c_feas:
        return False
    if not q_feas:
        return True
    if q_obj is None:
        return c_obj is not None
    if c_obj is None:
        return False
    return _compare(c_obj, q_obj, sense) == "better"


def _confidence(
    raw: RawResult, feasible: bool, advantage: str, baseline: RawResult | None
) -> float:
    """How much the platform trusts this answer, in [0, 1]."""
    if raw.meta.get("optimal"):
        return 1.0                      # exact enumeration: certified
    c = 0.5
    if feasible:
        c += 0.2
    else:
        c -= 0.3
    if advantage in ("better", "parity"):
        c += 0.2                        # independently corroborated
    elif advantage == "worse":
        c -= 0.1
    if baseline is not None and baseline.meta.get("optimal") and advantage == "parity":
        return 1.0                      # matched a certified optimum
    if raw.counts:
        # A result that dominates the sample distribution is more credible than
        # one that appeared once.
        total = sum(raw.counts.values())
        top = max(raw.counts.values())
        c += 0.1 * min(1.0, top / max(1, total) * 4)
    # Certainty is reserved for results that are actually certified. Two
    # heuristics agreeing is strong evidence, not proof -- they can share a
    # local optimum.
    return round(max(0.0, min(0.95, c)), 3)


def _summarize(
    spec, raw, plan, f, objective_value, sense,
    feasible, violations, baseline_value, advantage, baseline,
    answer_source="primary", primary_value=None,
) -> str:
    lines: list[str] = []
    backend = plan.primary.backend.name if plan else raw.backend_id
    lines.append(
        f"Solved as {spec.template or spec.problem_class.value} "
        f"({f.num_vars} binary variables) using {raw.algorithm} on {backend}."
    )

    if objective_value is not None:
        word = "maximized" if sense == "max" else "minimized"
        lines.append(f"Best {word} objective: {objective_value:,.4g}.")

    if not feasible:
        lines.append(
            "WARNING: no sampled solution satisfied all constraints. "
            + " ".join(violations)
            + " Treat this result as a draft, not an answer."
        )

    if baseline_value is not None:
        # The chosen route is often itself classical -- the broker picks exact
        # enumeration whenever it can certify the optimum -- so calling the
        # comparison "quantum vs classical" would misdescribe what happened.
        quantum_route = (
            plan is not None
            and plan.primary.backend.modality.value in ("gate_qpu", "gate_simulator", "annealer")
        )
        if quantum_route:
            verdict = {
                "better": "the quantum route beat the classical baseline",
                "worse": "the classical baseline beat the quantum route",
                "parity": "quantum and classical reached the same objective",
                "none": "no comparison available",
            }[advantage]
        else:
            verdict = {
                "better": "the chosen route beat the cross-check",
                "worse": "the cross-check found a better answer",
                "parity": "an independent cross-check agreed",
                "none": "no comparison available",
            }[advantage]
        extra = ""
        if baseline is not None and baseline.meta.get("optimal"):
            extra = " (the baseline is a certified global optimum)"
        lines.append(
            f"Classical baseline ({baseline.algorithm if baseline else 'n/a'}) "
            f"reached {baseline_value:,.4g} -- {verdict}{extra}."
        )
        if answer_source == "baseline":
            got = f"{primary_value:,.4g}" if primary_value is not None else "no feasible result"
            lines.append(
                f"The answer returned above is the baseline's, since the "
                f"{raw.algorithm} route only reached {got}."
            )

    if raw.cost_usd > 0:
        lines.append(f"Cost: ${raw.cost_usd:,.2f}. Wall time: {raw.wall_time_s:.1f}s.")
    else:
        lines.append(f"Cost: free. Wall time: {raw.wall_time_s:.2f}s.")

    if spec.assumptions:
        lines.append("Assumptions made: " + "; ".join(spec.assumptions) + ".")

    return " ".join(lines)


def format_answer(sol: Solution) -> str:
    """Render the decoded answer as readable lines for a terminal."""
    a = sol.answer
    if not isinstance(a, dict):
        return str(a)
    out: list[str] = []
    skip = {"assignment", "matrix", "placement", "colors"}
    for k, v in a.items():
        if k in skip:
            continue
        if isinstance(v, list) and len(v) > 12:
            out.append(f"  {k}: {v[:12]} ... ({len(v)} items)")
        elif isinstance(v, float):
            out.append(f"  {k}: {v:,.6g}")
        else:
            out.append(f"  {k}: {v}")
    return "\n".join(out)
