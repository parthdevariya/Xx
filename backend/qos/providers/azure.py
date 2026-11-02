"""Azure Quantum adapter: Quantinuum, IonQ, Rigetti and Pasqal via one workspace.

The reason Azure earns a slot alongside Braket is Quantinuum. H-series
trapped-ion systems have the lowest two-qubit error rates commercially
available (~1e-3, roughly 5-10x better than superconducting devices) with
all-to-all connectivity and mid-circuit measurement. For a deep circuit the
broker should prefer fewer, better qubits over more, worse ones -- so
Quantinuum is frequently the right answer for VQE and deep QAOA even though
it has far fewer qubits than an IBM Eagle.

Billing differs by vendor: Quantinuum charges in HQCs (H-System Quantum
Credits), a function of circuit depth and shot count rather than a flat
per-shot rate, which ``hqc_estimate`` models.
"""

from __future__ import annotations

import os
import time

import numpy as np

from ..algorithms.qaoa import run_qaoa
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

# Approximate list price per HQC on the pay-as-you-go plan.
USD_PER_HQC = 12.5

# (target id, display, modality, qubits, 2q error, all-to-all, per-shot USD)
AZURE_TARGETS = [
    ("quantinuum.qpu.h2-1", "Quantinuum H2-1 (56q trapped ion)",
     Modality.GATE_QPU, 56, 1.5e-3, True, 0.0),
    ("quantinuum.qpu.h1-1", "Quantinuum H1-1 (20q trapped ion)",
     Modality.GATE_QPU, 20, 1.0e-3, True, 0.0),
    ("quantinuum.sim.h2-1e", "Quantinuum H2 emulator (noise model)",
     Modality.GATE_SIMULATOR, 56, 1.5e-3, True, 0.0),
    ("ionq.qpu.aria-1", "IonQ Aria-1 (25q trapped ion)",
     Modality.GATE_QPU, 25, 4.0e-3, True, 0.03),
    ("ionq.qpu.forte-1", "IonQ Forte-1 (36q trapped ion)",
     Modality.GATE_QPU, 36, 3.0e-3, True, 0.08),
    ("ionq.simulator", "IonQ cloud simulator",
     Modality.GATE_SIMULATOR, 29, None, True, 0.0),
    ("rigetti.qpu.ankaa-3", "Rigetti Ankaa-3 (84q superconducting)",
     Modality.GATE_QPU, 84, 1.2e-2, False, 0.00035),
]


