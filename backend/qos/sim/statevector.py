"""Dependency-free statevector simulator (numpy only).

This exists so Quantum OS has a real execution engine out of the box: no
vendor SDK, no credentials, no network. It is the default backend and the
correctness reference the vendor adapters are checked against.

Convention: qubit 0 is the least-significant bit, so basis state index ``i``
has qubit ``q`` set iff ``(i >> q) & 1``. Bitstrings are rendered
little-endian-left, i.e. ``bitstring[q]`` is qubit ``q``.

Scaling: a statevector needs 2**n complex amplitudes, so memory is the hard
wall -- 24 qubits is ~268 MB, 28 qubits is ~4.3 GB. The estimator uses
MAX_PRACTICAL_QUBITS to keep the broker from planning a run that would thrash.
"""

from __future__ import annotations

import numpy as np

# Beyond this, a local statevector run is slower than the classical solver it
# is meant to be compared against, so the broker routes elsewhere.
MAX_PRACTICAL_QUBITS = 22

_INV_SQRT2 = 1.0 / np.sqrt(2.0)

H = np.array([[_INV_SQRT2, _INV_SQRT2], [_INV_SQRT2, -_INV_SQRT2]], dtype=complex)
X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
Z = np.array([[1, 0], [0, -1]], dtype=complex)
S = np.array([[1, 0], [0, 1j]], dtype=complex)
T = np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex)


def rx(theta: float) -> np.ndarray:
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)


def ry(theta: float) -> np.ndarray:
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -s], [s, c]], dtype=complex)


def rz(theta: float) -> np.ndarray:
    e = np.exp(-1j * theta / 2)
    return np.array([[e, 0], [0, np.conj(e)]], dtype=complex)


