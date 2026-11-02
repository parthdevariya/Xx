"""Core data contracts shared by every layer of Quantum OS.

The pipeline is a chain of transforms over these types:

    str (user goal)
      -> ProblemSpec    (intent layer: what are we actually solving?)
      -> Formulation     (compiler: QUBO / Hamiltonian / oracle)
      -> ResourceNeed    (estimator: qubits, depth, shots, money, time)
      -> ExecutionPlan   (broker: which backend, which algorithm, what fallback)
      -> RawResult       (runtime: bitstring counts / expectation values)
      -> Solution        (interpreter: domain-level answer + confidence)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


# --------------------------------------------------------------------------
# Problem taxonomy
# --------------------------------------------------------------------------

class ProblemClass(str, Enum):
    """What kind of mathematical object the user's goal reduces to.

    This is the hinge of the whole system: the intent layer's only real job is
    to land the goal in one of these buckets, because the bucket determines
    which formulations, algorithms and hardware are even eligible.
    """

    # Combinatorial optimization expressible as quadratic binary optimization.
    QUBO = "qubo"
    # Ground-state energy of a physical/chemical Hamiltonian.
    GROUND_STATE = "ground_state"
    # Unstructured search over a space with a verifiable predicate.
    SEARCH = "search"
    # Sampling from a hard-to-sample distribution.
    SAMPLING = "sampling"
    # Supervised/unsupervised learning with a quantum feature map or model.
    MACHINE_LEARNING = "machine_learning"
    # Linear algebra: solve Ax=b, eigenvalues, matrix inversion.
    LINEAR_ALGEBRA = "linear_algebra"
    # Numerical integration / expectation under a stochastic model.
    AMPLITUDE_ESTIMATION = "amplitude_estimation"
    # Period finding / factoring / discrete log.
    PERIOD_FINDING = "period_finding"
    # Could not be classified; platform says so rather than guessing.
    UNKNOWN = "unknown"


class Objective(str, Enum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"
    SATISFY = "satisfy"
    ESTIMATE = "estimate"


# --------------------------------------------------------------------------
# Intent layer output
# --------------------------------------------------------------------------

@dataclass
class ProblemSpec:
    """Structured reading of a natural-language goal."""

    raw_goal: str
    problem_class: ProblemClass
    objective: Objective
    # Canonical template name when the goal matched a known pattern
    # (e.g. "max_cut", "tsp", "portfolio"). None => generic formulation.
    template: str | None = None
    # Problem payload: graph edges, distance matrix, asset returns, etc.
    data: dict[str, Any] = field(default_factory=dict)
    # Hard constraints extracted from the goal ("budget under 50k", "<= 3 bins").
    constraints: list[dict[str, Any]] = field(default_factory=list)
    # How sure the intent layer is about this reading, in [0, 1].
    confidence: float = 0.0
    # Human-readable trace of why it was classified this way.
    rationale: str = ""
    # Assumptions the parser made and wants surfaced to the user.
    assumptions: list[str] = field(default_factory=list)
    # Data fields the chosen template needs but the goal did not supply.
    # Non-empty means the platform must ask rather than invent numbers.
    missing_data: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.problem_class is not ProblemClass.UNKNOWN and not self.missing_data

    @property
    def size(self) -> int:
        """Problem size in decision variables, when known."""
        return int(self.data.get("n", 0))


# --------------------------------------------------------------------------
# Compiler output
# --------------------------------------------------------------------------

class FormulationKind(str, Enum):
    QUBO = "qubo"              # Q matrix, minimize x.T @ Q @ x, x in {0,1}^n
    ISING = "ising"            # h, J: minimize sum h_i s_i + sum J_ij s_i s_j
    PAULI_SUM = "pauli_sum"    # list of (coeff, pauli_string)
    ORACLE = "oracle"          # predicate over bitstrings
    CIRCUIT = "circuit"        # explicit gate list


@dataclass
class Formulation:
    """Hardware-agnostic mathematical encoding of the problem."""

    kind: FormulationKind
    num_vars: int
    # QUBO / Ising payload
    Q: Any | None = None                      # numpy array, shape (n, n)
    offset: float = 0.0
    # PAULI_SUM payload
    terms: list[tuple[float, str]] = field(default_factory=list)
    # ORACLE payload: predicate on an int-encoded bitstring
    predicate: Callable[[int], bool] | None = None
    # Decoding metadata: how to turn a bitstring back into a domain answer.
    decode: dict[str, Any] = field(default_factory=dict)
    # Penalty weights used to fold hard constraints into the objective.
    penalties: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Resource estimation + hardware capability
# --------------------------------------------------------------------------

@dataclass
class ResourceNeed:
    """What running this problem is predicted to cost, per algorithm choice."""

    algorithm: str
    logical_qubits: int
    circuit_depth: int
    shots: int
    # Circuit executions including the classical optimization loop.
    circuit_executions: int = 1
    two_qubit_gates: int = 0
    # Does this need error-corrected hardware before it is useful?
    needs_fault_tolerance: bool = False
    est_runtime_s: float = 0.0
    est_cost_usd: float = 0.0
    notes: list[str] = field(default_factory=list)


class Modality(str, Enum):
    """Physical execution modality -- determines what a backend is good at."""

    GATE_SIMULATOR = "gate_simulator"
    GATE_QPU = "gate_qpu"
    ANNEALER = "annealer"
    CLASSICAL = "classical"


@dataclass
class BackendCapability:
    """Static + dynamic description of an execution target.

    The broker scores candidates purely off this struct, which is why adding a
    vendor only requires an adapter that can fill one of these in.
    """

    id: str                       # "local.sv", "ibm.aer", "dwave.advantage"
    vendor: str                   # ibm | aws | azure | dwave | google | local
    name: str
    modality: Modality
    max_qubits: int
    # Formulation kinds this backend can execute.
    supports: tuple[FormulationKind, ...] = ()
    # Noise characteristics; None for ideal simulators.
    two_qubit_error: float | None = None
    readout_error: float | None = None
    t1_us: float | None = None
    max_shots: int = 100_000
    # All-to-all connectivity means no SWAP overhead when transpiling.
    all_to_all: bool = False
    # Cost model
    cost_per_shot_usd: float = 0.0
    cost_per_task_usd: float = 0.0
    cost_per_second_usd: float = 0.0
    # Dynamic state, refreshed by the adapter when credentials are present.
    available: bool = True
    queue_depth: int = 0
    est_queue_wait_s: float = 0.0
    # True when the adapter has live credentials; False => advertised, unusable.
    credentialed: bool = False
    tags: tuple[str, ...] = ()
    # Why this backend cannot be used right now, and what would fix it.
    # Empty when usable. Adapters fill this in so the broker can report the
    # actual blocker -- a missing SDK is a different problem from a missing
    # API token, and telling a user the wrong one wastes their time.
    unavailable_reason: str = ""

    def can_run(self, f: "Formulation") -> bool:
        return f.kind in self.supports and f.num_vars <= self.max_qubits


# --------------------------------------------------------------------------
# Policy: the user's non-negotiables
# --------------------------------------------------------------------------

@dataclass
class Policy:
    """User-level constraints the broker must respect."""

    max_cost_usd: float = 0.0        # 0 => free tier / simulators only
    max_wait_s: float = 300.0
    # "accuracy" favours quality, "cheap" favours cost, "fast" favours latency.
    priority: str = "balanced"
    allow_vendors: tuple[str, ...] = ()    # empty => all
    deny_vendors: tuple[str, ...] = ()
    # Must be opted into explicitly before the broker will spend money.
    allow_hardware: bool = False
    require_classical_baseline: bool = True
    seed: int | None = None
    # Pin the route instead of letting the broker choose. Useful for
    # benchmarking a specific device and for users who want the quantum path
    # even where a classical solver would win on merit.
    force_backend: str | None = None
    force_algorithm: str | None = None

    def vendor_allowed(self, vendor: str) -> bool:
        if self.deny_vendors and vendor in self.deny_vendors:
            return False
        if self.allow_vendors and vendor not in self.allow_vendors:
            return False
        return True


# --------------------------------------------------------------------------
# Broker output
# --------------------------------------------------------------------------

@dataclass
class PlanStep:
    algorithm: str
    backend: BackendCapability
    need: ResourceNeed
    score: float
    reason: str


@dataclass
class ExecutionPlan:
    """Chosen route plus ordered fallbacks."""

    primary: PlanStep
    fallbacks: list[PlanStep] = field(default_factory=list)
    # Every candidate considered, with its score -- surfaced for explainability.
    considered: list[tuple[str, float, str]] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------
# Execution + results
# --------------------------------------------------------------------------

@dataclass
class RawResult:
    """Backend-level output, before domain interpretation."""

    backend_id: str
    algorithm: str
    counts: dict[str, int] = field(default_factory=dict)
    best_bitstring: str | None = None
    best_energy: float | None = None
    expectation: float | None = None
    shots: int = 0
    wall_time_s: float = 0.0
    cost_usd: float = 0.0
    iterations: int = 0
    converged: bool = False
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Solution:
    """Final, domain-level answer handed back to the user."""

    goal: str
    answer: Any                        # decoded, human-meaningful result
    summary: str                       # plain-language readout
    objective_value: float | None = None
    feasible: bool = True
    violations: list[str] = field(default_factory=list)
    # Quality signal: how the quantum result compared to a classical baseline.
    confidence: float = 0.0
    baseline_value: float | None = None
    quantum_advantage: str = "none"    # none | parity | better | worse
    raw: RawResult | None = None
    plan: ExecutionPlan | None = None
    spec: ProblemSpec | None = None
    trace: list[str] = field(default_factory=list)


@dataclass
class Job:
    """A tracked unit of work, so long-running runs can be polled."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    goal: str = ""
    status: str = "pending"            # pending|planning|running|done|failed
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    solution: Solution | None = None
    error: str | None = None
    events: list[tuple[float, str]] = field(default_factory=list)

    def log(self, msg: str) -> None:
        self.events.append((time.time(), msg))
