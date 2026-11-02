"""The broker: picks the backend and algorithm, and explains why.

This is the component that delivers the platform's core promise -- the user
states a goal, and the system decides where to run it. The decision is a
multi-objective trade-off between expected answer quality, money and latency,
resolved by explicit scoring rather than a hardcoded preference order.

Two principles the implementation holds to:

* **Hard gates before scoring.** A candidate that cannot produce a meaningful
  answer (too few qubits, fidelity floor, over budget, no credentials) is
  rejected with a stated reason, not merely down-weighted. Users are told what
  was rejected and why.

* **Quantum is not the default.** If exact enumeration will certify the global
  optimum in 200 ms, that wins, and the platform says so. Routing a 12-variable
  problem to a QPU to look impressive would be a disservice. The broker
  recommends quantum resources when they are genuinely the best available
  option for the problem in front of it.
"""

from __future__ import annotations

from ..models import (
    BackendCapability,
    ExecutionPlan,
    Formulation,
    Modality,
    PlanStep,
    Policy,
    ProblemSpec,
    ResourceNeed,
)
from ..providers.registry import Registry
from .estimator import estimate

# Below this expected fidelity a gate QPU returns noise rather than signal.
FIDELITY_FLOOR = 0.02

# Weight profiles: (quality, cost, latency). Must sum to 1 within a profile.
PROFILES = {
    "balanced": (0.55, 0.25, 0.20),
    "accuracy": (0.85, 0.05, 0.10),
    "cheap": (0.25, 0.65, 0.10),
    "fast": (0.30, 0.10, 0.60),
}


def quality_score(
    backend: BackendCapability, need: ResourceNeed, f: Formulation
) -> tuple[float, str]:
    """Expected answer quality in [0, 1], with a one-line justification."""
    algo = need.algorithm

    if algo == "exact_enumeration":
        return 1.0, "certified global optimum by exhaustive enumeration"

    if algo == "quantum_annealing":
        if backend.id.startswith("dwave.hybrid"):
            return 0.82, "hybrid solver: production-grade quality at large scale"
        chain = 1.0
        for note in need.notes:
            if "chain length" in note:
                try:
                    chain = float(note.split("~")[1])
                except (IndexError, ValueError):
                    pass
        # Chain breaks are the dominant quality loss on annealers.
        penalty = min(0.5, max(0.0, (chain - 1.0) * 0.12))
        return 0.70 - penalty, (
            f"native QUBO annealing, embedding chain ~{chain:.1f}"
            + (" (chain breaks will cost quality)" if chain > 3 else "")
        )

    fid = _fidelity_from(need)

    if algo.startswith("qaoa"):
        layers = int(algo.split("_p")[1])
        # More layers approach the optimum in theory, but on noisy hardware the
        # fidelity loss outruns the gain. Multiplying the two captures that.
        depth_quality = 1.0 - 0.75 ** layers      # p=1: 0.25, p=3: 0.58, p=6: 0.82
        score = 0.30 + 0.55 * depth_quality * fid
        detail = f"QAOA p={layers}"
        if fid < 0.5:
            detail += f", degraded by noise (fidelity {fid:.2g})"
        return min(0.95, score), detail

    if algo.startswith("vqe"):
        layers = int(algo.split("_l")[1])
        return min(0.9, 0.35 + 0.1 * layers) * max(fid, 0.1), f"VQE {layers} ansatz layers"

    if algo == "grover":
        return 0.5 + 0.45 * fid, "Grover amplitude amplification"

    if algo in ("simulated_annealing", "tabu_search"):
        # One-hot encodings (TSP, assignment, coloring) produce rigid feasible
        # regions where single-bit annealing moves are almost always rejected,
        # while tabu's steepest-descent step traverses them. Penalty terms in
        # the formulation are the signal that this is such an encoding.
        one_hot = bool(f.penalties)
        if one_hot and algo == "tabu_search":
            return 0.74, "tabu search, which handles the one-hot structure of this encoding well"
        if one_hot and algo == "simulated_annealing":
            return 0.60, "simulated annealing, weaker on the rigid one-hot structure here"
        return 0.68, f"classical heuristic ({algo}), strong in practice but no guarantee"

    return 0.5, algo


def _fidelity_from(need: ResourceNeed) -> float:
    for note in need.notes:
        if note.startswith("expected_fidelity="):
            try:
                return float(note.split("=")[1])
            except ValueError:
                return 1.0
    return 1.0


