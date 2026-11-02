"""Correctness tests for Quantum OS.

Runs under pytest (`pytest tests/`) or standalone (`python tests/test_all.py`),
because the platform's only hard dependency is numpy and the test suite should
not be the thing that forces a pytest install.

The tests check properties that actually matter rather than restating the
implementation:

* the simulator reproduces textbook quantum results (Bell, GHZ, Grover, VQE)
* every QUBO encoding's optimum is the true optimum of the original problem,
  verified by independent brute force over the domain (not over the QUBO)
* the broker's hard gates genuinely reject what they claim to reject
* the platform refuses to invent missing problem data
* the platform returns the best answer it found, not merely the chosen route's
"""

from __future__ import annotations

import itertools
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qos.algorithms.classical import exact_solve, simulated_annealing, tabu_search
from qos.algorithms.grover import classical_scan, optimal_iterations, run_grover
from qos.algorithms.qaoa import run_qaoa
from qos.algorithms.vqe import exact_ground_energy, run_vqe
from qos.broker.selector import NoViableBackend, plan
from qos.formulations.library import TEMPLATES
from qos.formulations.qubo import (
    QUBOBuilder,
    ising_to_pauli_terms,
    qubo_energies,
    qubo_to_ising,
)
from qos.intent.parser import parse
from qos.models import FormulationKind, Modality, Policy, ProblemClass
from qos.providers.registry import Registry
from qos.runtime.orchestrator import MissingProblemData, compile_problem, solve
from qos.sim.statevector import StateVector, all_basis_arrays, array_to_bitstring


# ==========================================================================
# Simulator
# ==========================================================================

def test_bell_state():
    sv = StateVector(2).h(0).cx(0, 1)
    p = sv.probabilities()
    assert abs(p[0] - 0.5) < 1e-12 and abs(p[3] - 0.5) < 1e-12
    assert abs(p[1]) < 1e-12 and abs(p[2]) < 1e-12
    assert abs(sv.norm() - 1.0) < 1e-12


def test_ghz_state_is_balanced():
    sv = StateVector(4).h(0)
    for q in range(1, 4):
        sv.cx(0, q)
    p = sv.probabilities()
    assert abs(p[0] - 0.5) < 1e-12
    assert abs(p[15] - 0.5) < 1e-12
    assert abs(p.sum() - 1.0) < 1e-12


def test_unitarity_is_preserved_under_random_circuit():
    rng = np.random.default_rng(0)
    sv = StateVector(6).h_all()
    for _ in range(60):
        kind = rng.integers(0, 4)
        a, b = rng.choice(6, size=2, replace=False)
        if kind == 0:
            sv.rx(int(a), float(rng.uniform(0, np.pi)))
        elif kind == 1:
            sv.rz(int(a), float(rng.uniform(0, np.pi)))
        elif kind == 2:
            sv.cx(int(a), int(b))
        else:
            sv.rzz(int(a), int(b), float(rng.uniform(0, np.pi)))
    assert abs(sv.norm() - 1.0) < 1e-10


def test_x_gate_flips_the_right_qubit():
    # Bitstring position q must be qubit q.
    for q in range(4):
        sv = StateVector(4).x(q)
        idx = int(np.argmax(sv.probabilities()))
        assert sv.bitstring(idx)[q] == "1"
        assert sv.bitstring(idx).count("1") == 1


def test_rzz_phase_matches_analytic_value():
    # |00> has ZZ parity +1 -> phase exp(-i*theta/2)
    theta = 0.7
    sv = StateVector(2)
    sv.rzz(0, 1, theta)
    assert abs(sv.state[0] - np.exp(-1j * theta / 2)) < 1e-12
    # |01> has parity -1 -> phase exp(+i*theta/2)
    sv = StateVector(2).x(0)
    sv.rzz(0, 1, theta)
    assert abs(sv.state[1] - np.exp(1j * theta / 2)) < 1e-12


