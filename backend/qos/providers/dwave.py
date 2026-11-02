"""D-Wave adapter: quantum annealers and Leap hybrid solvers.

D-Wave matters to this platform more than its public profile suggests,
because it is the only provider whose native input *is* the platform's
intermediate representation. A QUBO goes to an annealer unchanged -- no
circuit, no QAOA parameter loop, no transpilation. And the scale is in a
different league: ~5000 physical qubits on Advantage, and hybrid solvers that
accept up to a million binary variables.

The trade-off the broker weighs: annealers do not run Grover, VQE or anything
requiring gate-model coherence, and the hardware graph is sparse (Pegasus
degree 15, Zephyr degree 20), so a dense QUBO needs minor embedding -- several
physical qubits chained per logical variable. ``embedding_overhead``
estimates that, because a dense 200-variable problem will not fit a
5000-qubit annealer despite the headline number.
"""

from __future__ import annotations

import time

import numpy as np

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

# Leap QPU access is billed per second of QPU time; hybrid solvers per second
# of solver time with a minimum charge.
DWAVE_QPU_USD_PER_SECOND = 0.00019 * 1000   # ~$0.19/s of QPU access time
DWAVE_HYBRID_USD_PER_SECOND = 0.05


class DWaveProvider(Provider):
    vendor = "dwave"
    display_name = "D-Wave Leap"
    sdk_modules = ("dimod",)
    credential_env = ("DWAVE_API_TOKEN",)
    install_extra = "dwave"

    def __init__(self) -> None:
        self._live: dict[str, dict] = {}

    def capabilities(self) -> list[BackendCapability]:
        creds = self.has_credentials()
        sdk = self.sdk_available()
        adv = self._live.get("advantage", {})
        adv2 = self._live.get("advantage2", {})
        return [
            BackendCapability(
                id="dwave.advantage",
                vendor="dwave",
                name="D-Wave Advantage (Pegasus, ~5600 qubits)",
                modality=Modality.ANNEALER,
                max_qubits=adv.get("qubits", 5612),
                supports=(FormulationKind.QUBO, FormulationKind.ISING),
                two_qubit_error=None,
                max_shots=10_000,          # "num_reads"
                all_to_all=False,          # degree-15 Pegasus graph
                cost_per_second_usd=DWAVE_QPU_USD_PER_SECOND,
                available=sdk and creds and adv.get("online", True),
                est_queue_wait_s=adv.get("queue_wait_s", 30.0),
                credentialed=creds,
                unavailable_reason=blocker(
                    sdk_ok=sdk, creds_ok=creds, needs_creds=True,
                    sdk_name="dwave-ocean-sdk", install_extra="dwave",
                    credential_env=self.credential_env, offline=not adv.get("online", True),
                ),
                tags=("qpu", "annealer", "pegasus", "large-scale", "paid"),
            ),
            BackendCapability(
                id="dwave.advantage2",
                vendor="dwave",
                name="D-Wave Advantage2 (Zephyr, ~4400 qubits)",
                modality=Modality.ANNEALER,
                max_qubits=adv2.get("qubits", 4400),
                supports=(FormulationKind.QUBO, FormulationKind.ISING),
                max_shots=10_000,
                all_to_all=False,          # degree-20 Zephyr graph
                cost_per_second_usd=DWAVE_QPU_USD_PER_SECOND,
                available=sdk and creds and adv2.get("online", True),
                est_queue_wait_s=adv2.get("queue_wait_s", 30.0),
                credentialed=creds,
                unavailable_reason=blocker(
                    sdk_ok=sdk, creds_ok=creds, needs_creds=True,
                    sdk_name="dwave-ocean-sdk", install_extra="dwave",
                    credential_env=self.credential_env, offline=not adv2.get("online", True),
                ),
                tags=("qpu", "annealer", "zephyr", "higher-connectivity", "paid"),
            ),
            BackendCapability(
                id="dwave.hybrid_bqm",
                vendor="dwave",
                name="D-Wave Leap hybrid BQM solver (up to 1M variables)",
                modality=Modality.ANNEALER,
                max_qubits=1_000_000,
                supports=(FormulationKind.QUBO, FormulationKind.ISING),
                max_shots=1,
                all_to_all=True,           # hybrid handles embedding internally
                cost_per_second_usd=DWAVE_HYBRID_USD_PER_SECOND,
                available=sdk and creds,
                est_queue_wait_s=10.0,
                credentialed=creds,
                unavailable_reason=blocker(
                    sdk_ok=sdk, creds_ok=creds, needs_creds=True,
                    sdk_name="dwave-ocean-sdk", install_extra="dwave",
                    credential_env=self.credential_env, offline=False,
                ),
                tags=("hybrid", "annealer", "massive-scale", "robust", "paid"),
            ),
        ]

    def refresh(self) -> None:
        if not (self.sdk_available() and self.has_credentials()):
            return
        try:
            from dwave.cloud import Client

            with Client.from_config() as client:
                for solver in client.get_solvers():
                    name = str(getattr(solver, "id", ""))
                    key = None
                    if "Advantage2" in name:
                        key = "advantage2"
                    elif "Advantage" in name:
                        key = "advantage"
                    if key:
                        self._live[key] = {
                            "qubits": int(len(getattr(solver, "nodes", []) or [])) or None,
                            "online": bool(getattr(solver, "online", True)),
                        }
                        # Drop a None qubit count so the catalog default survives.
                        if not self._live[key]["qubits"]:
                            self._live[key].pop("qubits")
        except Exception:
            return

    def run(
        self,
        backend: BackendCapability,
        formulation: Formulation,
        need: ResourceNeed,
        policy: Policy,
    ) -> RawResult:
        self._require_ready()
        try:
            import dimod
        except ImportError as e:
            raise ProviderUnavailable(
                "dwave-ocean-sdk not installed: pip install 'quantum-os[dwave]'"
            ) from e

        Q = np.asarray(formulation.Q, dtype=float)
        bqm = qubo_to_bqm(dimod, Q, formulation.offset)
        t0 = time.perf_counter()

        try:
            if backend.id == "dwave.hybrid_bqm":
                from dwave.system import LeapHybridSampler

                sampler = LeapHybridSampler()
                sampleset = sampler.sample(bqm, label="quantum-os")
            else:
                from dwave.system import DWaveSampler, EmbeddingComposite

                solver_name = (
                    "Advantage2" if backend.id.endswith("advantage2") else "Advantage"
                )
                base = DWaveSampler(solver={"name__contains": solver_name})
                # EmbeddingComposite finds a minor embedding of the dense
                # problem graph onto the sparse hardware graph automatically.
                sampler = EmbeddingComposite(base)
                sampleset = sampler.sample(
                    bqm,
                    num_reads=min(need.shots, backend.max_shots),
                    annealing_time=20,          # microseconds, default schedule
                    label="quantum-os",
                )
        except Exception as e:
            raise ProviderExecutionError(f"D-Wave run failed on {backend.id}: {e}") from e

        elapsed = time.perf_counter() - t0
        n = Q.shape[0]
        counts: dict[str, int] = {}
        for rec in sampleset.record:
            sample, energy, occ = rec[0], float(rec[1]), int(rec[2])
            bits = "".join("1" if sample[i] > 0 else "0" for i in range(n))
            counts[bits] = counts.get(bits, 0) + occ

        best = sampleset.first
        best_bits = "".join("1" if best.sample[i] > 0 else "0" for i in range(n))
        info = dict(sampleset.info or {})
        qpu_us = float(info.get("qpu_access_time", 0.0))
        charge_s = (
            float(info.get("charge_time", 0.0)) / 1e6
            if "charge_time" in info else qpu_us / 1e6
        ) or elapsed

        return RawResult(
            backend_id=backend.id,
            algorithm="quantum_annealing",
            counts=counts,
            best_bitstring=best_bits,
            best_energy=float(best.energy),
            shots=int(sum(counts.values())),
            wall_time_s=elapsed,
            cost_usd=charge_s * backend.cost_per_second_usd,
            converged=True,
            meta={
                "executed_on": backend.id,
                "qpu_access_time_us": qpu_us,
                "chain_break_fraction": float(
                    np.mean(sampleset.record.chain_break_fraction)
                ) if "chain_break_fraction" in sampleset.record.dtype.names else 0.0,
                "solver_info": {k: v for k, v in info.items() if isinstance(v, (int, float, str))},
            },
        )


