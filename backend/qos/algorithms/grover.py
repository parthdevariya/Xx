"""Grover search and amplitude amplification.

Grover finds a marked item in an unstructured space of size N in O(sqrt(N))
oracle calls instead of O(N). The honest caveat, which the platform surfaces
to users rather than hiding: the speedup is in *oracle calls*, and building
the oracle requires knowing the predicate. If the predicate is cheap to
evaluate classically, a classical scan of N items is usually faster in wall
time than simulating sqrt(N) Grover iterations. Grover pays off on real
hardware for large spaces, or when the oracle encodes something genuinely
expensive.

Implemented here:

* ``run_grover``        -- known number of solutions, optimal iteration count
* ``run_grover_unknown``-- unknown solution count, exponential schedule
* ``optimal_iterations``-- the pi/4 * sqrt(N/M) rule
"""

from __future__ import annotations

import time

import numpy as np

from ..models import RawResult
from ..sim.statevector import StateVector


def optimal_iterations(n_qubits: int, n_solutions: int) -> int:
    """Iterations maximizing success probability: round(pi/4 * sqrt(N/M)).

    Overshooting is a real failure mode -- amplitude rotates past the target
    and success probability falls again -- so this is not "more is better".
    """
    N = 1 << n_qubits
    m = max(1, int(n_solutions))
    if m >= N:
        return 0
    theta = np.arcsin(np.sqrt(m / N))
    return max(0, int(round((np.pi / 2 - theta) / (2 * theta))))


def _diffuser(sv: StateVector) -> None:
    """Grover diffusion operator: 2|s><s| - I, as H^n (2|0><0| - I) H^n."""
    sv.h_all()
    sv.phase_oracle([0])      # flip phase of |0...0>
    sv.h_all()


def marked_states(predicate, n_qubits: int) -> np.ndarray:
    """Evaluate the predicate over the whole space to find marked indices.

    Enumerating here is what makes the simulator able to apply the oracle as
    one vectorized phase flip. On real hardware the predicate would instead be
    compiled into a reversible circuit; this is the simulator's shortcut, and
    the resource estimate accounts for the real oracle cost separately.
    """
    idx = np.arange(1 << n_qubits, dtype=np.int64)
    mask = np.fromiter((bool(predicate(int(i))) for i in idx), dtype=bool, count=len(idx))
    return idx[mask]


def run_grover(
    predicate,
    n_qubits: int,
    *,
    shots: int = 1024,
    iterations: int | None = None,
    seed: int | None = None,
    backend_id: str = "local.sv",
) -> RawResult:
    """Amplify states satisfying ``predicate`` and sample."""
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    marked = marked_states(predicate, n_qubits)
    N = 1 << n_qubits
    m = len(marked)

    if m == 0:
        return RawResult(
            backend_id=backend_id, algorithm="grover", shots=0,
            error="no state satisfies the predicate; the search space contains no solution",
            wall_time_s=time.perf_counter() - t0,
            meta={"search_space": N, "solutions": 0},
        )

    k = optimal_iterations(n_qubits, m) if iterations is None else int(iterations)
    sv = StateVector(n_qubits).h_all()
    for _ in range(k):
        sv.phase_oracle(marked)
        _diffuser(sv)

    counts = sv.sample(shots, rng)
    p = sv.probabilities()
    success = float(p[marked].sum())
    # Report the most-sampled outcome that actually satisfies the predicate.
    best = None
    for bits, _c in sorted(counts.items(), key=lambda kv: -kv[1]):
        idx = sum((1 << q) for q, ch in enumerate(bits) if ch == "1")
        if predicate(idx):
            best = bits
            break

    return RawResult(
        backend_id=backend_id,
        algorithm="grover",
        counts=counts,
        best_bitstring=best,
        expectation=success,
        shots=shots,
        iterations=k,
        converged=success > 0.5,
        wall_time_s=time.perf_counter() - t0,
        meta={
            "search_space": N,
            "solutions": m,
            "success_probability": success,
            "oracle_calls": k,
            "classical_calls_expected": N / (m + 1),
            "speedup_vs_classical_oracle_calls": (N / (m + 1)) / max(1, k),
            # A real device needs a reversible circuit for the predicate; the
            # 2(n-1) figure is the Toffoli cost of the multi-controlled Z in
            # the diffuser alone, excluding predicate compilation.
            "two_qubit_gates_min": k * 2 * max(1, n_qubits - 1),
        },
    )


def run_grover_unknown(
    predicate,
    n_qubits: int,
    *,
    shots: int = 1024,
    seed: int | None = None,
    max_rounds: int = 12,
    backend_id: str = "local.sv",
) -> RawResult:
    """Grover when the number of solutions is unknown (BBHT schedule).

    Tries iteration counts drawn from a geometrically growing window until a
    measured outcome satisfies the predicate. Expected total oracle calls stay
    O(sqrt(N/M)) without knowing M in advance.
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    marked = marked_states(predicate, n_qubits)
    if len(marked) == 0:
        return RawResult(
            backend_id=backend_id, algorithm="grover_bbht", shots=0,
            error="no state satisfies the predicate",
            wall_time_s=time.perf_counter() - t0,
        )
    N = 1 << n_qubits
    total_calls = 0
    lam = 6.0 / 5.0
    m = 1.0
    for _round in range(max_rounds):
        k = int(rng.integers(0, max(1, int(m))))
        sv = StateVector(n_qubits).h_all()
        for _ in range(k):
            sv.phase_oracle(marked)
            _diffuser(sv)
        total_calls += k
        idx = int(sv.sample_indices(1, rng)[0])
        if predicate(idx):
            counts = sv.sample(shots, rng)
            p = sv.probabilities()
            return RawResult(
                backend_id=backend_id,
                algorithm="grover_bbht",
                counts=counts,
                best_bitstring=sv.bitstring(idx),
                expectation=float(p[marked].sum()),
                shots=shots,
                iterations=total_calls,
                converged=True,
                wall_time_s=time.perf_counter() - t0,
                meta={"search_space": N, "rounds": _round + 1, "oracle_calls": total_calls},
            )
        m = min(np.sqrt(N), lam * m)
    return RawResult(
        backend_id=backend_id, algorithm="grover_bbht", shots=0,
        error=f"no solution sampled in {max_rounds} rounds",
        iterations=total_calls, wall_time_s=time.perf_counter() - t0,
    )


def classical_scan(predicate, n_qubits: int) -> RawResult:
    """Linear scan baseline, for the honest comparison."""
    t0 = time.perf_counter()
    N = 1 << n_qubits
    for i in range(N):
        if predicate(i):
            bits = "".join("1" if (i >> q) & 1 else "0" for q in range(n_qubits))
            return RawResult(
                backend_id="local.classical", algorithm="linear_scan",
                best_bitstring=bits, counts={bits: 1}, shots=1,
                iterations=i + 1, converged=True,
                wall_time_s=time.perf_counter() - t0,
                meta={"evaluations": i + 1, "search_space": N},
            )
    return RawResult(
        backend_id="local.classical", algorithm="linear_scan",
        error="no solution exists", iterations=N,
        wall_time_s=time.perf_counter() - t0,
    )