# ==========================================================================
# Grover
# ==========================================================================

def test_grover_finds_the_marked_state():
    pred = lambda x: x == 37
    r = run_grover(pred, 7, seed=1)
    idx = sum(1 << q for q, c in enumerate(r.best_bitstring) if c == "1")
    assert idx == 37
    assert r.meta["success_probability"] > 0.9


def test_grover_iteration_count_follows_the_sqrt_rule():
    # pi/4 * sqrt(N) for a single solution.
    for n in (6, 8, 10, 12):
        expected = round(math.pi / 4 * math.sqrt(2**n))
        assert abs(optimal_iterations(n, 1) - expected) <= 1


def test_grover_reports_no_solution_rather_than_guessing():
    r = run_grover(lambda x: False, 5, seed=0)
    assert r.error is not None
    assert r.best_bitstring is None


def test_grover_uses_fewer_oracle_calls_than_scanning():
    pred = lambda x: x % 64 == 13
    g = run_grover(pred, 10, seed=2)
    c = classical_scan(pred, 10)
    assert g.iterations < c.iterations


# ==========================================================================
# VQE
# ==========================================================================

def test_vqe_matches_exact_diagonalization_on_two_qubit_hamiltonian():
    h = [(-1.05, "II"), (0.398, "IZ"), (-0.398, "ZI"), (-0.011, "ZZ"), (0.181, "XX")]
    exact = exact_ground_energy(h)
    got = run_vqe(h, layers=2, seed=1).best_energy
    assert abs(got - exact) < 1e-5, f"vqe {got} vs exact {exact}"


def test_vqe_never_goes_below_the_true_ground_state():
    # A variational bound: no ansatz can beat the true minimum.
    terms = [(-1.0, "ZZI"), (-1.0, "IZZ"), (-0.6, "XII"), (-0.6, "IXI"), (-0.6, "IIX")]
    exact = exact_ground_energy(terms)
    got = run_vqe(terms, layers=3, seed=4).best_energy
    assert got >= exact - 1e-8


# ==========================================================================
# QUBO algebra
# ==========================================================================

def test_qubo_to_ising_preserves_energy_ordering():
    rng = np.random.default_rng(3)
    n = 7
    Q = rng.normal(size=(n, n))
    Q = (Q + Q.T) / 2
    h, J, const = qubo_to_ising(Q, 0.0)
    X = all_basis_arrays(n)
    qubo_e = qubo_energies(Q, X, 0.0)
    # Ising energy with s = 1 - 2x
    S = 1.0 - 2.0 * X
    ising_e = S @ h + np.einsum("ij,jk,ik->i", S, J, S) + const
    assert np.allclose(qubo_e, ising_e, atol=1e-9)


def test_pauli_terms_reproduce_the_qubo_diagonal():
    rng = np.random.default_rng(5)
    n = 5
    Q = rng.normal(size=(n, n))
    Q = (Q + Q.T) / 2
    h, J, const = qubo_to_ising(Q, 0.0)
    terms = ising_to_pauli_terms(h, J, const)
    # Every term is diagonal, so energy of basis state = sum of signed coeffs.
    X = all_basis_arrays(n)
    expected = qubo_energies(Q, X, 0.0)
    got = np.zeros(len(X))
    for i, row in enumerate(X):
        total = 0.0
        for coeff, pauli in terms:
            sign = 1.0
            for q, ch in enumerate(pauli):
                if ch == "Z" and row[q] == 1:
                    sign *= -1.0
            total += coeff * sign
        got[i] = total
    assert np.allclose(got, expected, atol=1e-9)


def test_one_hot_penalty_is_minimized_exactly_by_valid_assignments():
    b = QUBOBuilder(4)
    b.penalize_one_hot([0, 1, 2, 3], 1.0)
    f = b.build()
    X = all_basis_arrays(4)
    E = qubo_energies(f.Q, X, f.offset)
    valid = X.sum(axis=1) == 1
    assert np.allclose(E[valid], 0.0, atol=1e-9)
    assert (E[~valid] > 1e-9).all()


