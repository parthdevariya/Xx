"""Resource estimation: what each algorithm choice would actually cost.

The broker cannot choose intelligently without knowing the price of each
option, and "price" here is four numbers: qubits, circuit depth, wall time and
dollars. Everything in this module exists to produce those four numbers
*before* anything is submitted.

The estimates are deliberately conservative about noise. A 127-qubit device
with a 7e-3 two-qubit error rate cannot run a circuit with 2000 two-qubit
gates and return signal -- the expected fidelity is (1-7e-3)^2000 ~= 1e-6. The
``expected_fidelity`` function makes that explicit so the broker can reject
hardware that would return noise, which is the single most common way people
waste money on quantum computing.
"""

from __future__ import annotations

import numpy as np

from ..algorithms.qaoa import gate_counts
from ..algorithms.vqe import ansatz_param_count, ansatz_resources
from ..models import (
    BackendCapability,
    Formulation,
    FormulationKind,
    Modality,
    Policy,
    ProblemSpec,
    ResourceNeed,
)
from ..providers.dwave import embedding_overhead
from ..providers.ibm import estimate_transpiled_depth


def expected_fidelity(two_qubit_gates: int, error_rate: float | None,
                      readout_error: float | None, n_qubits: int) -> float:
    """Probability the circuit returns a meaningful (not noise) outcome.

    Simple multiplicative model: each two-qubit gate and each readout
    contributes an independent error channel. Crude, but it captures the
    exponential decay that decides whether a device is usable at a given
    depth, which is what the broker needs.
    """
    if error_rate is None:
        return 1.0
    f = (1.0 - error_rate) ** max(0, two_qubit_gates)
    if readout_error:
        f *= (1.0 - readout_error) ** n_qubits
    return float(max(0.0, min(1.0, f)))


def shots_for(n_vars: int, fidelity: float, base: int = 1024) -> int:
    """Shot budget, inflated when fidelity is low.

    Low fidelity spreads probability mass over wrong answers, so recovering
    the good bitstring needs more samples -- roughly 1/fidelity more.
    """
    scale = 1.0 / max(fidelity, 1e-3)
    shots = int(base * min(16.0, max(1.0, scale)) * max(1.0, n_vars / 16.0))
    return int(min(100_000, max(256, shots)))


