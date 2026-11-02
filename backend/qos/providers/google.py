"""Google adapter: Cirq / qsim simulators, and Quantum Engine where granted.

An honesty note the platform surfaces rather than hides: Google's hardware
(Sycamore, Willow) is **not** generally purchasable cloud capacity. Quantum
Engine access is granted per research agreement, so ``google.willow`` is
advertised but will stay ``available=False`` for almost every user. What is
genuinely useful here is qsim -- Google's high-performance simulator, which
is substantially faster than a pure-numpy statevector above ~20 qubits and
supports multithreading and GPU offload.
"""

from __future__ import annotations

import os
import time

import numpy as np

from ..algorithms.qaoa import run_qaoa
from ..formulations.qubo import qubo_to_ising
from ..models import (
    BackendCapability,
    Formulation,
    FormulationKind,
    Modality,
    Policy,
    RawResult,
    ResourceNeed,
)
from .base import Provider, ProviderExecutionError, ProviderUnavailable, blocker


class GoogleProvider(Provider):
    vendor = "google"
    display_name = "Google Quantum AI"
    sdk_modules = ("cirq",)
    credential_env = ("GOOGLE_CLOUD_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS")
    install_extra = "google"

    def capabilities(self) -> list[BackendCapability]:
        import importlib.util

        has_cirq = importlib.util.find_spec("cirq") is not None
        has_qsim = importlib.util.find_spec("qsimcirq") is not None
        creds = self.has_credentials()
        return [
            BackendCapability(
                id="google.qsim",
                vendor="google",
                name="Google qsim (high-performance simulator)",
                modality=Modality.GATE_SIMULATOR,
                max_qubits=32,
                supports=(FormulationKind.QUBO, FormulationKind.ISING,
                          FormulationKind.PAULI_SUM, FormulationKind.CIRCUIT),
                all_to_all=True,
                max_shots=1_000_000,
                available=has_qsim,
                credentialed=has_qsim,       # local, no account needed
                unavailable_reason=blocker(
                    sdk_ok=has_qsim, creds_ok=True, needs_creds=False,
                    sdk_name="qsimcirq", install_extra="google",
                ),
                tags=("free", "simulator", "fast", "multithreaded", "no-queue"),
            ),
            BackendCapability(
                id="google.cirq_sim",
                vendor="google",
                name="Cirq reference simulator",
                modality=Modality.GATE_SIMULATOR,
                max_qubits=24,
                supports=(FormulationKind.QUBO, FormulationKind.ISING,
                          FormulationKind.PAULI_SUM, FormulationKind.CIRCUIT),
                all_to_all=True,
                available=has_cirq,
                credentialed=has_cirq,
                unavailable_reason=blocker(
                    sdk_ok=has_cirq, creds_ok=True, needs_creds=False,
                    sdk_name="cirq", install_extra="google",
                ),
                tags=("free", "simulator", "no-queue"),
            ),
            BackendCapability(
                id="google.willow",
                vendor="google",
                name="Google Willow (105q) -- research access only",
                modality=Modality.GATE_QPU,
                max_qubits=105,
                supports=(FormulationKind.QUBO, FormulationKind.ISING,
                          FormulationKind.CIRCUIT),
                two_qubit_error=3.0e-3,
                all_to_all=False,            # square lattice, degree 4
                max_shots=100_000,
                # Requires an approved Quantum Engine processor, not a card.
                available=False,
                credentialed=creds and bool(os.environ.get("GOOGLE_QUANTUM_PROCESSOR_ID")),
                unavailable_reason="Google Quantum Engine access is granted per "
                                   "research agreement, not purchasable; needs an "
                                   "approved GOOGLE_QUANTUM_PROCESSOR_ID",
                tags=("qpu", "superconducting", "research-access-only", "not-purchasable"),
            ),
        ]

    def run(
        self,
        backend: BackendCapability,
        formulation: Formulation,
        need: ResourceNeed,
        policy: Policy,
    ) -> RawResult:
        try:
            import cirq
        except ImportError as e:
            raise ProviderUnavailable(
                "cirq not installed: pip install 'quantum-os[google]'"
            ) from e

        if backend.id == "google.willow":
            raise ProviderUnavailable(
                "Google Willow requires an approved Quantum Engine processor; "
                "it is not generally available cloud capacity"
            )

        layers = 3
        for note in need.notes:
            if note.startswith("layers="):
                layers = int(note.split("=")[1])

        Q = np.asarray(formulation.Q)
        t0 = time.perf_counter()

        if backend.id == "google.qsim":
            try:
                import qsimcirq

                simulator = qsimcirq.QSimSimulator()
            except ImportError as e:
                raise ProviderUnavailable("qsimcirq not installed") from e
        else:
            simulator = cirq.Simulator(seed=policy.seed)

        def sampler(n, diag, gammas, betas, n_shots):
            qubits = cirq.LineQubit.range(n)
            circuit = build_cirq_circuit(cirq, qubits, Q, gammas, betas)
            circuit.append(cirq.measure(*qubits, key="m"))
            result = simulator.run(circuit, repetitions=n_shots)
            arr = result.measurements["m"]          # shape (shots, n)
            counts: dict[str, int] = {}
            for row in arr:
                bits = "".join("1" if v else "0" for v in row)
                counts[bits] = counts.get(bits, 0) + 1
            return counts

        try:
            res = run_qaoa(
                Q, formulation.offset, layers=layers, shots=need.shots,
                seed=policy.seed, backend_id=backend.id, sampler=sampler,
            )
        except Exception as e:
            raise ProviderExecutionError(f"Google run failed on {backend.id}: {e}") from e

        res.meta["executed_on"] = backend.id
        res.meta["wall_time_s"] = time.perf_counter() - t0
        return res


def build_cirq_circuit(cirq, qubits, Q: np.ndarray, gammas, betas):
    """QAOA circuit in Cirq. ZZ interactions use cirq.ZZPowGate."""
    n = Q.shape[0]
    h, J, _c = qubo_to_ising(Q, 0.0)
    scale = max(float(np.abs(h).max() if h.size else 0.0),
                float(np.abs(J).max() if J.size else 0.0)) or 1.0
    circuit = cirq.Circuit()
    circuit.append(cirq.H.on_each(*qubits))
    for g, b in zip(gammas, betas):
        for i in range(n):
            if abs(h[i]) > 1e-12:
                # Cirq exponents are in half-turns: rz(theta) == Z**(theta/pi)
                circuit.append(cirq.Z(qubits[i]) ** (2.0 * float(g) * float(h[i]) / scale / np.pi))
        for i in range(n):
            for j in range(i + 1, n):
                w = float(J[i, j] + J[j, i])
                if abs(w) > 1e-12:
                    circuit.append(
                        cirq.ZZ(qubits[i], qubits[j]) ** (2.0 * float(g) * w / scale / np.pi)
                    )
        circuit.append(cirq.X.on_each(*qubits) ** (2.0 * float(b) / np.pi))
    return circuit