def test_inequality_slack_admits_exactly_the_feasible_sums():
    # x0 + 2*x1 <= 2, with slack bits
    from qos.formulations.qubo import slack_bits_needed

    ns = slack_bits_needed(2)
    b = QUBOBuilder(2 + ns)
    b.penalize_inequality_leq([0, 1], [1.0, 2.0], 2.0, 1.0, n_slack=ns)
    f = b.build()
    X = all_basis_arrays(f.num_vars)
    E = qubo_energies(f.Q, X, f.offset)
    for row, e in zip(X, E):
        total = row[0] * 1 + row[1] * 2
        if e < 1e-9:                      # zero penalty => claimed feasible
            assert total <= 2


# ==========================================================================
# Template encodings: QUBO optimum == true domain optimum
# ==========================================================================

def _solve_template_exactly(name: str, data: dict):
    t = TEMPLATES[name]
    f = t.build(data)
    X = all_basis_arrays(f.num_vars)
    E = qubo_energies(f.Q, X, f.offset)
    best = int(np.argmin(E))
    ans = t.decode(array_to_bitstring(X[best]), data)
    return t, ans, t.verify(ans, data), t.objective(ans, data)


def test_maxcut_encoding_finds_the_true_max_cut():
    data = {"n": 6, "edges": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 0], [0, 3]]}
    _t, _ans, chk, obj = _solve_template_exactly("max_cut", data)
    # Brute force the domain objective independently.
    best = 0
    for bits in itertools.product([0, 1], repeat=6):
        cut = sum(1 for i, j in [tuple(e) for e in data["edges"]] if bits[i] != bits[j])
        best = max(best, cut)
    assert chk.feasible
    assert obj == best, f"encoding gave {obj}, true max cut is {best}"


def test_tsp_encoding_finds_the_true_shortest_tour():
    D = np.array([[0, 12, 19, 8], [12, 0, 9, 17], [19, 9, 0, 14], [8, 17, 14, 0]], dtype=float)
    data = {"distances": D.tolist()}
    _t, ans, chk, obj = _solve_template_exactly("tsp", data)
    true_best = min(
        sum(D[p[i], p[(i + 1) % 4]] for i in range(4))
        for p in itertools.permutations(range(4))
    )
    assert chk.feasible, chk.violations
    assert abs(obj - true_best) < 1e-9, f"encoding {obj} vs true {true_best}"
    assert sorted(ans["tour"]) == [0, 1, 2, 3]


def test_knapsack_encoding_respects_capacity_and_maximizes_value():
    data = {"values": [10, 8, 6, 4], "weights": [5, 4, 3, 2], "capacity": 9}
    _t, ans, chk, obj = _solve_template_exactly("knapsack", data)
    best = 0
    for r in range(5):
        for combo in itertools.combinations(range(4), r):
            if sum(data["weights"][i] for i in combo) <= 9:
                best = max(best, sum(data["values"][i] for i in combo))
    assert chk.feasible
    assert ans["total_weight"] <= 9
    assert obj == best


def test_assignment_encoding_finds_the_optimal_matching():
    C = np.array([[4, 2, 8], [4, 3, 7], [3, 1, 6]], dtype=float)
    data = {"costs": C.tolist()}
    _t, _ans, chk, obj = _solve_template_exactly("assignment", data)
    true_best = min(
        sum(C[a, p[a]] for a in range(3)) for p in itertools.permutations(range(3))
    )
    assert chk.feasible
    assert abs(obj - true_best) < 1e-9