def qubo_to_bqm(dimod, Q: np.ndarray, offset: float = 0.0):
    """Dense QUBO matrix -> dimod BinaryQuadraticModel."""
    n = Q.shape[0]
    Qs = (Q + Q.T) / 2.0
    linear = {i: float(Qs[i, i]) for i in range(n)}
    quadratic = {
        (i, j): float(Qs[i, j] + Qs[j, i])
        for i in range(n)
        for j in range(i + 1, n)
        if abs(Qs[i, j]) > 1e-12
    }
    return dimod.BinaryQuadraticModel(linear, quadratic, float(offset), dimod.BINARY)


def embedding_overhead(Q: np.ndarray, hardware_degree: int = 15) -> tuple[int, float]:
    """Estimate physical qubits needed to embed a QUBO on a sparse annealer.

    A logical variable with more neighbours than the hardware degree must be
    represented as a chain of physical qubits. Chain length grows roughly
    linearly in the excess degree, and long chains break more often, which is
    why the broker penalizes dense problems on annealers rather than trusting
    the headline qubit count.
    """
    n = Q.shape[0]
    adj = np.abs(np.triu(Q, 1)) > 1e-12
    degrees = (adj | adj.T).sum(axis=1)
    max_deg = int(degrees.max()) if n else 0
    if max_deg <= hardware_degree:
        return n, 1.0
    # Clique embedding on Pegasus/Zephyr needs ~n/4 chain length for dense graphs.
    chain = max(1.0, max_deg / hardware_degree)
    return int(np.ceil(n * chain)), float(chain)
