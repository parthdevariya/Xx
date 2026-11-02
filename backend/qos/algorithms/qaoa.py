"""QAOA -- Quantum Approximate Optimization Algorithm.

Implements the standard ansatz: alternating cost and mixer layers applied to
a uniform superposition.

    |psi(g, b)> = prod_{l=1..p} [ RX(2*b_l) on all qubits . exp(-i g_l H_C) ] H^n |0>

Two implementation choices worth knowing about:

* The cost layer is applied as one diagonal phase multiply over all 2**n
  amplitudes (``phase_diag``) rather than as a circuit of RZ/RZZ gates. For a
  simulator these are mathematically identical, and the vectorized form is
  orders of magnitude faster on dense QUBOs. ``gate_counts`` still reports the
  RZ/RZZ counts a real device would need, so resource estimates stay honest.

* The classical objective defaults to CVaR (the mean of the best tail of
  measured energies) rather than the plain expectation value. For optimization
  problems the goal is a single good bitstring, not a low average, and CVaR
  consistently finds better optima at the same depth.
"""

from __future__ import annotations

import time

import numpy as np

from ..formulations.qubo import qubo_diagonal
from ..models import RawResult
from ..sim.statevector import StateVector


def gate_counts(Q: np.ndarray, layers: int) -> tuple[int, int, int]:
    """(depth, total gates, two-qubit gates) a real device would need.

    One RZ per nonzero diagonal term, one RZZ (= 2 CNOTs + RZ) per nonzero
    coupling, per layer, plus the mixer and the initial Hadamards.
    """
    n = Q.shape[0]
    Qs = (Q + Q.T) / 2.0
    lin = int(np.count_nonzero(np.abs(np.diag(Qs)) > 1e-12))
    quad = int(np.count_nonzero(np.abs(np.triu(Qs, 1)) > 1e-12))
    two_q = 2 * quad * layers
    gates = n + layers * (lin + 3 * quad + n)
    # Couplings sharing no qubits run in parallel; assume a constant-factor
    # packing of roughly n/2 per time slice.
    depth = 1 + layers * (1 + max(1, int(np.ceil(quad / max(1, n / 2)))) * 3 + 1)
    return depth, gates, two_q


def _apply_qaoa(
    n: int, diag: np.ndarray, gammas: np.ndarray, betas: np.ndarray
) -> StateVector:
    sv = StateVector(n).h_all()
    for g, b in zip(gammas, betas):
        sv.phase_diag(g * diag)          # exp(-i*g*H_C), H_C diagonal
        theta = 2.0 * b
        for q in range(n):
            sv.rx(q, theta)              # mixer: exp(-i*b*sum X_q)
    return sv


def _cvar(energies: np.ndarray, probs: np.ndarray, alpha: float) -> float:
    """Conditional Value at Risk: mean energy of the best alpha-tail.

    Sorts outcomes by energy and averages until alpha of the probability mass
    is accumulated, which focuses the optimizer on the low-energy tail.
    """
    if alpha >= 1.0:
        return float(np.dot(probs, energies))
    order = np.argsort(energies)
    e, p = energies[order], probs[order]
    cum = np.cumsum(p)
    k = int(np.searchsorted(cum, alpha)) + 1
    k = min(k, len(e))
    mass = cum[k - 1]
    if mass <= 0:
        return float(e[0])
    return float(np.dot(p[:k], e[:k]) / mass)


