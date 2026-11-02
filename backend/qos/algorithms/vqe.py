"""VQE -- Variational Quantum Eigensolver for ground-state energies.

Given a Hamiltonian as a weighted sum of Pauli strings,

    H = sum_k c_k * P_k,     P_k in {I, X, Y, Z}^n

VQE minimizes <psi(t)|H|psi(t)> over a parameterized ansatz. This is the
flagship near-term application (molecular energies, lattice models, spin
systems), and unlike QAOA it is not restricted to diagonal Hamiltonians.

The ansatz here is hardware-efficient: alternating RY rotation layers and a
linear CX entangling ladder. It makes no chemistry-specific assumptions, which
is the right default when the platform receives an arbitrary Hamiltonian. A
UCCSD-style chemistry ansatz needs orbital structure the platform does not
have unless the user supplies a molecule through a chemistry package.
"""

from __future__ import annotations

import time

import numpy as np

from ..models import RawResult
from ..sim.statevector import StateVector


def apply_pauli_string(sv: StateVector, pauli: str) -> StateVector:
    """Apply a Pauli string in place. ``pauli[q]`` acts on qubit q."""
    for q, ch in enumerate(pauli):
        if ch == "I":
            continue
        if ch == "X":
            sv.x(q)
        elif ch == "Y":
            sv.y(q)
        elif ch == "Z":
            sv.z(q)
        else:
            raise ValueError(f"bad Pauli character {ch!r}")
    return sv


def pauli_expectation(sv: StateVector, terms: list[tuple[float, str]]) -> float:
    """<psi|H|psi> for H given as (coeff, pauli_string) terms.

    Computed exactly on the simulator via inner products. On hardware each
    term becomes a separate measurement basis, which is why ``term_count`` is
    reported in resource estimates -- it multiplies the shot budget.
    """
    total = 0.0
    psi = sv.state
    for coeff, pauli in terms:
        if set(pauli) == {"I"}:
            total += coeff
            continue
        work = sv.copy()
        apply_pauli_string(work, pauli)
        total += coeff * float(np.real(np.vdot(psi, work.state)))
    return total


def hardware_efficient_ansatz(n: int, params: np.ndarray, layers: int) -> StateVector:
    """RY rotations + linear CX ladder, repeated ``layers`` times.

    Parameter count is n * (layers + 1): one RY per qubit per layer plus a
    final rotation layer.
    """
    sv = StateVector(n)
    p = 0
    for q in range(n):
        sv.ry(q, float(params[p])); p += 1
    for _ in range(layers):
        for q in range(n - 1):
            sv.cx(q, q + 1)
        for q in range(n):
            sv.ry(q, float(params[p])); p += 1
    return sv


def ansatz_param_count(n: int, layers: int) -> int:
    return n * (layers + 1)


def ansatz_resources(n: int, layers: int) -> tuple[int, int, int]:
    """(depth, gates, two-qubit gates) for the ansatz on real hardware."""
    two_q = layers * (n - 1)
    gates = n * (layers + 1) + two_q
    depth = 1 + layers * (n - 1 + 1)   # CX ladder is sequential on a line
    return depth, gates, two_q


def run_vqe(
    terms: list[tuple[float, str]],
    *,
    layers: int = 2,
    maxiter: int = 400,
    restarts: int = 3,
    seed: int | None = None,
    backend_id: str = "local.sv",
) -> RawResult:
    """Minimize the Hamiltonian expectation over the ansatz parameters."""
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    n = len(terms[0][1])
    if any(len(p) != n for _c, p in terms):
        raise ValueError("all Pauli strings must have the same length")
    npar = ansatz_param_count(n, layers)
    evals = {"count": 0}

    def objective(x: np.ndarray) -> float:
        evals["count"] += 1
        sv = hardware_efficient_ansatz(n, x, layers)
        return pauli_expectation(sv, terms)

    try:
        from scipy.optimize import minimize
        have_scipy = True
    except ImportError:          # pragma: no cover
        have_scipy = False

    best_val, best_x = np.inf, None
    for r in range(restarts):
        # Small random init avoids the barren-plateau-adjacent flat region at
        # the all-zero point while staying near the easy-to-optimize regime.
        x0 = rng.normal(0.0, 0.3, size=npar) if r else np.full(npar, 0.1)
        if have_scipy:
            res = minimize(objective, x0, method="COBYLA", options={"maxiter": maxiter})
            val, x = float(res.fun), np.asarray(res.x)
        else:
            from .qaoa import _nelder_mead
            val, x = _nelder_mead(objective, x0, maxiter)
        if val < best_val:
            best_val, best_x = val, x

    sv = hardware_efficient_ansatz(n, best_x, layers)
    depth, gates, two_q = ansatz_resources(n, layers)
    counts = sv.sample(1024, rng)
    return RawResult(
        backend_id=backend_id,
        algorithm=f"vqe_l{layers}",
        counts=counts,
        best_energy=float(best_val),
        expectation=float(best_val),
        best_bitstring=max(counts, key=counts.get) if counts else None,
        shots=1024,
        iterations=evals["count"],
        converged=True,
        wall_time_s=time.perf_counter() - t0,
        meta={
            "layers": layers,
            "parameters": npar,
            "term_count": len(terms),
            "circuit_depth": depth,
            "gate_count": gates,
            "two_qubit_gates": two_q,
            "optimizer": "COBYLA" if have_scipy else "nelder-mead",
        },
    )


def exact_ground_energy(terms: list[tuple[float, str]]) -> float:
    """Exact lowest eigenvalue by building the dense Hamiltonian.

    Only tractable for small n (2**n x 2**n matrix), but that is exactly the
    regime where a user deserves a certified answer and a check on VQE.
    """
    n = len(terms[0][1])
    if n > 12:
        raise ValueError(f"dense diagonalization needs n <= 12, got {n}")
    I = np.eye(2, dtype=complex)
    X = np.array([[0, 1], [1, 0]], dtype=complex)
    Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
    Z = np.array([[1, 0], [0, -1]], dtype=complex)
    M = {"I": I, "X": X, "Y": Y, "Z": Z}
    dim = 1 << n
    H = np.zeros((dim, dim), dtype=complex)
    for coeff, pauli in terms:
        # Qubit 0 is the least significant bit, so the Kronecker product is
        # built from the highest-index qubit down.
        op = np.array([[1.0 + 0j]])
        for q in range(n - 1, -1, -1):
            op = np.kron(op, M[pauli[q]])
        H += coeff * op
    return float(np.linalg.eigvalsh(H)[0])
