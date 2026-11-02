"""Classical solvers: baselines and fallbacks.

These are first-class citizens, not an afterthought. Two reasons:

1. Honesty. A quantum result is only meaningful next to the best classical
   effort on the same problem. The platform always runs a baseline so it can
   tell the user "the quantum route matched/beat/lost to classical" instead of
   presenting a number with no reference point.
2. Coverage. For most problem sizes a user will bring today, simulated
   annealing is simply the right tool. The broker is allowed to say so.
"""

from __future__ import annotations

import time

import numpy as np

from ..formulations.qubo import qubo_energies
from ..models import RawResult
from ..sim.statevector import all_basis_arrays, array_to_bitstring

# Above this, enumerating 2**n assignments stops being viable.
EXACT_LIMIT = 24


def exact_solve(Q: np.ndarray, offset: float = 0.0) -> RawResult:
    """Brute-force the global optimum by enumerating every assignment.

    Exact, and therefore the ground truth used in tests and for small user
    problems where certainty is worth more than speed.
    """
    t0 = time.perf_counter()
    n = Q.shape[0]
    if n > EXACT_LIMIT:
        raise ValueError(f"exact solve needs n <= {EXACT_LIMIT}, got {n}")
    X = all_basis_arrays(n)
    E = qubo_energies(Q, X, offset)
    best = int(np.argmin(E))
    bits = array_to_bitstring(X[best])
    return RawResult(
        backend_id="local.exact",
        algorithm="exact_enumeration",
        best_bitstring=bits,
        best_energy=float(E[best]),
        counts={bits: 1},
        shots=1,
        converged=True,
        wall_time_s=time.perf_counter() - t0,
        meta={"evaluated": int(2**n), "optimal": True},
    )


