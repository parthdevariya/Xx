from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import QuantumAlgorithm, QuantumCapability, QuantumProvider
from .service import sync_registry

CAPABILITIES = {
    "qubo": "Quadratic unconstrained binary optimisation",
    "ising": "Ising-model Hamiltonians",
    "pauli_sum": "Weighted sums of Pauli strings (chemistry, physics)",
    "oracle": "Predicate oracle for unstructured search",
    "circuit": "Arbitrary gate circuits",
}

ALGORITHMS = [
    {
        "key": "qaoa", "name": "Quantum Approximate Optimization Algorithm (QAOA)",
        "description": "Variational algorithm alternating a cost Hamiltonian and a mixer; parameters tuned "
                       "by a classical optimiser. Samples low-energy bitstrings of a QUBO.",
        "problem_compatibility": ["max_cut", "tsp", "knapsack", "number_partition", "portfolio", "vertex_cover",
                                  "independent_set", "graph_coloring", "assignment", "feature_selection",
                                  "bin_packing"],
        "input_schema": {"Q": "symmetric n×n matrix", "offset": "float", "layers": "int (p)"},
        "output_schema": {"counts": "bitstring→frequency", "best_bitstring": "str", "best_energy": "float"},
        "backend_requirements": {"formulations": ["qubo", "ising"], "modalities": ["gate"]},
        "resource_requirements": {"qubits": "n (one per binary variable)", "depth": "O(p·|E|)"},
        "execution_config": {"layers": 3, "shots": 2048},
        "known_limitations": [
            "No proven advantage over classical heuristics on current hardware or at simulable sizes.",
            "Penalty-encoded constraints can produce infeasible samples; answers are verified separately.",
            "Local simulation is limited to about 22 qubits.",
        ],
        "benchmark_methodology": "Same QUBO and true objective as the classical baseline; report best feasible "
                                 "objective, feasibility rate, wall time and shots; seed fixed.",
    },
    {
        "key": "vqe", "name": "Variational Quantum Eigensolver (VQE)",
        "description": "Estimates the ground-state energy of a Pauli-sum Hamiltonian with a parameterised ansatz.",
        "problem_compatibility": ["ground_state"],
        "input_schema": {"terms": "[[coeff, pauli_string], ...]"},
        "output_schema": {"expectation": "float", "iterations": "int", "converged": "bool"},
        "backend_requirements": {"formulations": ["pauli_sum"], "modalities": ["gate"]},
        "resource_requirements": {"qubits": "length of Pauli strings"},
        "execution_config": {"optimizer": "COBYLA-like", "max_iterations": 200},
        "known_limitations": ["Ansatz expressivity and barren plateaus limit accuracy.",
                              "Exact diagonalisation is cheaper for small Hamiltonians."],
        "benchmark_methodology": "Compare against exact diagonalisation energy where tractable.",
    },
    {
        "key": "grover", "name": "Grover's search",
        "description": "Amplitude amplification over 2^n candidates with a verifiable predicate oracle.",
        "problem_compatibility": ["search"],
        "input_schema": {"predicate": "callable", "n": "bit width"},
        "output_schema": {"counts": "bitstring→frequency"},
        "backend_requirements": {"formulations": ["oracle"], "modalities": ["gate"]},
        "resource_requirements": {"qubits": "n + ancillas", "iterations": "≈ π/4·√(2^n/M)"},
        "execution_config": {"shots": 1024},
        "known_limitations": ["Quadratic speed-up only, and only with fault-tolerant hardware.",
                              "Oracle construction cost is not included in the speed-up."],
        "benchmark_methodology": "Success probability vs iterations, compared to classical brute force.",
    },
    {
        "key": "quantum_annealing", "name": "Quantum annealing (D-Wave)",
        "description": "Physical annealing of an Ising model on annealer hardware or hybrid solvers.",
        "problem_compatibility": ["max_cut", "tsp", "knapsack", "portfolio", "assignment", "bin_packing"],
        "input_schema": {"Q": "QUBO"}, "output_schema": {"samples": "list", "energies": "list"},
        "backend_requirements": {"formulations": ["qubo", "ising"], "modalities": ["annealer"]},
        "resource_requirements": {"qubits": "n logical, more physical after embedding"},
        "execution_config": {"num_reads": 1000},
        "known_limitations": ["Embedding overhead; analogue noise; benefit over classical is contested."],
        "benchmark_methodology": "Time-to-target and best energy vs simulated annealing on the same QUBO.",
    },
]


def seed_quantum(db: Session) -> None:
    for code, desc in CAPABILITIES.items():
        if db.get(QuantumCapability, code) is None:
            db.add(QuantumCapability(code=code, description=desc))
    for spec in ALGORITHMS:
        if db.scalar(select(QuantumAlgorithm).where(QuantumAlgorithm.key == spec["key"])) is None:
            db.add(QuantumAlgorithm(**spec))
    db.flush()
    sync_registry(db)
    local = db.scalar(select(QuantumProvider).where(QuantumProvider.vendor == "local"))
    if local:
        local.is_active = True
    db.flush()
