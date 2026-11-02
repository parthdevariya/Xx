"""IBM Quantum adapter: Qiskit Aer simulators and IBM Quantum QPUs.

Covers two distinct targets that happen to share an SDK:

* ``ibm.aer``  -- local high-performance simulator (no credentials, free).
  Worth having alongside the built-in simulator because Aer is substantially
  faster above ~18 qubits and supports realistic noise models.
* ``ibm.<device>`` -- real superconducting QPUs via IBM Quantum Runtime.

Execution model for QUBO problems is the standard hybrid split: QAOA
parameters are optimized on a simulator, and only the final parameterized
circuit is sampled on the QPU. Optimizing directly against hardware would
multiply QPU-seconds by the iteration count, which is how people
accidentally spend a lot of money for a worse answer.

Device figures below are catalog defaults. When credentials are present,
``refresh()`` replaces them with live values from the API.
"""

from __future__ import annotations

import os
import time

import numpy as np

from ..algorithms.qaoa import gate_counts, run_qaoa
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

# Pay-as-you-go list price; the Open plan gives a free monthly allowance.
IBM_USD_PER_SECOND = 1.60


class IBMProvider(Provider):
    vendor = "ibm"
    display_name = "IBM Quantum"
    sdk_modules = ("qiskit",)
    credential_env = ("QISKIT_IBM_TOKEN", "IBM_QUANTUM_TOKEN")
    install_extra = "ibm"

    def __init__(self) -> None:
        self._live: dict[str, dict] = {}

    # ---------------------------------------------------------- capabilities
    def capabilities(self) -> list[BackendCapability]:
        import importlib.util

        has_qiskit = importlib.util.find_spec("qiskit") is not None
        has_aer = importlib.util.find_spec("qiskit_aer") is not None
        creds = self.has_credentials()

        caps = [
            BackendCapability(
                id="ibm.aer",
                vendor="ibm",
                name="Qiskit Aer statevector simulator",
                modality=Modality.GATE_SIMULATOR,
                max_qubits=30,
                supports=(FormulationKind.QUBO, FormulationKind.ISING,
                          FormulationKind.PAULI_SUM, FormulationKind.CIRCUIT),
                all_to_all=True,
                max_shots=1_000_000,
                available=has_aer,
                credentialed=has_aer,     # local simulator needs no account
                unavailable_reason=blocker(
                    sdk_ok=has_aer, creds_ok=True, needs_creds=False,
                    sdk_name="qiskit-aer", install_extra="ibm",
                ),
                tags=("free", "noiseless", "fast", "no-queue"),
            ),
        ]

        # Catalog of QPU families. Error rates are representative medians.
        devices = [
            ("ibm_fez", "Heron r2", 156, 2.5e-3, 1.5e-2, 180.0),
            ("ibm_torino", "Heron r1", 133, 3.5e-3, 2.0e-2, 160.0),
            ("ibm_brisbane", "Eagle r3", 127, 7.0e-3, 2.0e-2, 230.0),
            ("ibm_sherbrooke", "Eagle r3", 127, 7.5e-3, 2.2e-2, 260.0),
        ]
        for dev_id, family, nq, e2q, ero, t1 in devices:
            live = self._live.get(dev_id, {})
            caps.append(BackendCapability(
                id=f"ibm.{dev_id}",
                vendor="ibm",
                name=f"IBM {dev_id} ({family}, {nq}q)",
                modality=Modality.GATE_QPU,
                max_qubits=live.get("num_qubits", nq),
                supports=(FormulationKind.QUBO, FormulationKind.ISING,
                          FormulationKind.PAULI_SUM, FormulationKind.CIRCUIT),
                two_qubit_error=live.get("two_qubit_error", e2q),
                readout_error=live.get("readout_error", ero),
                t1_us=live.get("t1_us", t1),
                max_shots=100_000,
                # Heavy-hex lattice: degree 2-3, so SWAP overhead is real.
                all_to_all=False,
                cost_per_second_usd=IBM_USD_PER_SECOND,
                available=has_qiskit and creds and live.get("operational", True),
                queue_depth=live.get("queue_depth", 0),
                est_queue_wait_s=live.get("queue_wait_s", 120.0),
                credentialed=creds,
                unavailable_reason=blocker(
                    sdk_ok=has_qiskit, creds_ok=creds, needs_creds=True,
                    sdk_name="qiskit-ibm-runtime", install_extra="ibm",
                    credential_env=self.credential_env,
                    offline=not live.get("operational", True),
                ),
                tags=("qpu", "superconducting", "heavy-hex", "paid"),
            ))
        return caps

    # --------------------------------------------------------------- refresh
    def refresh(self) -> None:
        """Pull live device status from IBM Quantum Runtime."""
        if not (self.sdk_available() and self.has_credentials()):
            return
        try:
            from qiskit_ibm_runtime import QiskitRuntimeService

            service = QiskitRuntimeService(
                channel="ibm_quantum_platform",
                token=os.environ.get("QISKIT_IBM_TOKEN") or os.environ.get("IBM_QUANTUM_TOKEN"),
            )
            for be in service.backends(simulator=False, operational=True):
                try:
                    status = be.status()
                    props = be.properties()
                    entry: dict = {
                        "num_qubits": be.num_qubits,
                        "operational": bool(status.operational),
                        "queue_depth": int(status.pending_jobs),
                        # Rough: historical mean job turnaround scales with queue.
                        "queue_wait_s": float(status.pending_jobs) * 30.0,
                    }
                    if props is not None:
                        errs = [
                            g.parameters[0].value
                            for g in props.gates
                            if g.gate in ("cz", "cx", "ecr") and g.parameters
                        ]
                        if errs:
                            entry["two_qubit_error"] = float(np.median(errs))
                        ros = [props.readout_error(q) for q in range(be.num_qubits)]
                        if ros:
                            entry["readout_error"] = float(np.median(ros))
                        t1s = [props.t1(q) for q in range(be.num_qubits) if props.t1(q)]
                        if t1s:
                            entry["t1_us"] = float(np.median(t1s)) * 1e6
                    self._live[be.name] = entry
                except Exception:
                    # One bad device must not blind the broker to the others.
                    continue
        except Exception:
            # Refresh is best-effort; catalog defaults remain in force.
            return

    # ------------------------------------------------------------- execution
    def run(
        self,
        backend: BackendCapability,
        formulation: Formulation,
        need: ResourceNeed,
        policy: Policy,
    ) -> RawResult:
        if backend.id == "ibm.aer":
            return self._run_aer(backend, formulation, need, policy)
        return self._run_qpu(backend, formulation, need, policy)

    # ------------------------------------------------------------------ Aer
    def _run_aer(self, backend, formulation, need, policy) -> RawResult:
        try:
            from qiskit_aer import AerSimulator
        except ImportError as e:
            raise ProviderUnavailable(
                "qiskit-aer not installed: pip install 'quantum-os[ibm]'"
            ) from e

        layers = _layers_from(need)
        sim = AerSimulator(method="statevector")

        def sampler(n, diag, gammas, betas, shots):
            qc = build_qaoa_circuit(np.asarray(formulation.Q), gammas, betas)
            qc.measure_all()
            from qiskit import transpile

            tqc = transpile(qc, sim, optimization_level=2)
            counts = sim.run(tqc, shots=shots).result().get_counts()
            return {_qiskit_bits_to_qos(b, n): c for b, c in counts.items()}

        res = run_qaoa(
            np.asarray(formulation.Q), formulation.offset,
            layers=layers, shots=need.shots, seed=policy.seed,
            backend_id=backend.id, sampler=sampler,
        )
        res.meta["executed_on"] = "qiskit-aer"
        return res

    # ------------------------------------------------------------------ QPU
    def _run_qpu(self, backend, formulation, need, policy) -> RawResult:
        self._require_ready()
        try:
            from qiskit import transpile
            from qiskit_ibm_runtime import QiskitRuntimeService
            from qiskit_ibm_runtime import SamplerV2
        except ImportError as e:
            raise ProviderUnavailable(
                "qiskit-ibm-runtime not installed: pip install 'quantum-os[ibm]'"
            ) from e

        device_name = backend.id.split(".", 1)[1]
        t0 = time.perf_counter()
        try:
            service = QiskitRuntimeService(
                channel="ibm_quantum_platform",
                token=os.environ.get("QISKIT_IBM_TOKEN") or os.environ.get("IBM_QUANTUM_TOKEN"),
            )
            device = service.backend(device_name)
        except Exception as e:
            raise ProviderUnavailable(f"cannot reach IBM backend {device_name}: {e}") from e

        layers = _layers_from(need)
        shots = min(need.shots, backend.max_shots)

        def sampler(n, diag, gammas, betas, n_shots):
            qc = build_qaoa_circuit(np.asarray(formulation.Q), gammas, betas)
            qc.measure_all()
            tqc = transpile(qc, device, optimization_level=3)
            job = SamplerV2(mode=device).run([tqc], shots=n_shots)
            result = job.result()
            counts = result[0].data.meas.get_counts()
            return {_qiskit_bits_to_qos(b, n): c for b, c in counts.items()}

        try:
            # Parameters are optimized locally; only the final sample hits the QPU.
            res = run_qaoa(
                np.asarray(formulation.Q), formulation.offset,
                layers=layers, shots=shots, seed=policy.seed,
                backend_id=backend.id, sampler=sampler,
            )
        except Exception as e:
            raise ProviderExecutionError(f"IBM run failed on {device_name}: {e}") from e

        elapsed = time.perf_counter() - t0
        res.cost_usd = elapsed * IBM_USD_PER_SECOND
        res.meta["executed_on"] = device_name
        res.meta["hybrid_split"] = "parameters optimized locally, final sampling on QPU"
        return res