class AzureQuantumProvider(Provider):
    vendor = "azure"
    display_name = "Azure Quantum"
    sdk_modules = ("azure.quantum",)
    credential_env = ("AZURE_QUANTUM_WORKSPACE_RESOURCE_ID", "AZURE_QUANTUM_SUBSCRIPTION_ID")
    install_extra = "azure"

    def __init__(self) -> None:
        self._live: dict[str, dict] = {}

    def capabilities(self) -> list[BackendCapability]:
        creds = self.has_credentials()
        sdk = self.sdk_available()
        out = []
        for tid, name, modality, nq, e2q, a2a, per_shot in AZURE_TARGETS:
            live = self._live.get(tid, {})
            is_sim = modality is Modality.GATE_SIMULATOR
            vendor_tag = tid.split(".")[0]
            tags = ["simulator" if is_sim else "qpu", vendor_tag]
            if a2a:
                tags.append("all-to-all")
            if vendor_tag in ("quantinuum", "ionq"):
                tags.append("trapped-ion")
            if vendor_tag == "quantinuum":
                tags += ["highest-fidelity", "mid-circuit-measurement"]
            if not is_sim:
                tags.append("paid")
            out.append(BackendCapability(
                id=f"azure.{tid}",
                vendor="azure",
                name=name,
                modality=modality,
                max_qubits=live.get("qubits", nq),
                supports=(FormulationKind.QUBO, FormulationKind.ISING,
                          FormulationKind.PAULI_SUM, FormulationKind.CIRCUIT),
                two_qubit_error=live.get("two_qubit_error", e2q),
                max_shots=10_000 if not is_sim else 100_000,
                all_to_all=a2a,
                cost_per_shot_usd=per_shot,
                available=sdk and creds and live.get("available", True),
                est_queue_wait_s=live.get("queue_wait_s", 600.0 if not is_sim else 20.0),
                credentialed=creds,
                unavailable_reason=blocker(
                    sdk_ok=sdk, creds_ok=creds, needs_creds=True,
                    sdk_name="azure-quantum", install_extra="azure",
                    credential_env=self.credential_env,
                    offline=not live.get("available", True),
                ),
                tags=tuple(tags),
            ))
        return out

    def refresh(self) -> None:
        if not (self.sdk_available() and self.has_credentials()):
            return
        try:
            ws = self._workspace()
            for target in ws.get_targets():
                tid = str(getattr(target, "name", ""))
                status = str(getattr(target, "current_availability", "Available"))
                queue = getattr(target, "average_queue_time", None)
                entry: dict = {"available": status.lower() == "available"}
                if queue is not None:
                    entry["queue_wait_s"] = float(queue)
                self._live[tid] = entry
        except Exception:
            return

    def _workspace(self):
        from azure.quantum import Workspace

        rid = os.environ.get("AZURE_QUANTUM_WORKSPACE_RESOURCE_ID")
        if rid:
            return Workspace(resource_id=rid, location=os.environ.get("AZURE_QUANTUM_LOCATION", "eastus"))
        return Workspace(
            subscription_id=os.environ["AZURE_QUANTUM_SUBSCRIPTION_ID"],
            resource_group=os.environ["AZURE_QUANTUM_RESOURCE_GROUP"],
            name=os.environ["AZURE_QUANTUM_WORKSPACE_NAME"],
            location=os.environ.get("AZURE_QUANTUM_LOCATION", "eastus"),
        )

    def run(
        self,
        backend: BackendCapability,
        formulation: Formulation,
        need: ResourceNeed,
        policy: Policy,
    ) -> RawResult:
        self._require_ready()
        target_id = backend.id.split(".", 1)[1]
        layers = 3
        for note in need.notes:
            if note.startswith("layers="):
                layers = int(note.split("=")[1])

        try:
            ws = self._workspace()
        except Exception as e:
            raise ProviderUnavailable(f"cannot open Azure Quantum workspace: {e}") from e

        t0 = time.perf_counter()
        shots = min(need.shots, backend.max_shots)
        Q = np.asarray(formulation.Q)

        def sampler(n, diag, gammas, betas, n_shots):
            # Azure Quantum accepts Qiskit circuits through its provider shim,
            # which is the most portable route across its vendor targets.
            try:
                from azure.quantum.qiskit import AzureQuantumProvider as AQP
                from qiskit import transpile

                from .ibm import build_qaoa_circuit

                provider = AQP(workspace=ws)
                device = provider.get_backend(target_id)
                qc = build_qaoa_circuit(Q, gammas, betas)
                qc.measure_all()
                tqc = transpile(qc, device, optimization_level=3)
                job = device.run(tqc, shots=n_shots)
                counts = job.result().get_counts()
                return {
                    str(b).replace(" ", "")[-n:][::-1]: int(c) for b, c in counts.items()
                }
            except ImportError as e:
                raise ProviderUnavailable(
                    "azure-quantum[qiskit] and qiskit are required for Azure execution"
                ) from e

        try:
            res = run_qaoa(
                Q, formulation.offset, layers=layers, shots=shots,
                seed=policy.seed, backend_id=backend.id, sampler=sampler,
            )
        except ProviderUnavailable:
            raise
        except Exception as e:
            raise ProviderExecutionError(f"Azure run failed on {target_id}: {e}") from e

        elapsed = time.perf_counter() - t0
        if target_id.startswith("quantinuum"):
            hqc = hqc_estimate(need.circuit_depth, shots, need.two_qubit_gates)
            res.cost_usd = hqc * USD_PER_HQC
            res.meta["hqc_estimate"] = hqc
        else:
            res.cost_usd = shots * backend.cost_per_shot_usd
        res.meta["executed_on"] = target_id
        res.meta["wall_time_s"] = elapsed
        return res


def hqc_estimate(depth: int, shots: int, two_qubit_gates: int) -> float:
    """Quantinuum H-System Quantum Credits for a circuit.

    Published formula: HQC = 5 + C * (N_1q + 10*N_2q + 5*N_meas) / 5000, where
    C is the shot count. Two-qubit gates dominate, so this is the number that
    makes a deep circuit expensive and is worth showing the user before they
    commit.
    """
    n_1q = max(0, depth - two_qubit_gates)
    n_meas = 1
    return 5.0 + shots * (n_1q + 10 * two_qubit_gates + 5 * n_meas) / 5000.0