def test_graph_coloring_encoding_finds_a_proper_coloring():
    data = {"n": 4, "k": 3, "edges": [[0, 1], [1, 2], [2, 3], [3, 0], [0, 2]]}
    _t, ans, chk, obj = _solve_template_exactly("graph_coloring", data)
    assert chk.feasible, chk.violations
    assert obj == 0, "a proper 3-coloring of this graph exists"
    for i, j in [tuple(e) for e in data["edges"]]:
        assert ans["colors"][i] != ans["colors"][j]


def test_number_partition_encoding_finds_the_minimum_difference():
    data = {"numbers": [8, 5, 4, 3, 3, 2, 1]}
    _t, ans, _chk, obj = _solve_template_exactly("number_partition", data)
    total = sum(data["numbers"])
    best = min(
        abs(total - 2 * sum(c))
        for r in range(len(data["numbers"]) + 1)
        for c in itertools.combinations(data["numbers"], r)
    )
    assert abs(obj - best) < 1e-9
    assert abs(ans["sum_1"] + ans["sum_2"] - total) < 1e-9


def test_independent_set_encoding_respects_conflicts():
    data = {"n": 6, "edges": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]]}
    _t, ans, chk, obj = _solve_template_exactly("independent_set", data)
    assert chk.feasible
    assert obj == 3
    sel = set(ans["selected"])
    for i, j in [tuple(e) for e in data["edges"]]:
        assert not (i in sel and j in sel)


def test_vertex_cover_encoding_covers_every_edge():
    data = {"n": 5, "edges": [[0, 1], [1, 2], [2, 3], [3, 4]]}
    _t, ans, chk, obj = _solve_template_exactly("vertex_cover", data)
    assert chk.feasible
    assert obj == 2
    cover = set(ans["cover"])
    for i, j in [tuple(e) for e in data["edges"]]:
        assert i in cover or j in cover


def test_every_template_builds_a_wellformed_qubo():
    cases = {
        "max_cut": {"n": 4, "edges": [[0, 1], [1, 2]]},
        "tsp": {"distances": [[0, 1, 2], [1, 0, 3], [2, 3, 0]]},
        "knapsack": {"values": [3, 2], "weights": [2, 1], "capacity": 2},
        "number_partition": {"numbers": [3, 2, 1]},
        "portfolio": {"returns": [0.1, 0.2], "budget": 1},
        "vertex_cover": {"n": 3, "edges": [[0, 1]]},
        "independent_set": {"n": 3, "edges": [[0, 1]]},
        "graph_coloring": {"n": 3, "k": 2, "edges": [[0, 1]]},
        "assignment": {"costs": [[1, 2], [3, 4]]},
        "feature_selection": {"relevance": [0.5, 0.4], "k": 1},
        "bin_packing": {"sizes": [2, 2], "capacity": 2, "bins": 2},
    }
    assert set(cases) == set(TEMPLATES), "a template is missing test coverage"
    for name, data in cases.items():
        f = TEMPLATES[name].build(data)
        assert f.kind is FormulationKind.QUBO
        assert f.num_vars > 0
        assert f.Q.shape == (f.num_vars, f.num_vars)
        assert np.allclose(f.Q, f.Q.T), f"{name}: Q must be symmetric"
        assert np.isfinite(f.Q).all(), f"{name}: Q has non-finite entries"


# ==========================================================================
# Classical solvers
# ==========================================================================

def test_exact_solve_finds_the_global_minimum():
    rng = np.random.default_rng(7)
    Q = rng.normal(size=(10, 10))
    Q = (Q + Q.T) / 2
    r = exact_solve(Q)
    X = all_basis_arrays(10)
    assert abs(r.best_energy - qubo_energies(Q, X).min()) < 1e-9


def test_heuristics_never_beat_the_proven_optimum():
    rng = np.random.default_rng(11)
    Q = rng.normal(size=(12, 12))
    Q = (Q + Q.T) / 2
    best = exact_solve(Q).best_energy
    for r in (simulated_annealing(Q, seed=1), tabu_search(Q, seed=1)):
        assert r.best_energy >= best - 1e-9, f"{r.algorithm} claims below-optimal energy"


