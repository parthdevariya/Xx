"""Goal recognition patterns: natural language -> problem template.

The matcher is keyword-and-phrase based and runs with no network and no model.
That is a deliberate floor, not a placeholder: pattern matching on an explicit
vocabulary is auditable, instant, free, and for the overwhelming majority of
real requests ("pick the best 5 of these 20 assets", "route this van through
these stops") it lands the right template. The LLM parser in ``parser.py``
handles everything else and fills in data extraction.

Each pattern declares which data fields its template requires, so the parser
can tell the user exactly what is missing instead of fabricating inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Objective, ProblemClass


@dataclass
class Pattern:
    template: str
    problem_class: ProblemClass
    objective: Objective
    # Any one of these phrases is a strong signal.
    strong: tuple[str, ...] = ()
    # Supporting words; several together add confidence.
    weak: tuple[str, ...] = ()
    # Data keys the template's build() needs.
    requires: tuple[str, ...] = ()
    # Human description of each required field, for the "what's missing" message.
    field_help: dict[str, str] = field(default_factory=dict)
    # Plain-language description of what will be solved.
    reads_as: str = ""


PATTERNS: list[Pattern] = [
    Pattern(
        template="tsp",
        problem_class=ProblemClass.QUBO,
        objective=Objective.MINIMIZE,
        strong=("travelling salesman", "traveling salesman", "tsp", "shortest route",
                "shortest tour", "delivery route", "visit every", "visit all",
                "route my", "optimal route", "round trip"),
        weak=("route", "tour", "cities", "stops", "locations", "deliveries",
              "truck", "van", "driver", "itinerary", "mileage"),
        requires=("distances",),
        field_help={"distances": "a square distance/time matrix between every pair of stops"},
        reads_as="shortest round trip visiting every location once",
    ),
    Pattern(
        template="max_cut",
        problem_class=ProblemClass.QUBO,
        objective=Objective.MAXIMIZE,
        strong=("max cut", "maxcut", "maximum cut", "split the graph",
                "partition the network", "two groups", "cut the graph"),
        weak=("graph", "network", "edges", "nodes", "partition", "split",
              "community", "divide"),
        requires=("n", "edges"),
        field_help={"n": "number of nodes", "edges": "list of [i, j] or [i, j, weight] edges"},
        reads_as="split a network into two groups maximizing the connections between them",
    ),
    Pattern(
        template="knapsack",
        problem_class=ProblemClass.QUBO,
        objective=Objective.MAXIMIZE,
        strong=("knapsack", "fit in the budget", "maximize value within",
                "most value", "within capacity", "within the weight limit"),
        weak=("budget", "capacity", "weight", "value", "items", "pack",
              "limit", "afford", "select items"),
        requires=("values", "weights", "capacity"),
        field_help={
            "values": "value of each item",
            "weights": "weight/cost of each item",
            "capacity": "the limit the total weight must not exceed",
        },
        reads_as="most valuable set of items that fits the capacity limit",
    ),
    Pattern(
        template="portfolio",
        problem_class=ProblemClass.QUBO,
        objective=Objective.MAXIMIZE,
        strong=("portfolio", "asset selection", "which stocks", "invest in",
                "risk-adjusted", "mean variance", "mean-variance"),
        weak=("assets", "stocks", "returns", "risk", "covariance", "invest",
              "holdings", "securities", "diversify"),
        requires=("returns",),
        field_help={
            "returns": "expected return per asset",
            "covariance": "covariance matrix between assets (optional, defaults to independent)",
            "budget": "exact number of positions to hold (optional)",
        },
        reads_as="asset basket balancing expected return against risk",
    ),
    Pattern(
        template="number_partition",
        problem_class=ProblemClass.QUBO,
        objective=Objective.MINIMIZE,
        strong=("number partition", "split these numbers", "two equal groups",
                "equal halves", "balance the sums", "divide into two equal",
                "even split"),
        weak=("partition", "split", "numbers", "equal", "balance", "halves"),
        requires=("numbers",),
        field_help={"numbers": "the list of numbers to split"},
        reads_as="split a list of numbers into two groups with equal sums",
    ),
    Pattern(
        template="vertex_cover",
        problem_class=ProblemClass.QUBO,
        objective=Objective.MINIMIZE,
        strong=("vertex cover", "minimum cover", "cover every edge",
                "monitor every", "cover all connections", "sensor placement"),
        weak=("cover", "monitor", "guard", "watch", "edges", "coverage"),
        requires=("n", "edges"),
        field_help={"n": "number of nodes", "edges": "list of [i, j] edges to cover"},
        reads_as="fewest nodes that together touch every edge",
    ),
    Pattern(
        template="independent_set",
        problem_class=ProblemClass.QUBO,
        objective=Objective.MAXIMIZE,
        strong=("independent set", "maximum independent", "no two conflict",
                "non-conflicting", "without conflicts", "mutually compatible",
                "largest compatible"),
        weak=("conflict", "compatible", "incompatible", "clash", "exclusive",
              "select", "largest set"),
        requires=("n", "edges"),
        field_help={"n": "number of candidates",
                    "edges": "list of [i, j] conflict pairs"},
        reads_as="largest set of items with no conflicting pair",
    ),
    Pattern(
        template="graph_coloring",
        problem_class=ProblemClass.QUBO,
        objective=Objective.SATISFY,
        strong=("graph coloring", "graph colouring", "color the", "colour the",
                "assign timeslots", "exam timetable", "frequency assignment",
                "no two adjacent", "register allocation"),
        weak=("color", "colour", "timeslot", "schedule", "frequency", "shift",
              "rooms", "classes", "conflict"),
        requires=("n", "edges"),
        field_help={"n": "number of items to label", "k": "number of labels available",
                    "edges": "list of [i, j] pairs that must differ"},
        reads_as="assign labels so no two conflicting items share a label",
    ),
    Pattern(
        template="assignment",
        problem_class=ProblemClass.QUBO,
        objective=Objective.MINIMIZE,
        strong=("assignment problem", "assign workers", "match workers",
                "allocate tasks", "assign each", "match each", "one task each",
                "job assignment", "matching problem"),
        weak=("assign", "allocate", "match", "workers", "agents", "tasks",
              "jobs", "machines", "crew", "staff"),
        requires=("costs",),
        field_help={"costs": "cost matrix [agent][task]"},
        reads_as="match agents to tasks one-for-one at minimum total cost",
    ),
    Pattern(
        template="feature_selection",
        problem_class=ProblemClass.QUBO,
        objective=Objective.MAXIMIZE,
        strong=("feature selection", "select features", "which features",
                "best predictors", "reduce dimensionality", "pick variables"),
        weak=("features", "predictors", "variables", "columns", "relevance",
              "redundancy", "correlation", "model inputs"),
        requires=("relevance",),
        field_help={
            "relevance": "relevance score per feature (e.g. correlation with the target)",
            "redundancy": "pairwise redundancy matrix (optional)",
            "k": "how many features to keep (optional)",
        },
        reads_as="most informative, least redundant subset of features",
    ),
    Pattern(
        template="bin_packing",
        problem_class=ProblemClass.QUBO,
        objective=Objective.MINIMIZE,
        strong=("bin packing", "pack into", "load balancing", "distribute across",
                "balance the load", "split across servers", "spread evenly"),
        weak=("bins", "containers", "trucks", "servers", "pack", "distribute",
              "balance", "capacity", "load"),
        requires=("sizes", "capacity"),
        field_help={
            "sizes": "size of each item",
            "capacity": "capacity of each bin",
            "bins": "how many bins are available",
        },
        reads_as="distribute items across bins without exceeding capacity",
    ),
    Pattern(
        template=None,
        problem_class=ProblemClass.SEARCH,
        objective=Objective.SATISFY,
        strong=("find a value such that", "search for an input", "find the input",
                "brute force search", "find x where", "satisfying assignment",
                "preimage", "find a bitstring"),
        weak=("search", "find", "satisfy", "predicate", "condition", "inverse"),
        requires=("predicate", "n"),
        field_help={"predicate": "a Python callable taking an integer and returning bool",
                    "n": "number of bits in the search space"},
        reads_as="unstructured search for an input satisfying a predicate",
    ),
    Pattern(
        template=None,
        problem_class=ProblemClass.GROUND_STATE,
        objective=Objective.MINIMIZE,
        strong=("ground state", "ground-state energy", "lowest energy",
                "molecular energy", "hamiltonian", "binding energy",
                "electronic structure", "spin chain"),
        weak=("energy", "molecule", "atom", "orbital", "spin", "ising model",
              "quantum chemistry", "eigenvalue"),
        requires=("terms",),
        field_help={"terms": "Hamiltonian as a list of [coefficient, pauli_string] pairs"},
        reads_as="lowest eigenvalue of a given Hamiltonian",
    ),
]


# Words that, in isolation, indicate the user wants optimization of some kind
# but give no template. Used to pick a generic QUBO path when data is supplied
# directly as a Q matrix.
GENERIC_OPTIMIZATION = (
    "optimize", "optimise", "minimize", "minimise", "maximize", "maximise",
    "best combination", "best configuration", "optimal", "qubo", "ising",
)


def score_pattern(text: str, p: Pattern) -> float:
    """Confidence that ``text`` is asking for pattern ``p``, in [0, 1]."""
    t = text.lower()
    score = 0.0
    strong_hits = sum(1 for s in p.strong if s in t)
    weak_hits = sum(1 for w in p.weak if w in t)
    if strong_hits:
        score += 0.62 + 0.10 * min(2, strong_hits - 1)
    score += min(0.30, 0.075 * weak_hits)
    return min(1.0, score)


def best_patterns(text: str, top: int = 3) -> list[tuple[Pattern, float]]:
    scored = [(p, score_pattern(text, p)) for p in PATTERNS]
    scored = [(p, s) for p, s in scored if s > 0]
    scored.sort(key=lambda ps: -ps[1])
    return scored[:top]