def _layers_from(need: ResourceNeed) -> int:
    for note in need.notes:
        if note.startswith("layers="):
            return int(note.split("=")[1])
    return 3


def _qiskit_bits_to_qos(bits: str, n: int) -> str:
    """Qiskit returns big-endian bitstrings; this platform uses position==qubit."""
    clean = bits.replace(" ", "")[-n:]
    return clean[::-1]


def build_qaoa_circuit(Q: np.ndarray, gammas, betas):
    """Build a QAOA circuit for a QUBO as a native Qiskit circuit.

    Converts the QUBO to Ising first, because the cost layer is naturally
    expressed in Z operators: single-qubit RZ for the h terms and RZZ for the
    J couplings.
    """
    from qiskit import QuantumCircuit

    n = Q.shape[0]
    h, J, _const = qubo_to_ising(Q, 0.0)
    scale = max(float(np.abs(h).max() if h.size else 0.0),
                float(np.abs(J).max() if J.size else 0.0)) or 1.0

    qc = QuantumCircuit(n)
    qc.h(range(n))
    for g, b in zip(gammas, betas):
        for i in range(n):
            if abs(h[i]) > 1e-12:
                qc.rz(2.0 * float(g) * float(h[i]) / scale, i)
        for i in range(n):
            for j in range(i + 1, n):
                w = float(J[i, j] + J[j, i])
                if abs(w) > 1e-12:
                    qc.rzz(2.0 * float(g) * w / scale, i, j)
        qc.rx(2.0 * float(b), range(n))
    return qc


def estimate_transpiled_depth(Q: np.ndarray, layers: int, all_to_all: bool) -> tuple[int, int]:
    """(depth, two-qubit gates) after routing onto a limited-connectivity device.

    On a heavy-hex lattice, couplings between non-adjacent qubits need SWAP
    chains. The multiplier below is an empirical mid-range figure for dense
    QUBOs; it exists so the estimator does not pretend a 127-qubit device can
    run a dense 40-variable QAOA circuit coherently.
    """
    depth, _gates, two_q = gate_counts(Q, layers)
    if all_to_all:
        return depth, two_q
    n = Q.shape[0]
    density = float(np.count_nonzero(np.triu(Q, 1))) / max(1, n * (n - 1) / 2)
    swap_factor = 1.0 + 2.5 * density * np.log2(max(2, n))
    return int(depth * swap_factor), int(two_q * swap_factor)
