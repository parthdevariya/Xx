"""QUBO construction and evaluation.

A QUBO (Quadratic Unconstrained Binary Optimization) problem is

    minimize  x.T @ Q @ x + offset,    x in {0, 1}^n

Almost every combinatorial problem a user will ask about lands here, which is
why QUBO is the central intermediate representation of the platform: one
encoding feeds gate-based QAOA, quantum annealers, and the classical baseline
solvers without reformulation.

Hard constraints become quadratic penalty terms. Penalty weights matter a
lot -- too small and the optimizer returns infeasible answers, too large and
the objective landscape flattens and the optimizer cannot see the signal. See
``PenaltyScaler`` for how the weight is chosen rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..models import Formulation, FormulationKind


class QUBOBuilder:
    """Accumulates linear/quadratic terms and constraint penalties.

    Terms are summed into an upper-triangular-ish dense matrix; ``build``
    symmetrizes at the end so ``x.T @ Q @ x`` is unambiguous.
    """

    def __init__(self, n: int, name: str = "") -> None:
        self.n = n
        self.name = name
        self.Q = np.zeros((n, n), dtype=float)
        self.offset = 0.0
        self.notes: list[str] = []
        self.penalties: dict[str, float] = {}
        self._labels: dict[int, str] = {}

    # ------------------------------------------------------------ terms
    def linear(self, i: int, w: float) -> "QUBOBuilder":
        """Add w * x_i. Linear terms live on the diagonal since x_i^2 == x_i."""
        self.Q[i, i] += w
        return self

    def quadratic(self, i: int, j: int, w: float) -> "QUBOBuilder":
        """Add w * x_i * x_j."""
        if i == j:
            self.Q[i, i] += w
        else:
            self.Q[i, j] += w / 2.0
            self.Q[j, i] += w / 2.0
        return self

    def constant(self, c: float) -> "QUBOBuilder":
        self.offset += c
        return self

    def label(self, i: int, text: str) -> "QUBOBuilder":
        """Attach a human-readable name to variable i, for decoding."""
        self._labels[i] = text
        return self

    # ------------------------------------------------------- constraints
    def penalize_equality(
        self, indices: list[int], target: float, weight: float, tag: str = ""
    ) -> "QUBOBuilder":
        """Add weight * (sum_{i in indices} x_i - target)^2.

        Expanding: sum_i x_i^2 + 2*sum_{i<j} x_i x_j - 2*target*sum_i x_i + target^2
        and x_i^2 == x_i for binary x.
        """
        w = float(weight)
        for i in indices:
            self.linear(i, w * (1.0 - 2.0 * target))
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                self.quadratic(indices[a], indices[b], 2.0 * w)
        self.constant(w * target * target)
        if tag:
            self.penalties[tag] = w
        return self

    def penalize_one_hot(
        self, indices: list[int], weight: float, tag: str = ""
    ) -> "QUBOBuilder":
        """Exactly one of ``indices`` must be 1."""
        return self.penalize_equality(indices, 1.0, weight, tag)

    def penalize_at_most_one(
        self, indices: list[int], weight: float, tag: str = ""
    ) -> "QUBOBuilder":
        """Pairwise exclusion: no two of ``indices`` both 1.

        Cheaper than an equality penalty -- no linear or constant term, so it
        does not shift the objective for feasible assignments.
        """
        w = float(weight)
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                self.quadratic(indices[a], indices[b], w)
        if tag:
            self.penalties[tag] = w
        return self

    def penalize_implication(self, i: int, j: int, weight: float, tag: str = "") -> "QUBOBuilder":
        """x_i = 1 implies x_j = 1, via weight * x_i * (1 - x_j)."""
        w = float(weight)
        self.linear(i, w)
        self.quadratic(i, j, -w)
        if tag:
            self.penalties[tag] = w
        return self

    def penalize_inequality_leq(
        self,
        indices: list[int],
        coeffs: list[float],
        capacity: float,
        weight: float,
        tag: str = "",
        n_slack: int | None = None,
    ) -> "QUBOBuilder":
        """Encode sum_i c_i x_i <= capacity using binary slack variables.

        Returns the builder; slack variables are appended to the end of the
        variable vector, so callers must size ``n`` accordingly up front via
        ``slack_bits_needed``.
        """
        if n_slack is None:
            n_slack = slack_bits_needed(capacity)
        start = self.n - n_slack
        slack_idx = list(range(start, self.n))
        all_idx = list(indices) + slack_idx
        all_coef = list(coeffs) + [float(1 << k) for k in range(n_slack)]
        # weight * (sum c_i x_i + sum 2^k s_k - capacity)^2
        w = float(weight)
        for pos, i in enumerate(all_idx):
            c = all_coef[pos]
            self.linear(i, w * (c * c - 2.0 * capacity * c))
        for a in range(len(all_idx)):
            for b in range(a + 1, len(all_idx)):
                self.quadratic(all_idx[a], all_idx[b], 2.0 * w * all_coef[a] * all_coef[b])
        self.constant(w * capacity * capacity)
        if tag:
            self.penalties[tag] = w
        return self

    # ------------------------------------------------------------ output
    def build(self, decode: dict | None = None) -> Formulation:
        Q = (self.Q + self.Q.T) / 2.0
        meta = dict(decode or {})
        if self._labels:
            meta.setdefault("labels", {str(k): v for k, v in self._labels.items()})
        meta.setdefault("template", self.name)
        return Formulation(
            kind=FormulationKind.QUBO,
            num_vars=self.n,
            Q=Q,
            offset=self.offset,
            decode=meta,
            penalties=dict(self.penalties),
            notes=list(self.notes),
        )

    @property
    def magnitude(self) -> float:
        """Largest absolute coefficient -- the natural scale for penalties."""
        return float(np.abs(self.Q).max()) if self.n else 0.0


def slack_bits_needed(capacity: float) -> int:
    """Bits required to represent slack in [0, capacity]."""
    cap = max(0, int(np.floor(capacity)))
    return max(1, int(np.floor(np.log2(cap))) + 1) if cap > 0 else 1


def suggest_penalty(objective_scale: float, safety: float = 2.0) -> float:
    """Choose a penalty weight from the objective's own scale.

    Rule of thumb from the constrained-QUBO literature: the penalty must
    exceed the best possible objective improvement a constraint violation
    could buy. Scaling off the max coefficient and multiplying by a safety
    factor is the standard practical choice.
    """
    return max(1.0, float(objective_scale)) * float(safety)


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

def qubo_energy(Q: np.ndarray, x: np.ndarray, offset: float = 0.0) -> float:
    """Energy of a single assignment."""
    x = np.asarray(x, dtype=float)
    return float(x @ Q @ x + offset)


def qubo_energies(Q: np.ndarray, X: np.ndarray, offset: float = 0.0) -> np.ndarray:
    """Energies of many assignments at once.

    ``X`` has shape (m, n); returns shape (m,). Uses an einsum rather than a
    loop so the exact solver and the QAOA expectation step stay fast.
    """
    Xf = np.asarray(X, dtype=float)
    return np.einsum("ij,jk,ik->i", Xf, Q, Xf) + offset


def qubo_diagonal(Q: np.ndarray, offset: float = 0.0) -> np.ndarray:
    """Eigenvalues of the cost Hamiltonian over all 2**n basis states.

    This is the diagonal that QAOA's cost layer applies as phases and that
    exact expectation values are taken against. Only call for n <= ~22.
    """
    from ..sim.statevector import all_basis_arrays

    n = Q.shape[0]
    X = all_basis_arrays(n)
    return qubo_energies(Q, X, offset)


def qubo_to_ising(Q: np.ndarray, offset: float = 0.0) -> tuple[np.ndarray, np.ndarray, float]:
    """Convert QUBO to Ising (h, J, constant) via x = (1 - s) / 2.

    Annealers and many gate-based tools speak Ising, so this is the bridge to
    the D-Wave and Pauli-sum paths.
    """
    n = Q.shape[0]
    Qs = (Q + Q.T) / 2.0
    diag = np.diag(Qs).copy()
    offdiag = Qs - np.diag(diag)
    J = offdiag / 4.0
    h = -diag / 2.0 - offdiag.sum(axis=1) / 2.0
    const = offset + diag.sum() / 2.0 + offdiag.sum() / 4.0
    return h, J, float(const)


def ising_to_pauli_terms(h: np.ndarray, J: np.ndarray, const: float) -> list[tuple[float, str]]:
    """Render an Ising model as a Pauli sum: [(coeff, "ZIZ..."), ...]."""
    n = len(h)
    terms: list[tuple[float, str]] = []
    if abs(const) > 1e-12:
        terms.append((float(const), "I" * n))
    for i in range(n):
        if abs(h[i]) > 1e-12:
            s = ["I"] * n
            s[i] = "Z"
            terms.append((float(h[i]), "".join(s)))
    for i in range(n):
        for j in range(i + 1, n):
            w = J[i, j] + J[j, i]
            if abs(w) > 1e-12:
                s = ["I"] * n
                s[i] = s[j] = "Z"
                terms.append((float(w), "".join(s)))
    return terms


@dataclass
class ConstraintCheck:
    """Result of validating a decoded assignment against the original constraints."""

    feasible: bool
    violations: list[str] = field(default_factory=list)