def run_qaoa(
    Q: np.ndarray,
    offset: float = 0.0,
    *,
    layers: int = 3,
    shots: int = 2048,
    maxiter: int = 150,
    restarts: int = 3,
    cvar_alpha: float = 0.2,
    seed: int | None = None,
    backend_id: str = "local.sv",
    sampler=None,
) -> RawResult:
    """Optimize QAOA parameters, then sample the final state.

    ``sampler``, when given, is a callable ``(n, diag, gammas, betas, shots)
    -> dict[bitstring, int]`` that executes the circuit on real hardware. The
    parameter optimization still runs on the simulator (cheap), and only the
    final sampling goes to the device -- the standard hybrid split that keeps
    QPU time bounded and predictable.
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    n = Q.shape[0]
    diag = qubo_diagonal(Q, offset)
    # Normalize the cost Hamiltonian so gamma lives on a comparable scale
    # across problems; otherwise the optimizer's step size is problem-dependent.
    scale = float(np.abs(diag).max()) or 1.0
    diag_n = diag / scale

    evals = {"count": 0}

    def objective(params: np.ndarray) -> float:
        evals["count"] += 1
        g, b = params[:layers], params[layers:]
        sv = _apply_qaoa(n, diag_n, g, b)
        p = sv.probabilities()
        return _cvar(diag_n, p, cvar_alpha)

    try:
        from scipy.optimize import minimize
        have_scipy = True
    except ImportError:          # pragma: no cover - scipy is a soft dependency
        have_scipy = False

    best_params, best_val = None, np.inf
    for r in range(restarts):
        # Linear ramp init (gamma increasing, beta decreasing) is a well-known
        # good starting point; later restarts are random.
        if r == 0:
            x0 = np.concatenate([
                np.linspace(0.1, 0.9, layers),
                np.linspace(0.9, 0.1, layers) * (np.pi / 4),
            ])
        else:
            x0 = rng.uniform(0, np.pi, size=2 * layers)
        if have_scipy:
            res = minimize(
                objective, x0, method="COBYLA",
                options={"maxiter": maxiter, "rhobeg": 0.4, "tol": 1e-6},
            )
            val, params = float(res.fun), np.asarray(res.x)
        else:
            val, params = _nelder_mead(objective, x0, maxiter)
        if val < best_val:
            best_val, best_params = val, params

    g, b = best_params[:layers], best_params[layers:]
    sv = _apply_qaoa(n, diag_n, g, b)

    if sampler is not None:
        counts = sampler(n, diag_n, g, b, shots)
    else:
        counts = sv.sample(shots, rng)

    # Pick the best measured bitstring by true energy. QAOA's value is that a
    # good solution appears in the samples, not that the mean is low.
    best_bits, best_e = None, np.inf
    for bits, c in counts.items():
        idx = sum((1 << q) for q, ch in enumerate(bits) if ch == "1")
        e = float(diag[idx])
        if e < best_e:
            best_e, best_bits = e, bits

    depth, gates, two_q = gate_counts(Q, layers)
    return RawResult(
        backend_id=backend_id,
        algorithm=f"qaoa_p{layers}",
        counts=counts,
        best_bitstring=best_bits,
        best_energy=best_e,
        expectation=float(np.dot(sv.probabilities(), diag)),
        shots=shots,
        iterations=evals["count"],
        converged=True,
        wall_time_s=time.perf_counter() - t0,
        meta={
            "layers": layers,
            "gammas": [float(v) for v in g],
            "betas": [float(v) for v in b],
            "cvar_alpha": cvar_alpha,
            "cvar_value": best_val * scale,
            "circuit_depth": depth,
            "gate_count": gates,
            "two_qubit_gates": two_q,
            "optimizer": "COBYLA" if have_scipy else "nelder-mead",
            "restarts": restarts,
            "energy_scale": scale,
        },
    )


def _nelder_mead(f, x0: np.ndarray, maxiter: int) -> tuple[float, np.ndarray]:
    """Minimal Nelder-Mead, used only if scipy is unavailable."""
    n = len(x0)
    step = 0.4
    simplex = [x0.copy()]
    for i in range(n):
        p = x0.copy()
        p[i] += step
        simplex.append(p)
    vals = [f(p) for p in simplex]
    for _ in range(maxiter):
        order = np.argsort(vals)
        simplex = [simplex[i] for i in order]
        vals = [vals[i] for i in order]
        centroid = np.mean(simplex[:-1], axis=0)
        worst = simplex[-1]
        refl = centroid + 1.0 * (centroid - worst)
        fr = f(refl)
        if fr < vals[0]:
            exp_ = centroid + 2.0 * (centroid - worst)
            fe = f(exp_)
            simplex[-1], vals[-1] = (exp_, fe) if fe < fr else (refl, fr)
        elif fr < vals[-2]:
            simplex[-1], vals[-1] = refl, fr
        else:
            con = centroid + 0.5 * (worst - centroid)
            fc = f(con)
            if fc < vals[-1]:
                simplex[-1], vals[-1] = con, fc
            else:
                for i in range(1, len(simplex)):
                    simplex[i] = simplex[0] + 0.5 * (simplex[i] - simplex[0])
                    vals[i] = f(simplex[i])
    i = int(np.argmin(vals))
    return float(vals[i]), simplex[i]
