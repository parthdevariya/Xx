"""Amazon Braket adapter: AWS-managed simulators and third-party QPUs.

Braket is the broadest single access point in the market -- trapped-ion
(IonQ), superconducting (Rigetti, IQM) and neutral-atom (QuEra) hardware
behind one API and one bill. That makes it the most useful provider for the
broker to have, since switching between device *modalities* becomes a
scoring decision rather than an integration project.

Pricing below is catalog-rate: a per-task charge plus a per-shot charge.
``refresh()`` replaces these with the live values Braket publishes in
``device.properties.service.deviceCost`` when credentials are present, since
per-shot rates do change.
"""

from __future__ import annotations

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

BRAKET_TASK_FEE_USD = 0.30

# (short id, ARN, display, modality, qubits, 2q err, per-shot USD, all-to-all)
BRAKET_DEVICES = [
    ("sv1", "arn:aws:braket:::device/quantum-simulator/amazon/sv1",
     "Braket SV1 statevector", Modality.GATE_SIMULATOR, 34, None, 0.0, True),
    ("dm1", "arn:aws:braket:::device/quantum-simulator/amazon/dm1",
     "Braket DM1 density matrix", Modality.GATE_SIMULATOR, 17, None, 0.0, True),
    ("tn1", "arn:aws:braket:::device/quantum-simulator/amazon/tn1",
     "Braket TN1 tensor network", Modality.GATE_SIMULATOR, 50, None, 0.0, True),
    ("ionq-aria", "arn:aws:braket:us-east-1::device/qpu/ionq/Aria-1",
     "IonQ Aria-1 (trapped ion)", Modality.GATE_QPU, 25, 4.0e-3, 0.03, True),
    ("ionq-forte", "arn:aws:braket:us-east-1::device/qpu/ionq/Forte-1",
     "IonQ Forte-1 (trapped ion)", Modality.GATE_QPU, 36, 3.0e-3, 0.08, True),
    ("iqm-garnet", "arn:aws:braket:eu-north-1::device/qpu/iqm/Garnet",
     "IQM Garnet (superconducting)", Modality.GATE_QPU, 20, 6.0e-3, 0.00145, False),
    ("rigetti-ankaa", "arn:aws:braket:us-west-1::device/qpu/rigetti/Ankaa-3",
     "Rigetti Ankaa-3 (superconducting)", Modality.GATE_QPU, 84, 1.2e-2, 0.00035, False),
]

# Simulator time-based rates, USD per minute.
SIM_RATE_PER_MIN = {"sv1": 0.075, "dm1": 0.075, "tn1": 0.275}


class BraketProvider(Provider):
    vendor = "aws"
    display_name = "Amazon Braket"
    sdk_modules = ("braket",)
    credential_env = ("AWS_ACCESS_KEY_ID", "AWS_PROFILE", "AWS_SESSION_TOKEN")
    install_extra = "aws"

    def __init__(self) -> None:
        self._live: dict[str, dict] = {}

    def capabilities(self) -> list[BackendCapability]:
        creds = self.has_credentials()
        sdk = self.sdk_available()
        out: list[BackendCapability] = []
        for short, arn, name, modality, nq, e2q, per_shot, a2a in BRAKET_DEVICES:
            is_sim = modality is Modality.GATE_SIMULATOR
            out.append(_cap_with_arn(
                short, arn, name, modality, self._live.get(short, {}),
                nq, e2q, per_shot, a2a, sdk, creds, is_sim,
            ))
        return out

    def refresh(self) -> None:
        if not (self.sdk_available() and self.has_credentials()):
            return
        try:
            from braket.aws import AwsDevice
        except Exception:
            return
        for short, arn, *_rest in BRAKET_DEVICES:
            try:
                dev = AwsDevice(arn)
                entry: dict = {"available": str(dev.status).upper() == "ONLINE"}
                svc = dev.properties.service
                # Live per-shot pricing, when the device publishes it.
                cost = getattr(svc, "deviceCost", None)
                if cost is not None and getattr(cost, "unit", "") == "shot":
                    entry["per_shot"] = float(cost.price)
                paradigm = getattr(dev.properties, "paradigm", None)
                if paradigm is not None and hasattr(paradigm, "qubitCount"):
                    entry["qubits"] = int(paradigm.qubitCount)
                windows = getattr(svc, "executionWindows", None)
                if windows:
                    entry["queue_wait_s"] = 60.0
                self._live[short] = entry
            except Exception:
                continue

    def run(
        self,
        backend: BackendCapability,
        formulation: Formulation,
        need: ResourceNeed,
        policy: Policy,
    ) -> RawResult:
        self._require_ready()
        try:
            from braket.aws import AwsDevice
            from braket.circuits import Circuit
        except ImportError as e:
            raise ProviderUnavailable(
                "amazon-braket-sdk not installed: pip install 'quantum-os[aws]'"
            ) from e

        short = backend.id.split(".", 1)[1]
        arn = next((a for s, a, *_ in BRAKET_DEVICES if s == short), None)
        if arn is None:
            raise ProviderExecutionError(f"unknown Braket device {short!r}")

        layers = 3
        for note in need.notes:
            if note.startswith("layers="):
                layers = int(note.split("=")[1])

        t0 = time.perf_counter()
        try:
            device = AwsDevice(arn)
        except Exception as e:
            raise ProviderUnavailable(f"cannot reach Braket device {short}: {e}") from e

        shots = min(need.shots, backend.max_shots)
        tasks = {"count": 0}

        def sampler(n, diag, gammas, betas, n_shots):
            circuit = build_braket_circuit(Circuit, np.asarray(formulation.Q), gammas, betas)
            task = device.run(circuit, shots=n_shots)
            tasks["count"] += 1
            counts = task.result().measurement_counts
            # Braket returns bitstrings with qubit 0 leftmost, which already
            # matches this platform's position==qubit convention.
            return {str(b)[:n]: int(c) for b, c in counts.items()}

        try:
            res = run_qaoa(
                np.asarray(formulation.Q), formulation.offset,
                layers=layers, shots=shots, seed=policy.seed,
                backend_id=backend.id, sampler=sampler,
            )
        except Exception as e:
            raise ProviderExecutionError(f"Braket run failed on {short}: {e}") from e

        elapsed = time.perf_counter() - t0
        res.cost_usd = (
            tasks["count"] * backend.cost_per_task_usd
            + shots * backend.cost_per_shot_usd
            + elapsed * backend.cost_per_second_usd
        )
        res.meta["executed_on"] = short
        res.meta["device_arn"] = arn
        res.meta["braket_tasks"] = tasks["count"]
        return res