def simulated_annealing(
    Q: np.ndarray,
    offset: float = 0.0,
    *,
    reads: int = 24,
    sweeps: int = 1200,
    seed: int | None = None,
) -> RawResult:
    """Metropolis simulated annealing with single-bit flips.

    Uses an incremental delta-energy evaluation: flipping bit i changes the
    energy by a quantity computable from row i alone, so a sweep is O(n^2)
    rather than O(n^3). Geometric temperature schedule from an estimate of the
    typical energy scale.
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    n = Q.shape[0]
    Qs = (Q + Q.T) / 2.0
    diag = np.diag(Qs).copy()
    # Energy scale sets the starting temperature; too cold and nothing moves.
    scale = float(np.abs(Qs).sum(axis=1).mean()) or 1.0
    t_hot, t_cold = scale, scale * 1e-3
    best_x: np.ndarray | None = None
    best_e = np.inf
    counts: dict[str, int] = {}

    for _ in range(reads):
        x = rng.integers(0, 2, size=n).astype(np.float64)
        # delta_i = energy(flip i) - energy(x)
        #         = s_i * (2 * (Qs[i] @ x - Qs[i,i]*x_i) + Qs[i,i]),  s_i = 1-2x_i
        field = Qs @ x
        e = float(x @ Qs @ x + offset)
        for sweep in range(sweeps):
            temp = t_hot * (t_cold / t_hot) ** (sweep / max(1, sweeps - 1))
            order = rng.permutation(n)
            for i in order:
                xi = x[i]
                s = 1.0 - 2.0 * xi                      # +1 if flipping 0->1
                delta = s * (2.0 * (field[i] - diag[i] * xi) + diag[i])
                if delta <= 0 or rng.random() < np.exp(-delta / max(temp, 1e-12)):
                    x[i] = 1.0 - xi
                    field += Qs[:, i] * s               # keep field consistent
                    e += delta
        bits = array_to_bitstring(x.astype(np.int8))
        counts[bits] = counts.get(bits, 0) + 1
        if e < best_e:
            best_e, best_x = e, x.copy()

    bits = array_to_bitstring(best_x.astype(np.int8))
    return RawResult(
        backend_id="local.sa",
        algorithm="simulated_annealing",
        best_bitstring=bits,
        best_energy=float(best_e),
        counts=counts,
        shots=reads,
        iterations=reads * sweeps,
        converged=True,
        wall_time_s=time.perf_counter() - t0,
        meta={"reads": reads, "sweeps": sweeps},
    )


def tabu_search(
    Q: np.ndarray,
    offset: float = 0.0,
    *,
    iterations: int = 4000,
    tenure: int | None = None,
    restarts: int = 4,
    seed: int | None = None,
) -> RawResult:
    """Steepest-descent tabu search over single-bit flips.

    Complements annealing: tabu is better on rugged landscapes with large
    plateaus (assignment and one-hot-heavy encodings), annealing on smoother
    ones. The broker runs whichever fits the encoding, or both.
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    n = Q.shape[0]
    Qs = (Q + Q.T) / 2.0
    diag = np.diag(Qs).copy()
    tenure = tenure or max(3, n // 4)
    best_overall, best_e_overall = None, np.inf

    for _ in range(restarts):
        x = rng.integers(0, 2, size=n).astype(np.float64)
        field = Qs @ x
        e = float(x @ Qs @ x + offset)
        best_x, best_e = x.copy(), e
        tabu_until = np.zeros(n, dtype=int)
        for it in range(iterations // restarts):
            s = 1.0 - 2.0 * x
            deltas = s * (2.0 * (field - diag * x) + diag)
            allowed = tabu_until <= it
            # Aspiration: a tabu move is permitted if it beats the best known.
            allowed |= (e + deltas) < best_e - 1e-12
            if not allowed.any():
                break
            cand = np.where(allowed, deltas, np.inf)
            i = int(np.argmin(cand))
            si = 1.0 - 2.0 * x[i]
            x[i] = 1.0 - x[i]
            field += Qs[:, i] * si
            e += float(deltas[i])
            tabu_until[i] = it + tenure
            if e < best_e - 1e-12:
                best_e, best_x = e, x.copy()
        if best_e < best_e_overall:
            best_e_overall, best_overall = best_e, best_x

    bits = array_to_bitstring(best_overall.astype(np.int8))
    return RawResult(
        backend_id="local.tabu",
        algorithm="tabu_search",
        best_bitstring=bits,
        best_energy=float(best_e_overall),
        counts={bits: 1},
        shots=1,
        iterations=iterations,
        converged=True,
        wall_time_s=time.perf_counter() - t0,
        meta={"restarts": restarts, "tenure": tenure},
    )


def greedy_descent(Q: np.ndarray, offset: float = 0.0, *, seed: int | None = None) -> RawResult:
    """Single greedy descent to a local minimum -- the cheap sanity check."""
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    n = Q.shape[0]
    Qs = (Q + Q.T) / 2.0
    diag = np.diag(Qs).copy()
    x = rng.integers(0, 2, size=n).astype(np.float64)
    field = Qs @ x
    e = float(x @ Qs @ x + offset)
    improved = True
    steps = 0
    while improved:
        improved = False
        s = 1.0 - 2.0 * x
        deltas = s * (2.0 * (field - diag * x) + diag)
        i = int(np.argmin(deltas))
        if deltas[i] < -1e-12:
            si = 1.0 - 2.0 * x[i]
            x[i] = 1.0 - x[i]
            field += Qs[:, i] * si
            e += float(deltas[i])
            improved = True
            steps += 1
    bits = array_to_bitstring(x.astype(np.int8))
    return RawResult(
        backend_id="local.greedy",
        algorithm="greedy_descent",
        best_bitstring=bits,
        best_energy=float(e),
        counts={bits: 1},
        shots=1,
        iterations=steps,
        converged=True,
        wall_time_s=time.perf_counter() - t0,
    )


def best_classical(
    Q: np.ndarray,
    offset: float = 0.0,
    *,
    seed: int | None = None,
    time_budget_s: float = 5.0,
) -> RawResult:
    """Run the appropriate classical solver(s) and return the best result.

    This is the baseline every quantum run is measured against.
    """
    n = Q.shape[0]
    if n <= 20:
        return exact_solve(Q, offset)
    # Run both heuristics and keep the winner. They fail on different
    # landscapes -- annealing struggles with the rigid one-hot blocks produced
    # by TSP and assignment encodings, where tabu's steepest-descent moves
    # navigate better, and the reverse holds on smoother problems. Both
    # together cost well under a second at these sizes, so picking one up
    # front would trade real solution quality for no meaningful saving.
    results = [
        simulated_annealing(Q, offset, seed=seed, reads=16, sweeps=800),
        tabu_search(Q, offset, seed=seed),
    ]
    best = min(results, key=lambda r: r.best_energy)
    best.meta["considered"] = {r.algorithm: r.best_energy for r in results}
    best.meta["method_spread"] = max(r.best_energy for r in results) - best.best_energy
    return best