def test_heuristic_energy_matches_a_recomputation_of_its_own_bitstring():
    # Guards the incremental delta-energy bookkeeping in both solvers.
    rng = np.random.default_rng(13)
    Q = rng.normal(size=(14, 14))
    Q = (Q + Q.T) / 2
    for r in (simulated_annealing(Q, seed=2), tabu_search(Q, seed=2)):
        x = np.array([1.0 if c == "1" else 0.0 for c in r.best_bitstring])
        assert abs(float(x @ Q @ x) - r.best_energy) < 1e-7, r.algorithm


# ==========================================================================
# QAOA
# ==========================================================================

def test_qaoa_reaches_the_optimum_on_small_maxcut():
    data = {"n": 8, "edges": [[i, (i + 1) % 8] for i in range(8)] + [[0, 4], [2, 6]]}
    f = TEMPLATES["max_cut"].build(data)
    exact = exact_solve(f.Q, f.offset).best_energy
    r = run_qaoa(f.Q, f.offset, layers=3, shots=4096, seed=7, restarts=2)
    assert abs(r.best_energy - exact) < 1e-9


def test_qaoa_energy_is_consistent_with_its_reported_bitstring():
    f = TEMPLATES["max_cut"].build({"n": 6, "edges": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]]})
    r = run_qaoa(f.Q, f.offset, layers=2, shots=2048, seed=3, restarts=1)
    x = np.array([1.0 if c == "1" else 0.0 for c in r.best_bitstring])
    assert abs(float(x @ f.Q @ x + f.offset) - r.best_energy) < 1e-9


def test_qaoa_reports_hardware_gate_counts():
    f = TEMPLATES["max_cut"].build({"n": 6, "edges": [[0, 1], [1, 2], [2, 3]]})
    r = run_qaoa(f.Q, f.offset, layers=2, shots=256, seed=1, restarts=1)
    # Three edges, two layers, two CNOTs per RZZ.
    assert r.meta["two_qubit_gates"] == 3 * 2 * 2
    assert r.meta["circuit_depth"] > 0


# ==========================================================================
# Intent parsing
# ==========================================================================

def test_parser_identifies_templates_from_phrasing():
    cases = [
        ("find the shortest route visiting every delivery stop", "tsp"),
        ("split this network into two groups maximizing edges between them", "max_cut"),
        ("which items give the most value within my weight limit", "knapsack"),
        ("pick the best portfolio of stocks by risk-adjusted return", "portfolio"),
        ("assign each worker exactly one task at minimum cost", "assignment"),
        ("select features with the highest relevance", "feature_selection"),
        ("choose the largest set of mutually compatible bookings", "independent_set"),
    ]
    for goal, expected in cases:
        spec = parse(goal, use_llm="never")
        assert spec.template == expected, f"{goal!r} -> {spec.template}, expected {expected}"


def test_parser_reads_numbers_out_of_the_goal_text():
    spec = parse("split these numbers into two equal groups: 8, 5, 4, 3, 3, 2", use_llm="never")
    assert spec.template == "number_partition"
    assert spec.data["numbers"] == [8, 5, 4, 3, 3, 2]
    assert not spec.missing_data


def test_parser_reports_missing_data_instead_of_inventing_it():
    spec = parse("find the shortest route for my delivery trucks", use_llm="never")
    assert spec.template == "tsp"
    assert spec.missing_data
    assert any("distances" in m for m in spec.missing_data)
    assert "distances" not in spec.data


def test_parser_infers_template_from_data_shape():
    spec = parse("solve this", {"distances": [[0, 1], [1, 0]]}, use_llm="never")
    assert spec.template == "tsp"