def _cap_with_arn(
    short, arn, name, modality, live, nq, e2q, per_shot, a2a, sdk, creds, is_sim
) -> BackendCapability:
    """Build the capability struct; ARN is carried in tags for traceability."""
    tags = ["simulator" if is_sim else "qpu"]
    if "ionq" in short:
        tags.append("trapped-ion")
    if short in ("iqm-garnet", "rigetti-ankaa"):
        tags.append("superconducting")
    if a2a and not is_sim:
        tags.append("all-to-all")
    if not is_sim or short in SIM_RATE_PER_MIN:
        tags.append("paid")
    return BackendCapability(
        id=f"aws.{short}",
        vendor="aws",
        name=name,
        modality=modality,
        max_qubits=live.get("qubits", nq),
        supports=(FormulationKind.QUBO, FormulationKind.ISING,
                  FormulationKind.PAULI_SUM, FormulationKind.CIRCUIT),
        two_qubit_error=live.get("two_qubit_error", e2q),
        max_shots=100_000 if is_sim else 10_000,
        all_to_all=a2a,
        cost_per_shot_usd=live.get("per_shot", per_shot),
        cost_per_task_usd=0.0 if is_sim else BRAKET_TASK_FEE_USD,
        cost_per_second_usd=SIM_RATE_PER_MIN.get(short, 0.0) / 60.0,
        available=sdk and creds and live.get("available", True),
        est_queue_wait_s=live.get("queue_wait_s", 5.0 if is_sim else 300.0),
        credentialed=creds,
        unavailable_reason=blocker(
            sdk_ok=sdk, creds_ok=creds, needs_creds=True,
            sdk_name="amazon-braket-sdk", install_extra="aws",
            credential_env=("AWS_ACCESS_KEY_ID", "AWS_PROFILE"),
            offline=not live.get("available", True),
        ),
        tags=tuple(tags),
    )


def build_braket_circuit(Circuit, Q: np.ndarray, gammas, betas):
    """QAOA circuit in Braket's gate set (zz is composed from cnot+rz)."""
    n = Q.shape[0]
    h, J, _c = qubo_to_ising(Q, 0.0)
    scale = max(float(np.abs(h).max() if h.size else 0.0),
                float(np.abs(J).max() if J.size else 0.0)) or 1.0
    circ = Circuit()
    for q in range(n):
        circ.h(q)
    for g, b in zip(gammas, betas):
        for i in range(n):
            if abs(h[i]) > 1e-12:
                circ.rz(i, 2.0 * float(g) * float(h[i]) / scale)
        for i in range(n):
            for j in range(i + 1, n):
                w = float(J[i, j] + J[j, i])
                if abs(w) > 1e-12:
                    circ.cnot(i, j)
                    circ.rz(j, 2.0 * float(g) * w / scale)
                    circ.cnot(i, j)
        for q in range(n):
            circ.rx(q, 2.0 * float(b))
    return circ