class StateVector:
    """Mutable statevector with in-place gate application.

    Gate methods return ``self`` so circuits read as fluent chains, which keeps
    the algorithm modules (QAOA, Grover, VQE) close to their textbook form.
    """

    __slots__ = ("n", "dim", "state", "_gate_count", "_two_qubit_count", "_depth")

    def __init__(self, n: int, state: np.ndarray | None = None) -> None:
        if n < 1:
            raise ValueError("need at least 1 qubit")
        if n > 30:
            raise ValueError(
                f"{n} qubits needs {2**n * 16 / 1e9:.1f} GB; refusing to allocate"
            )
        self.n = n
        self.dim = 1 << n
        if state is None:
            self.state = np.zeros(self.dim, dtype=complex)
            self.state[0] = 1.0
        else:
            if state.shape != (self.dim,):
                raise ValueError(f"state must have shape ({self.dim},)")
            self.state = state.astype(complex, copy=True)
        self._gate_count = 0
        self._two_qubit_count = 0
        self._depth = 0

    # ---------------------------------------------------------------- stats
    @property
    def gate_count(self) -> int:
        return self._gate_count

    @property
    def two_qubit_count(self) -> int:
        return self._two_qubit_count

    # ------------------------------------------------------- single qubit
    def apply_1q(self, gate: np.ndarray, q: int) -> "StateVector":
        """Apply a 2x2 unitary to qubit ``q``.

        Uses a reshape into (high, 2, low) so the gate is a contraction over
        the middle axis -- no index arithmetic, and numpy does it at C speed.
        """
        self._check(q)
        hi = 1 << (self.n - 1 - q)
        lo = 1 << q
        v = self.state.reshape(hi, 2, lo)
        a = v[:, 0, :].copy()
        b = v[:, 1, :]
        v[:, 0, :] = gate[0, 0] * a + gate[0, 1] * b
        v[:, 1, :] = gate[1, 0] * a + gate[1, 1] * b
        self._gate_count += 1
        self._depth += 1
        return self

    def h(self, q: int) -> "StateVector":
        return self.apply_1q(H, q)

    def x(self, q: int) -> "StateVector":
        return self.apply_1q(X, q)

    def y(self, q: int) -> "StateVector":
        return self.apply_1q(Y, q)

    def z(self, q: int) -> "StateVector":
        return self.apply_1q(Z, q)

    def rx(self, q: int, theta: float) -> "StateVector":
        return self.apply_1q(rx(theta), q)

    def ry(self, q: int, theta: float) -> "StateVector":
        return self.apply_1q(ry(theta), q)

    def rz(self, q: int, theta: float) -> "StateVector":
        return self.apply_1q(rz(theta), q)

    def h_all(self) -> "StateVector":
        for q in range(self.n):
            self.h(q)
        return self

    # --------------------------------------------------------- two qubit
    def cx(self, control: int, target: int) -> "StateVector":
        self._check(control)
        self._check(target)
        if control == target:
            raise ValueError("control and target must differ")
        idx = np.arange(self.dim)
        # Rows where control is 1 and target is 0 swap with their target-flipped partner.
        mask = ((idx >> control) & 1 == 1) & ((idx >> target) & 1 == 0)
        src = idx[mask]
        dst = src | (1 << target)
        tmp = self.state[src].copy()
        self.state[src] = self.state[dst]
        self.state[dst] = tmp
        self._gate_count += 1
        self._two_qubit_count += 1
        self._depth += 1
        return self

    def cz(self, a: int, b: int) -> "StateVector":
        self._check(a)
        self._check(b)
        idx = np.arange(self.dim)
        mask = (((idx >> a) & 1) == 1) & (((idx >> b) & 1) == 1)
        self.state[mask] *= -1.0
        self._gate_count += 1
        self._two_qubit_count += 1
        self._depth += 1
        return self

    def rzz(self, a: int, b: int, theta: float) -> "StateVector":
        """exp(-i*theta/2 * Z_a Z_b) -- the workhorse of QAOA cost layers.

        Diagonal in the computational basis, so it is a single elementwise
        multiply rather than a matrix contraction.
        """
        self._check(a)
        self._check(b)
        idx = np.arange(self.dim)
        parity = (((idx >> a) & 1) ^ ((idx >> b) & 1)).astype(float)
        # parity 0 -> eigenvalue +1, parity 1 -> eigenvalue -1
        sign = 1.0 - 2.0 * parity
        self.state *= np.exp(-1j * theta / 2.0 * sign)
        self._gate_count += 1
        self._two_qubit_count += 1
        self._depth += 1
        return self

    def phase_diag(self, phases: np.ndarray) -> "StateVector":
        """Apply exp(-i * phases[i]) to every amplitude.

        Lets an arbitrary diagonal cost Hamiltonian become one vectorized op,
        which is what makes QAOA on a dense QUBO fast here.
        """
        if phases.shape != (self.dim,):
            raise ValueError("phases must match state dimension")
        self.state *= np.exp(-1j * phases)
        self._gate_count += 1
        self._depth += 1
        return self

    # ------------------------------------------------------ multi-control
    def mcz(self, qubits: list[int] | None = None) -> "StateVector":
        """Flip the phase of the all-ones state over ``qubits`` (default: all)."""
        qs = list(range(self.n)) if qubits is None else qubits
        for q in qs:
            self._check(q)
        idx = np.arange(self.dim)
        mask = np.ones(self.dim, dtype=bool)
        for q in qs:
            mask &= ((idx >> q) & 1) == 1
        self.state[mask] *= -1.0
        self._gate_count += 1
        if len(qs) > 1:
            self._two_qubit_count += 2 * (len(qs) - 1)  # Toffoli decomposition cost
        self._depth += 1
        return self

    def phase_oracle(self, marked: np.ndarray | list[int]) -> "StateVector":
        """Flip the phase of every marked basis state (Grover oracle)."""
        self.state[np.asarray(marked, dtype=np.int64)] *= -1.0
        self._gate_count += 1
        self._depth += 1
        return self

    # ------------------------------------------------------------ readout
    def probabilities(self) -> np.ndarray:
        p = np.abs(self.state) ** 2
        total = p.sum()
        return p / total if total > 0 else p

    def sample(self, shots: int, rng: np.random.Generator | None = None) -> dict[str, int]:
        """Sample measurement outcomes and return bitstring -> count."""
        rng = rng or np.random.default_rng()
        p = self.probabilities()
        draws = rng.multinomial(shots, p)
        nz = np.nonzero(draws)[0]
        return {self.bitstring(int(i)): int(draws[i]) for i in nz}

    def sample_indices(self, shots: int, rng: np.random.Generator | None = None) -> np.ndarray:
        rng = rng or np.random.default_rng()
        return rng.choice(self.dim, size=shots, p=self.probabilities())

    def bitstring(self, index: int) -> str:
        """Render basis index as a bitstring where position q is qubit q."""
        return "".join("1" if (index >> q) & 1 else "0" for q in range(self.n))

    def expectation_diag(self, diag: np.ndarray) -> float:
        """Expectation of a diagonal observable given its 2**n eigenvalues."""
        return float(np.dot(self.probabilities(), diag))

    def norm(self) -> float:
        return float(np.linalg.norm(self.state))

    def normalize(self) -> "StateVector":
        nrm = self.norm()
        if nrm > 0:
            self.state /= nrm
        return self

    def copy(self) -> "StateVector":
        return StateVector(self.n, self.state)

    def _check(self, q: int) -> None:
        if not 0 <= q < self.n:
            raise ValueError(f"qubit {q} out of range for {self.n} qubits")

    def __repr__(self) -> str:
        return f"StateVector(n={self.n}, gates={self._gate_count})"


def bitstring_to_array(bits: str) -> np.ndarray:
    """Bitstring (position q == qubit q) -> int array of 0/1."""
    return np.array([int(c) for c in bits], dtype=np.int8)


def array_to_bitstring(arr: np.ndarray) -> str:
    return "".join(str(int(v)) for v in arr)


def index_to_array(index: int, n: int) -> np.ndarray:
    return np.array([(index >> q) & 1 for q in range(n)], dtype=np.int8)


def all_basis_arrays(n: int) -> np.ndarray:
    """Matrix of shape (2**n, n) whose row i is basis state i as 0/1.

    Used to evaluate a QUBO over the entire space at once, which gives exact
    expectation values and exact optima for the small-n regime.
    """
    idx = np.arange(1 << n, dtype=np.int64)
    shifts = np.arange(n, dtype=np.int64)
    return ((idx[:, None] >> shifts[None, :]) & 1).astype(np.int8)