def test_parser_extracts_cardinality_constraints():
    spec = parse(
        "pick 3 assets with the best return",
        {"returns": [0.1, 0.2, 0.3, 0.4]},
        use_llm="never",
    )
    assert spec.data.get("budget") == 3


def test_unknown_goal_is_flagged_not_guessed():
    spec = parse("write me a poem about the ocean", use_llm="never")
    assert spec.problem_class is ProblemClass.UNKNOWN
    assert spec.confidence == 0.0


# ==========================================================================
# Broker
# ==========================================================================

def test_broker_rejects_backends_with_too_few_qubits():
    reg = Registry()
    f = TEMPLATES["max_cut"].build({"n": 30, "edges": [[i, i + 1] for i in range(29)]})
    spec = parse("max cut", {"n": 30}, use_llm="never")
    p = plan(spec, f, reg, Policy())
    reasons = dict(p.rejected)
    assert any("qubits" in r for r in reasons.values())
    # local.sv caps at 22 qubits, so a 30-variable problem must not land there.
    assert p.primary.backend.id != "local.sv"


def test_broker_refuses_to_spend_money_unless_allowed():
    reg = Registry()
    f = TEMPLATES["max_cut"].build({"n": 10, "edges": [[0, 1], [1, 2]]})
    spec = parse("max cut", {"n": 10}, use_llm="never")
    p = plan(spec, f, reg, Policy(allow_hardware=False))
    assert p.primary.need.est_cost_usd == 0.0
    for _bid, score, _reason in p.considered:
        assert score <= 1.0


def test_broker_prefers_exact_certification_when_it_is_cheap():
    reg = Registry()
    f = TEMPLATES["max_cut"].build({"n": 8, "edges": [[0, 1], [1, 2], [2, 3]]})
    spec = parse("max cut", {"n": 8}, use_llm="never")
    p = plan(spec, f, reg, Policy(priority="accuracy"))
    assert p.primary.algorithm == "exact_enumeration"


def test_broker_raises_when_policy_admits_nothing():
    reg = Registry()
    f = TEMPLATES["max_cut"].build({"n": 10, "edges": [[0, 1]]})
    spec = parse("max cut", {"n": 10}, use_llm="never")
    try:
        plan(spec, f, reg, Policy(deny_vendors=("local", "ibm", "aws", "azure", "dwave", "google")))
    except NoViableBackend as e:
        assert e.rejected
        assert "vendor excluded" in e.explain()
    else:
        raise AssertionError("expected NoViableBackend")


def test_broker_honours_a_pinned_backend():
    reg = Registry()
    f = TEMPLATES["max_cut"].build({"n": 10, "edges": [[0, 1], [1, 2], [2, 3]]})
    spec = parse("max cut", {"n": 10}, use_llm="never")
    p = plan(spec, f, reg, Policy(force_backend="local.sv", force_algorithm="qaoa"))
    assert p.primary.backend.id == "local.sv"
    assert p.primary.algorithm.startswith("qaoa")


def test_every_catalogued_backend_has_a_coherent_cost_model():
    reg = Registry()
    for c in reg.capabilities():
        assert c.max_qubits > 0, c.id
        assert c.cost_per_shot_usd >= 0 and c.cost_per_second_usd >= 0, c.id
        if c.modality is Modality.CLASSICAL or "free" in c.tags:
            assert c.cost_per_shot_usd == 0.0, f"{c.id} tagged free but charges per shot"
        if c.two_qubit_error is not None:
            assert 0 < c.two_qubit_error < 1, c.id


def test_local_provider_is_always_usable():
    reg = Registry()
    usable = {c.id for c in reg.usable()}
    assert {"local.sv", "local.exact", "local.sa", "local.tabu"} <= usable


# ==========================================================================
# End-to-end
# ==========================================================================