def _normalize(values: list[float], invert: bool) -> list[float]:
    """Map values to [0, 1]; ``invert`` makes smaller better."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [1.0 if invert else 0.5] * len(values)
    out = [(v - lo) / (hi - lo) for v in values]
    return [1.0 - v for v in out] if invert else out


def plan(
    spec: ProblemSpec,
    f: Formulation,
    registry: Registry,
    policy: Policy | None = None,
) -> ExecutionPlan:
    """Build the execution plan: primary route plus ranked fallbacks."""
    pol = policy or Policy()
    rejected: list[tuple[str, str]] = []
    candidates: list[tuple[BackendCapability, ResourceNeed, float, str]] = []

    for backend in registry.capabilities():
        # ---------------------------------------------------- hard gates
        if pol.force_backend and backend.id != pol.force_backend:
            continue
        if not pol.vendor_allowed(backend.vendor):
            rejected.append((backend.id, "vendor excluded by policy"))
            continue
        if not backend.credentialed:
            rejected.append((
                backend.id,
                backend.unavailable_reason or "no credentials configured for this vendor",
            ))
            continue
        if not backend.available:
            rejected.append((
                backend.id,
                backend.unavailable_reason or "device offline or unreachable",
            ))
            continue
        if not backend.can_run(f):
            if f.num_vars > backend.max_qubits:
                rejected.append((
                    backend.id,
                    f"needs {f.num_vars} qubits, device has {backend.max_qubits}",
                ))
            else:
                rejected.append((backend.id, f"cannot execute {f.kind.value} formulations"))
            continue

        needs = estimate(spec, f, backend, pol)
        if not needs:
            rejected.append((backend.id, "no viable algorithm for this problem on this device"))
            continue

        for need in needs:
            if pol.force_algorithm and not need.algorithm.startswith(pol.force_algorithm):
                continue
            # Authorization is checked before the budget: a user who has not
            # opted into paid resources at all needs to hear that, not that
            # their (default, zero) budget was exceeded.
            if need.est_cost_usd > 0 and not pol.allow_hardware:
                rejected.append((
                    f"{backend.id}:{need.algorithm}",
                    f"costs ${need.est_cost_usd:.2f}, but hardware spending is not "
                    f"enabled (pass --allow-hardware --budget N)",
                ))
                continue
            if need.est_cost_usd > pol.max_cost_usd + 1e-9:
                rejected.append((
                    f"{backend.id}:{need.algorithm}",
                    f"estimated ${need.est_cost_usd:.2f} exceeds budget ${pol.max_cost_usd:.2f}",
                ))
                continue
            if need.est_runtime_s > pol.max_wait_s:
                rejected.append((
                    f"{backend.id}:{need.algorithm}",
                    f"estimated {need.est_runtime_s:.0f}s exceeds max wait {pol.max_wait_s:.0f}s",
                ))
                continue
            fid = _fidelity_from(need)
            if backend.modality is Modality.GATE_QPU and fid < FIDELITY_FLOOR:
                rejected.append((
                    f"{backend.id}:{need.algorithm}",
                    f"expected fidelity {fid:.2g} below floor {FIDELITY_FLOOR}; "
                    f"{need.two_qubit_gates} two-qubit gates is too deep for this device",
                ))
                continue

            q, why = quality_score(backend, need, f)
            candidates.append((backend, need, q, why))

    if not candidates:
        pinned = ""
        if pol.force_backend or pol.force_algorithm:
            pinned = (
                f" (pinned to backend={pol.force_backend or 'any'}, "
                f"algorithm={pol.force_algorithm or 'any'})"
            )
        raise NoViableBackend(
            f"no backend can run this problem under the current policy{pinned}", rejected
        )

    # ------------------------------------------------------------ scoring
    w_q, w_c, w_l = PROFILES.get(pol.priority, PROFILES["balanced"])
    costs = [c[1].est_cost_usd for c in candidates]
    times = [c[1].est_runtime_s for c in candidates]
    cost_s = _normalize(costs, invert=True)
    time_s = _normalize(times, invert=True)

    scored: list[PlanStep] = []
    for i, (backend, need, q, why) in enumerate(candidates):
        score = w_q * q + w_c * cost_s[i] + w_l * time_s[i]
        reason = (
            f"{why}; quality {q:.2f}, "
            f"est {_fmt_cost(need.est_cost_usd)}, est {_fmt_time(need.est_runtime_s)}"
        )
        scored.append(PlanStep(need.algorithm, backend, need, score, reason))

    scored.sort(key=lambda s: -s.score)
    considered = [(f"{s.backend.id}:{s.algorithm}", s.score, s.reason) for s in scored]

    # Fallbacks: best alternative per distinct backend, so a failure moves to
    # genuinely different hardware rather than retrying the same device.
    fallbacks: list[PlanStep] = []
    seen = {scored[0].backend.id}
    for s in scored[1:]:
        if s.backend.id not in seen:
            fallbacks.append(s)
            seen.add(s.backend.id)
        if len(fallbacks) >= 3:
            break

    return ExecutionPlan(
        primary=scored[0],
        fallbacks=fallbacks,
        considered=considered,
        rejected=rejected,
    )


def _fmt_cost(usd: float) -> str:
    return "free" if usd <= 0 else f"${usd:,.2f}"


def _fmt_time(s: float) -> str:
    if s < 1:
        return f"{s * 1000:.0f}ms"
    if s < 90:
        return f"{s:.1f}s"
    return f"{s / 60:.1f}min"


class NoViableBackend(RuntimeError):
    """Raised when the policy admits no backend at all."""

    def __init__(self, message: str, rejected: list[tuple[str, str]]) -> None:
        super().__init__(message)
        self.rejected = rejected

    def explain(self) -> str:
        lines = [str(self), "", "Rejected candidates:"]
        for bid, why in self.rejected[:20]:
            lines.append(f"  - {bid}: {why}")
        if len(self.rejected) > 20:
            lines.append(f"  ... and {len(self.rejected) - 20} more")
        return "\n".join(lines)
