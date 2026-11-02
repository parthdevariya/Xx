"""Local provider: built-in statevector simulator and classical solvers.

Always available, never costs money, needs no credentials. This is what makes
the platform usable the moment it is installed, and it is the fallback of last
resort when every remote provider is unreachable.
"""

from __future__ import annotations

import numpy as np

from ..algorithms import classical, grover, qaoa, vqe
from ..models import (
    BackendCapability,
    Formulation,
    FormulationKind,
    Modality,
    Policy,
    RawResult,
    ResourceNeed,
)
from ..sim.statevector import MAX_PRACTICAL_QUBITS
from .base import Provider, ProviderExecutionError

# Classical heuristics scale to far more variables than a statevector does.
CLASSICAL_MAX_VARS = 5000


class LocalProvider(Provider):
    vendor = "local"
    display_name = "Local (built-in)"
    sdk_modules = ()            # numpy only, already a hard dependency
    credential_env = ()

    def capabilities(self) -> list[BackendCapability]:
        return [
            BackendCapability(
                id="local.sv",
                vendor="local",
                name="Built-in statevector simulator",
                modality=Modality.GATE_SIMULATOR,
                max_qubits=MAX_PRACTICAL_QUBITS,
                supports=(FormulationKind.QUBO, FormulationKind.ISING,
                          FormulationKind.PAULI_SUM, FormulationKind.ORACLE),
                all_to_all=True,
                max_shots=1_000_000,
                credentialed=True,
                tags=("free", "noiseless", "instant", "no-queue"),
            ),
            BackendCapability(
                id="local.exact",
                vendor="local",
                name="Exact enumeration (certified optimum)",
                modality=Modality.CLASSICAL,
                max_qubits=classical.EXACT_LIMIT,
                supports=(FormulationKind.QUBO, FormulationKind.ISING),
                all_to_all=True,
                credentialed=True,
                tags=("free", "exact", "certified", "no-queue"),
            ),
            BackendCapability(
                id="local.sa",
                vendor="local",
                name="Simulated annealing (classical)",
                modality=Modality.CLASSICAL,
                max_qubits=CLASSICAL_MAX_VARS,
                supports=(FormulationKind.QUBO, FormulationKind.ISING),
                all_to_all=True,
                credentialed=True,
                tags=("free", "heuristic", "scales", "no-queue"),
            ),
            BackendCapability(
                id="local.tabu",
                vendor="local",
                name="Tabu search (classical)",
                modality=Modality.CLASSICAL,
                max_qubits=CLASSICAL_MAX_VARS,
                supports=(FormulationKind.QUBO, FormulationKind.ISING),
                all_to_all=True,
                credentialed=True,
                tags=("free", "heuristic", "scales", "no-queue"),
            ),
        ]

    def run(
        self,
        backend: BackendCapability,
        formulation: Formulation,
        need: ResourceNeed,
        policy: Policy,
    ) -> RawResult:
        algo = need.algorithm
        seed = policy.seed

        if backend.id == "local.exact":
            return classical.exact_solve(formulation.Q, formulation.offset)
        if backend.id == "local.sa":
            return classical.simulated_annealing(
                formulation.Q, formulation.offset, seed=seed,
                reads=max(8, min(64, need.shots // 64 or 16)),
            )
        if backend.id == "local.tabu":
            return classical.tabu_search(formulation.Q, formulation.offset, seed=seed)

        # local.sv -- gate-based simulation
        if algo.startswith("qaoa"):
            layers = int(need.notes[0].split("=")[1]) if need.notes and "layers=" in need.notes[0] else 3
            return qaoa.run_qaoa(
                formulation.Q, formulation.offset,
                layers=layers, shots=need.shots, seed=seed, backend_id=backend.id,
            )
        if algo.startswith("vqe"):
            terms = formulation.terms or _qubo_to_terms(formulation)
            return vqe.run_vqe(terms, seed=seed, backend_id=backend.id)
        if algo.startswith("grover"):
            if formulation.predicate is None:
                raise ProviderExecutionError("grover requires an oracle predicate")
            return grover.run_grover(
                formulation.predicate, formulation.num_vars,
                shots=need.shots, seed=seed, backend_id=backend.id,
            )
        raise ProviderExecutionError(f"local.sv cannot run algorithm {algo!r}")


def _qubo_to_terms(f: Formulation) -> list[tuple[float, str]]:
    """Fall back to a Pauli-sum view of a QUBO so VQE can run on it."""
    from ..formulations.qubo import ising_to_pauli_terms, qubo_to_ising

    h, J, const = qubo_to_ising(np.asarray(f.Q), f.offset)
    return ising_to_pauli_terms(h, J, const)