def test_solve_end_to_end_returns_the_optimal_tour():
    D = [[0, 12, 19, 8], [12, 0, 9, 17], [19, 9, 0, 14], [8, 17, 14, 0]]
    sol = solve(
        "find the shortest round trip visiting every stop",
        {"distances": D},
        policy=Policy(seed=5),
    )
    Dn = np.array(D, dtype=float)
    true_best = min(
        sum(Dn[p[i], p[(i + 1) % 4]] for i in range(4))
        for p in itertools.permutations(range(4))
    )
    assert sol.feasible
    assert abs(sol.objective_value - true_best) < 1e-9
    assert sorted(sol.answer["tour"]) == [0, 1, 2, 3]


def test_solve_refuses_to_invent_missing_data():
    try:
        solve("find the best route for my vans", use_llm="never")
    except MissingProblemData as e:
        assert "distances" in str(e)
    else:
        raise AssertionError("expected MissingProblemData")


def test_dry_run_estimates_without_executing():
    sol = solve(
        "split this network into two groups",
        {"n": 10, "edges": [[i, (i + 1) % 10] for i in range(10)]},
        policy=Policy(seed=1),
        dry_run=True,
    )
    assert "would_run" in sol.answer
    assert sol.answer["estimated_cost_usd"] == 0.0
    assert sol.raw is None


def test_solve_returns_the_best_answer_found_not_just_the_chosen_route():
    # Pinning a weak route must not stop the platform returning the better
    # answer its baseline found.
    D = [[0, 12, 19, 8, 15], [12, 0, 9, 17, 22], [19, 9, 0, 14, 7],
         [8, 17, 14, 0, 11], [15, 22, 7, 11, 0]]
    sol = solve(
        "shortest round trip visiting every stop",
        {"distances": D},
        policy=Policy(seed=11, force_backend="local.sa"),
    )
    Dn = np.array(D, dtype=float)
    true_best = min(
        sum(Dn[p[i], p[(i + 1) % 5]] for i in range(5))
        for p in itertools.permutations(range(5))
    )
    assert sol.feasible
    assert abs(sol.objective_value - true_best) < 1e-9, (
        f"platform returned {sol.objective_value}, but had {true_best} available"
    )


def test_solution_trace_records_the_decision_path():
    sol = solve(
        "pick 2 assets with the best risk-adjusted return",
        {"returns": [0.1, 0.2, 0.15, 0.05], "budget": 2},
        policy=Policy(seed=2),
    )
    joined = " ".join(sol.trace)
    assert "intent:" in joined
    assert "compiled to" in joined
    assert "plan:" in joined


def test_compile_rejects_a_search_problem_without_a_predicate():
    spec = parse("find a bitstring satisfying the condition", use_llm="never")
    spec.data.pop("predicate", None)
    spec.missing_data = []
    try:
        compile_problem(spec)
    except ValueError as e:
        assert "predicate" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_search_problem_runs_through_the_oracle_path():
    sol = solve(
        "find an input satisfying the predicate",
        {"predicate": lambda x: x == 21, "n": 6},
        policy=Policy(seed=1, force_backend="local.sv"),
    )
    idx = sum(1 << q for q, c in enumerate(sol.answer["bitstring"]) if c == "1")
    assert idx == 21


def test_ground_state_problem_runs_through_the_vqe_path():
    terms = [[-1.05, "II"], [0.398, "IZ"], [-0.398, "ZI"], [-0.011, "ZZ"], [0.181, "XX"]]
    sol = solve(
        "find the ground state energy of this hamiltonian",
        {"terms": terms},
        policy=Policy(seed=1),
    )
    exact = exact_ground_energy([(c, p) for c, p in terms])
    assert abs(sol.objective_value - exact) < 1e-4


# ==========================================================================
# Runner
# ==========================================================================

def _run_all() -> int:
    tests = [
        (name, fn) for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as e:
            failed.append((name, e))
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print()
    print(f"{passed}/{len(tests)} passed")
    if failed:
        print("\nfailures:")
        for name, e in failed:
            print(f"  {name}: {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
