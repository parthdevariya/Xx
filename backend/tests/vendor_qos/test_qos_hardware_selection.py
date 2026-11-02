"""Broker decision tests against synthetic credentialed hardware.

The vendor SDKs are not installed in every environment and real credentials
cannot be assumed, so the submission paths cannot be exercised here. The
*decision* logic can be, and it is the part that determines whether a user's
money is spent well. These tests stand in a fake provider whose devices mirror
the real catalog -- an IBM Eagle, an IonQ Aria, a Quantinuum H2, a D-Wave
Advantage -- with credentials present, and assert the broker does the right
thing with them.

What is checked:

* a deep circuit on a noisy device is rejected on fidelity, not merely ranked low
* the budget is a hard ceiling, and free resources are chosen when spending
  is not authorized
* a low-error, all-to-all device wins over a high-qubit-count noisy one when
  accuracy is the priority
* a dense QUBO too large to embed on an annealer is rejected
* priority profiles actually change the outcome
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qos.broker.selector import FIDELITY_FLOOR, NoViableBackend, plan
from qos.formulations.library import TEMPLATES
from qos.intent.parser import parse
from qos.models import (
    BackendCapability,
    FormulationKind,
    Modality,
    Policy,
    RawResult,
)
from qos.providers.base import Provider
from qos.providers.local import LocalProvider
from qos.providers.registry import Registry

GATE_KINDS = (
    FormulationKind.QUBO,
    FormulationKind.ISING,
    FormulationKind.PAULI_SUM,
    FormulationKind.CIRCUIT,
)


class FakeHardware(Provider):
    """A credentialed stand-in for the real vendor catalog."""

    vendor = "fakeqpu"
    display_name = "Fake QPU vendor"
    sdk_modules = ()
    credential_env = ()

    def capabilities(self) -> list[BackendCapability]:
        return [
            # Many qubits, noisy, sparse connectivity -- an Eagle-class device.
            BackendCapability(
                id="fakeqpu.eagle", vendor="fakeqpu", name="Fake Eagle 127q",
                modality=Modality.GATE_QPU, max_qubits=127, supports=GATE_KINDS,
                two_qubit_error=7.0e-3, readout_error=2.0e-2, all_to_all=False,
                max_shots=100_000, cost_per_second_usd=1.60,
                available=True, credentialed=True, est_queue_wait_s=120.0,
                tags=("qpu", "superconducting", "paid"),
            ),
            # Fewer qubits, far better fidelity, all-to-all -- Quantinuum-class.
            BackendCapability(
                id="fakeqpu.h2", vendor="fakeqpu", name="Fake H2 56q trapped ion",
                modality=Modality.GATE_QPU, max_qubits=56, supports=GATE_KINDS,
                two_qubit_error=1.5e-3, readout_error=3.0e-3, all_to_all=True,
                max_shots=10_000, cost_per_shot_usd=0.01,
                available=True, credentialed=True, est_queue_wait_s=60.0,
                tags=("qpu", "trapped-ion", "highest-fidelity", "paid"),
            ),
            # Expensive per shot -- IonQ-class.
            BackendCapability(
                id="fakeqpu.aria", vendor="fakeqpu", name="Fake Aria 25q",
                modality=Modality.GATE_QPU, max_qubits=25, supports=GATE_KINDS,
                two_qubit_error=4.0e-3, readout_error=5.0e-3, all_to_all=True,
                max_shots=10_000, cost_per_shot_usd=0.03, cost_per_task_usd=0.30,
                available=True, credentialed=True, est_queue_wait_s=300.0,
                tags=("qpu", "trapped-ion", "paid"),
            ),
            # Huge but sparse annealer.
            BackendCapability(
                id="fakeqpu.annealer", vendor="fakeqpu", name="Fake annealer 5000q",
                modality=Modality.ANNEALER, max_qubits=5000,
                supports=(FormulationKind.QUBO, FormulationKind.ISING),
                all_to_all=False, max_shots=10_000, cost_per_second_usd=0.19,
                available=True, credentialed=True, est_queue_wait_s=30.0,
                tags=("qpu", "annealer", "paid"),
            ),
        ]

    def run(self, backend, formulation, need, policy) -> RawResult:
        raise AssertionError("these tests must never execute a run")


def _registry() -> Registry:
    return Registry([LocalProvider(), FakeHardware()])


def _maxcut(n: int, density: float = 0.5, seed: int = 0):
    rng = np.random.default_rng(seed)
    edges = [
        [i, j] for i in range(n) for j in range(i + 1, n)
        if rng.random() < density
    ]
    data = {"n": n, "edges": edges}
    return parse("max cut", data, use_llm="never"), TEMPLATES["max_cut"].build(data)


# ==========================================================================

def test_free_resources_chosen_when_spending_not_authorized():
    spec, f = _maxcut(18, 0.4, seed=1)
    p = plan(spec, f, _registry(), Policy(allow_hardware=False))
    assert p.primary.need.est_cost_usd == 0.0
    assert p.primary.backend.vendor == "local"
    # Paid candidates must be rejected with a stated reason, not silently dropped.
    assert any("hardware spending is not enabled" in why for _bid, why in p.rejected)


def test_budget_is_a_hard_ceiling():
    spec, f = _maxcut(40, 0.6, seed=2)
    p = plan(spec, f, _registry(), Policy(allow_hardware=True, max_cost_usd=1.0))
    assert p.primary.need.est_cost_usd <= 1.0 + 1e-9
    for _bid, score, _reason in p.considered:
        assert 0.0 <= score <= 1.0
    over = [why for _b, why in p.rejected if "exceeds budget" in why]
    assert over, "an over-budget candidate should have been rejected by name"


def test_deep_circuit_on_noisy_device_is_rejected_on_fidelity():
    # A dense 40-variable QUBO at p=6 needs thousands of two-qubit gates.
    spec, f = _maxcut(40, 0.9, seed=3)
    p = plan(spec, f, _registry(), Policy(allow_hardware=True, max_cost_usd=10_000))
    fidelity_rejections = [
        why for bid, why in p.rejected
        if "fidelity" in why and "eagle" in bid
    ]
    assert fidelity_rejections, (
        "a dense deep circuit on a 7e-3-error device must be rejected on fidelity"
    )
    assert "too deep for this device" in fidelity_rejections[0]


def test_fidelity_floor_is_actually_enforced_not_just_weighted():
    spec, f = _maxcut(36, 0.95, seed=4)
    p = plan(spec, f, _registry(), Policy(allow_hardware=True, max_cost_usd=10_000))
    # Every surviving gate-QPU candidate must clear the floor.
    for step in [p.primary, *p.fallbacks]:
        if step.backend.modality is Modality.GATE_QPU:
            fid = 1.0
            for note in step.need.notes:
                if note.startswith("expected_fidelity="):
                    fid = float(note.split("=")[1])
            assert fid >= FIDELITY_FLOOR, f"{step.backend.id} below the floor at {fid}"


def test_high_fidelity_device_preferred_over_high_qubit_count():
    # 30 variables: both the Eagle (127q, noisy, sparse) and H2 (56q, clean,
    # all-to-all) can hold it. Accuracy priority must pick the clean one.
    spec, f = _maxcut(30, 0.3, seed=5)
    p = plan(
        spec, f, _registry(),
        Policy(allow_hardware=True, max_cost_usd=10_000, priority="accuracy"),
    )
    gate_steps = [
        s for s in [p.primary, *p.fallbacks]
        if s.backend.modality is Modality.GATE_QPU
    ]
    if gate_steps:
        ranked = sorted(gate_steps, key=lambda s: -s.score)
        assert ranked[0].backend.id == "fakeqpu.h2", (
            f"expected the low-error all-to-all device to rank first, got "
            f"{ranked[0].backend.id}"
        )


def test_dense_problem_too_large_to_embed_is_rejected_from_the_annealer():
    # Dense 400-variable QUBO: each variable's degree far exceeds the hardware
    # graph degree, so the chain-embedded size blows past 5000 physical qubits.
    rng = np.random.default_rng(6)
    n = 400
    Q = rng.normal(size=(n, n))
    Q = (Q + Q.T) / 2
    spec = parse("optimize this", {"Q": Q, "n": n}, use_llm="never")
    from qos.runtime.orchestrator import compile_problem

    f = compile_problem(spec)
    p = plan(spec, f, _registry(), Policy(allow_hardware=True, max_cost_usd=10_000))
    assert p.primary.backend.id != "fakeqpu.annealer", (
        "a dense 400-variable problem must not be routed to a sparse annealer"
    )


def test_sparse_problem_does_reach_the_annealer():
    # A ring graph has degree 2 everywhere, which embeds without chaining and
    # is far too large for exact enumeration or local simulation.
    n = 600
    data = {"n": n, "edges": [[i, (i + 1) % n] for i in range(n)]}
    spec = parse("max cut", data, use_llm="never")
    f = TEMPLATES["max_cut"].build(data)
    p = plan(spec, f, _registry(), Policy(allow_hardware=True, max_cost_usd=10_000,
                                          priority="accuracy"))
    candidates = {s.backend.id for s in [p.primary, *p.fallbacks]}
    assert "fakeqpu.annealer" in candidates, (
        f"a sparse 600-variable QUBO should be an annealer candidate; got {candidates}"
    )


def test_priority_profiles_change_the_decision():
    spec, f = _maxcut(24, 0.35, seed=7)
    pol = dict(allow_hardware=True, max_cost_usd=10_000)
    cheap = plan(spec, f, _registry(), Policy(priority="cheap", **pol))
    fast = plan(spec, f, _registry(), Policy(priority="fast", **pol))
    accuracy = plan(spec, f, _registry(), Policy(priority="accuracy", **pol))
    # Cheap must never pick something costlier than the accuracy pick.
    assert cheap.primary.need.est_cost_usd <= accuracy.primary.need.est_cost_usd + 1e-9
    # Fast must never pick something slower than the accuracy pick.
    assert fast.primary.need.est_runtime_s <= accuracy.primary.need.est_runtime_s + 1e-6


def test_max_wait_excludes_long_queues():
    spec, f = _maxcut(30, 0.3, seed=8)
    # Every fake QPU has a queue of at least 30s; a 10s ceiling must exclude them.
    p = plan(
        spec, f, _registry(),
        Policy(allow_hardware=True, max_cost_usd=10_000, max_wait_s=10.0),
    )
    assert p.primary.need.est_runtime_s <= 10.0
    assert any("exceeds max wait" in why for _b, why in p.rejected)


def test_fallbacks_are_on_distinct_backends():
    spec, f = _maxcut(20, 0.3, seed=9)
    p = plan(spec, f, _registry(), Policy(allow_hardware=True, max_cost_usd=10_000))
    ids = [p.primary.backend.id] + [s.backend.id for s in p.fallbacks]
    assert len(ids) == len(set(ids)), (
        "a fallback on the same device as the primary would retry the same failure"
    )


def test_vendor_restriction_is_respected():
    spec, f = _maxcut(20, 0.3, seed=10)
    p = plan(
        spec, f, _registry(),
        Policy(allow_hardware=True, max_cost_usd=10_000, allow_vendors=("fakeqpu",)),
    )
    assert p.primary.backend.vendor == "fakeqpu"
    for s in p.fallbacks:
        assert s.backend.vendor == "fakeqpu"


def test_cost_estimates_are_finite_and_nonnegative():
    spec, f = _maxcut(25, 0.4, seed=11)
    p = plan(spec, f, _registry(), Policy(allow_hardware=True, max_cost_usd=10_000))
    for step in [p.primary, *p.fallbacks]:
        n = step.need
        assert np.isfinite(n.est_cost_usd) and n.est_cost_usd >= 0, step.backend.id
        assert np.isfinite(n.est_runtime_s) and n.est_runtime_s >= 0, step.backend.id
        assert n.shots > 0, step.backend.id
        assert n.logical_qubits > 0, step.backend.id


def test_impossible_policy_explains_itself():
    spec, f = _maxcut(20, 0.3, seed=12)
    try:
        plan(spec, f, _registry(), Policy(max_cost_usd=0.0, max_wait_s=1e-9))
    except NoViableBackend as e:
        report = e.explain()
        assert "Rejected candidates:" in report
        assert len(e.rejected) > 0
    else:
        raise AssertionError("expected NoViableBackend for an impossible policy")


def _run_all() -> int:
    tests = [
        (n, f) for n, f in sorted(globals().items())
        if n.startswith("test_") and callable(f)
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
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