def estimate(
    spec: ProblemSpec,
    f: Formulation,
    backend: BackendCapability,
    policy: Policy,
) -> list[ResourceNeed]:
    """Candidate (algorithm, resource) pairs for one backend.

    Returns an empty list when the backend cannot run this formulation at all.
    """
    needs: list[ResourceNeed] = []
    n = f.num_vars

    if not backend.can_run(f):
        return needs

    # ------------------------------------------------------- annealers
    if backend.modality is Modality.ANNEALER:
        if f.kind not in (FormulationKind.QUBO, FormulationKind.ISING):
            return needs
        if backend.id.startswith("dwave.hybrid"):
            phys, chain = n, 1.0
            runtime = max(3.0, n / 2000.0)
            notes = ["hybrid solver handles embedding and classical refinement internally"]
        else:
            degree = 20 if "advantage2" in backend.id else 15
            phys, chain = embedding_overhead(np.asarray(f.Q), degree)
            if phys > backend.max_qubits:
                return needs
            # QPU access time is dominated by annealing time x num_reads.
            reads = min(1000, backend.max_shots)
            runtime = reads * 20e-6 + 0.02
            notes = [f"minor embedding: {phys} physical qubits, chain length ~{chain:.1f}"]
            if chain > 4:
                notes.append("long chains break often; solution quality degrades")
        needs.append(ResourceNeed(
            algorithm="quantum_annealing",
            logical_qubits=n,
            circuit_depth=0,
            shots=min(1000, backend.max_shots),
            circuit_executions=1,
            est_runtime_s=runtime + backend.est_queue_wait_s,
            est_cost_usd=runtime * backend.cost_per_second_usd,
            notes=notes + [f"physical_qubits={phys}"],
        ))
        return needs

    # ------------------------------------------------------- classical
    if backend.modality is Modality.CLASSICAL:
        if backend.id == "local.exact":
            # 2**n enumeration; measured at roughly 20M assignments/second.
            runtime = (2.0**n) / 2e7
            needs.append(ResourceNeed(
                algorithm="exact_enumeration", logical_qubits=n, circuit_depth=0,
                shots=1, est_runtime_s=runtime, est_cost_usd=0.0,
                notes=["certified global optimum"],
            ))
        else:
            algo = "simulated_annealing" if backend.id.endswith("sa") else "tabu_search"
            needs.append(ResourceNeed(
                algorithm=algo, logical_qubits=n, circuit_depth=0, shots=1,
                est_runtime_s=max(0.05, n * n * 2e-5),
                est_cost_usd=0.0,
                notes=["heuristic: no optimality guarantee"],
            ))
        return needs

    # -------------------------------------------------- gate-based targets
    if f.kind == FormulationKind.ORACLE:
        from ..algorithms.grover import optimal_iterations

        iters = optimal_iterations(n, max(1, int(spec.data.get("n_solutions", 1))))
        two_q = iters * 2 * max(1, n - 1)
        fid = expected_fidelity(two_q, backend.two_qubit_error, backend.readout_error, n)
        needs.append(ResourceNeed(
            algorithm="grover",
            logical_qubits=n,
            circuit_depth=iters * (2 * n),
            shots=shots_for(n, fid),
            circuit_executions=1,
            two_qubit_gates=two_q,
            needs_fault_tolerance=fid < 0.1,
            est_runtime_s=_gate_runtime(backend, iters * 2 * n, shots_for(n, fid), 1),
            est_cost_usd=_gate_cost(backend, shots_for(n, fid), 1,
                                    _gate_runtime(backend, iters * 2 * n, shots_for(n, fid), 1)),
            notes=[f"grover iterations={iters}", f"expected_fidelity={fid:.3g}"],
        ))
        return needs

    if f.kind == FormulationKind.PAULI_SUM:
        for layers in (2, 4):
            depth, _gates, two_q = ansatz_resources(n, layers)
            fid = expected_fidelity(two_q, backend.two_qubit_error, backend.readout_error, n)
            # VQE measures each Pauli term separately, and the optimizer loops.
            iters = 40 * ansatz_param_count(n, layers)
            execs = iters * max(1, len(f.terms))
            shots = shots_for(n, fid, base=512)
            rt = _gate_runtime(backend, depth, shots, execs)
            needs.append(ResourceNeed(
                algorithm=f"vqe_l{layers}",
                logical_qubits=n,
                circuit_depth=depth,
                shots=shots,
                circuit_executions=execs,
                two_qubit_gates=two_q,
                needs_fault_tolerance=fid < 0.1,
                est_runtime_s=rt,
                est_cost_usd=_gate_cost(backend, shots, execs, rt),
                notes=[f"layers={layers}", f"pauli_terms={len(f.terms)}",
                       f"expected_fidelity={fid:.3g}"],
            ))
        return needs

    # QUBO / Ising on a gate device -> QAOA at a few depths.
    Q = np.asarray(f.Q)
    for layers in (1, 3, 6):
        depth, _gates, two_q = gate_counts(Q, layers)
        if not backend.all_to_all:
            depth, two_q = estimate_transpiled_depth(Q, layers, backend.all_to_all)
        fid = expected_fidelity(two_q, backend.two_qubit_error, backend.readout_error, n)
        shots = shots_for(n, fid)
        # Parameters are optimized on a simulator, so only the final sampling
        # consumes device time. That is what makes hardware QAOA affordable.
        execs = 1 if backend.modality is Modality.GATE_QPU else 2 * layers * 50
        rt = _gate_runtime(backend, depth, shots, execs)
        needs.append(ResourceNeed(
            algorithm=f"qaoa_p{layers}",
            logical_qubits=n,
            circuit_depth=int(depth),
            shots=shots,
            circuit_executions=execs,
            two_qubit_gates=int(two_q),
            needs_fault_tolerance=fid < 0.05,
            est_runtime_s=rt,
            est_cost_usd=_gate_cost(backend, shots, execs, rt),
            notes=[f"layers={layers}", f"expected_fidelity={fid:.3g}"]
                  + ([] if backend.all_to_all else ["includes SWAP overhead for limited connectivity"]),
        ))
    return needs


def _gate_runtime(backend: BackendCapability, depth: int, shots: int, execs: int) -> float:
    """Wall-clock estimate including queue wait."""
    if backend.modality is Modality.GATE_SIMULATOR:
        # Simulator cost grows with 2**n only inside the provider; here the
        # dominant term is shots x depth of bookkeeping.
        per_exec = 1e-6 * depth * max(1, shots / 1000)
        return backend.est_queue_wait_s + per_exec * execs + 0.05
    # Real devices: ~100us per shot of circuit execution plus per-job overhead.
    per_shot = 1e-4 + depth * 1e-7
    return backend.est_queue_wait_s + execs * (shots * per_shot + 2.0)


def _gate_cost(backend: BackendCapability, shots: int, execs: int, runtime_s: float) -> float:
    """Dollar estimate from the backend's cost model."""
    return (
        execs * backend.cost_per_task_usd
        + execs * shots * backend.cost_per_shot_usd
        + max(0.0, runtime_s - backend.est_queue_wait_s) * backend.cost_per_second_usd
    )
