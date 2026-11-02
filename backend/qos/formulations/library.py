"""Template library: domain problem -> QUBO, and back again.

Each template bundles four things, because an encoding alone is not enough to
give a user a trustworthy answer:

    build     data -> Formulation          (the encoding)
    decode    bits -> domain answer        (what the user actually asked for)
    verify    answer -> ConstraintCheck    (is it feasible?)
    objective answer -> float              (true objective, not penalized energy)

Keeping ``objective`` separate from the QUBO energy is deliberate: energy
includes penalty terms, so it is the wrong number to report or to compare
against a classical baseline. The platform always scores solutions on the
true objective and reports feasibility separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from ..models import Formulation
from .qubo import ConstraintCheck, QUBOBuilder, slack_bits_needed, suggest_penalty


@dataclass
class Template:
    name: str
    description: str
    build: Callable[[dict], Formulation]
    decode: Callable[[str, dict], Any]
    verify: Callable[[Any, dict], ConstraintCheck]
    objective: Callable[[Any, dict], float]
    # "max" means a larger true objective is better.
    sense: str = "min"
    # Variables needed, as a function of the data -- used by the estimator
    # before any encoding work happens.
    size: Callable[[dict], int] = lambda d: int(d.get("n", 0))


TEMPLATES: dict[str, Template] = {}


def register(t: Template) -> Template:
    TEMPLATES[t.name] = t
    return t


def _bits(bitstring: str, n: int) -> np.ndarray:
    """Bitstring -> 0/1 array, truncated/padded to n (position q == var q)."""
    arr = np.zeros(n, dtype=np.int8)
    for i in range(min(n, len(bitstring))):
        arr[i] = 1 if bitstring[i] == "1" else 0
    return arr


def _edges(data: dict) -> list[tuple[int, int, float]]:
    """Normalize edges to (i, j, weight) triples."""
    out = []
    for e in data.get("edges", []):
        if len(e) == 3:
            out.append((int(e[0]), int(e[1]), float(e[2])))
        else:
            out.append((int(e[0]), int(e[1]), 1.0))
    return out


# =========================================================================
# MAX-CUT -- the canonical QAOA benchmark
# =========================================================================

def _maxcut_build(data: dict) -> Formulation:
    n = int(data["n"])
    edges = _edges(data)
    b = QUBOBuilder(n, "max_cut")
    # Cut value of edge (i,j) is w*(x_i + x_j - 2 x_i x_j); we minimize the
    # negative of the total cut.
    for i, j, w in edges:
        b.linear(i, -w)
        b.linear(j, -w)
        b.quadratic(i, j, 2.0 * w)
    b.notes.append(f"max-cut on {n} nodes, {len(edges)} edges")
    return b.build({"template": "max_cut", "n": n})


def _maxcut_decode(bits: str, data: dict) -> dict:
    n = int(data["n"])
    x = _bits(bits, n)
    return {
        "partition_A": [i for i in range(n) if x[i] == 0],
        "partition_B": [i for i in range(n) if x[i] == 1],
        "assignment": x.tolist(),
    }


def _maxcut_objective(ans: dict, data: dict) -> float:
    x = np.asarray(ans["assignment"])
    return float(sum(w for i, j, w in _edges(data) if x[i] != x[j]))


register(Template(
    name="max_cut",
    description="Split a graph's nodes into two groups, maximizing the weight of edges crossing between them.",
    build=_maxcut_build,
    decode=_maxcut_decode,
    verify=lambda a, d: ConstraintCheck(True),
    objective=_maxcut_objective,
    sense="max",
))


# =========================================================================
# TRAVELLING SALESPERSON -- one-hot time/city encoding
# =========================================================================

def _tsp_build(data: dict) -> Formulation:
    D = np.asarray(data["distances"], dtype=float)
    n = D.shape[0]
    nv = n * n
    # Variable x[c * n + t] == 1 means city c is visited at step t.
    scale = float(D.max()) if D.size else 1.0
    pen = suggest_penalty(scale * n, safety=2.5)
    b = QUBOBuilder(nv, "tsp")

    def v(city: int, t: int) -> int:
        return city * n + t

    # Objective: distance between consecutive steps, tour closes back to start.
    for t in range(n):
        t2 = (t + 1) % n
        for c1 in range(n):
            for c2 in range(n):
                if c1 != c2 and D[c1, c2] != 0:
                    b.quadratic(v(c1, t), v(c2, t2), float(D[c1, c2]))
    # Each city visited exactly once, and each time step holds exactly one city.
    for c in range(n):
        b.penalize_one_hot([v(c, t) for t in range(n)], pen, "city_once")
    for t in range(n):
        b.penalize_one_hot([v(c, t) for c in range(n)], pen, "one_city_per_step")
    for c in range(n):
        for t in range(n):
            b.label(v(c, t), f"city{c}@step{t}")
    b.notes.append(f"TSP on {n} cities -> {nv} binary variables (one-hot city x step)")
    return b.build({"template": "tsp", "n": n, "nv": nv})


def _tsp_decode(bits: str, data: dict) -> dict:
    D = np.asarray(data["distances"], dtype=float)
    n = D.shape[0]
    x = _bits(bits, n * n).reshape(n, n)   # [city, step]
    # Read off the tour; if a step is ambiguous, take the set bit with the
    # lowest index and let verify() report the infeasibility.
    tour: list[int] = []
    for t in range(n):
        col = np.nonzero(x[:, t])[0]
        tour.append(int(col[0]) if len(col) else -1)
    names = data.get("names")
    return {
        "tour": tour,
        "tour_names": [names[c] if names and 0 <= c < len(names) else str(c) for c in tour],
        "matrix": x.tolist(),
    }


def _tsp_verify(ans: dict, data: dict) -> ConstraintCheck:
    n = np.asarray(data["distances"]).shape[0]
    tour = ans["tour"]
    viol: list[str] = []
    if -1 in tour:
        viol.append("one or more steps had no city assigned")
    visited = [c for c in tour if c >= 0]
    if len(set(visited)) != len(visited):
        dupes = {c for c in visited if visited.count(c) > 1}
        viol.append(f"cities visited more than once: {sorted(dupes)}")
    missing = set(range(n)) - set(visited)
    if missing:
        viol.append(f"cities never visited: {sorted(missing)}")
    return ConstraintCheck(not viol, viol)


def _tsp_objective(ans: dict, data: dict) -> float:
    D = np.asarray(data["distances"], dtype=float)
    tour = [c for c in ans["tour"] if c >= 0]
    if len(tour) < 2:
        return float("inf")
    return float(sum(D[tour[i], tour[(i + 1) % len(tour)]] for i in range(len(tour))))


register(Template(
    name="tsp",
    description="Find the shortest round trip that visits every location exactly once.",
    build=_tsp_build,
    decode=_tsp_decode,
    verify=_tsp_verify,
    objective=_tsp_objective,
    sense="min",
    size=lambda d: int(np.asarray(d["distances"]).shape[0] ** 2),
))


# =========================================================================
# KNAPSACK -- inequality constraint via binary slack
# =========================================================================

def _knapsack_build(data: dict) -> Formulation:
    values = np.asarray(data["values"], dtype=float)
    weights = np.asarray(data["weights"], dtype=float)
    cap = float(data["capacity"])
    n = len(values)
    n_slack = slack_bits_needed(cap)
    b = QUBOBuilder(n + n_slack, "knapsack")
    # Maximize value => minimize negative value.
    for i in range(n):
        b.linear(i, -float(values[i]))
    pen = suggest_penalty(float(values.sum()), safety=2.0) / max(1.0, cap)
    b.penalize_inequality_leq(
        list(range(n)), [float(w) for w in weights], cap, pen, "capacity", n_slack
    )
    names = data.get("names")
    for i in range(n):
        b.label(i, names[i] if names and i < len(names) else f"item{i}")
    b.notes.append(f"knapsack: {n} items + {n_slack} slack bits for capacity {cap:g}")
    return b.build({"template": "knapsack", "n": n, "n_slack": n_slack})


def _knapsack_decode(bits: str, data: dict) -> dict:
    n = len(data["values"])
    x = _bits(bits, n)
    names = data.get("names")
    chosen = [i for i in range(n) if x[i] == 1]
    return {
        "selected": chosen,
        "selected_names": [names[i] if names and i < len(names) else f"item{i}" for i in chosen],
        "assignment": x.tolist(),
        "total_weight": float(np.asarray(data["weights"], dtype=float)[chosen].sum()),
        "total_value": float(np.asarray(data["values"], dtype=float)[chosen].sum()),
    }


def _knapsack_verify(ans: dict, data: dict) -> ConstraintCheck:
    cap = float(data["capacity"])
    w = ans["total_weight"]
    if w > cap + 1e-9:
        return ConstraintCheck(False, [f"total weight {w:g} exceeds capacity {cap:g}"])
    return ConstraintCheck(True)


register(Template(
    name="knapsack",
    description="Choose the most valuable set of items that fits within a capacity limit.",
    build=_knapsack_build,
    decode=_knapsack_decode,
    verify=_knapsack_verify,
    objective=lambda a, d: float(a["total_value"]),
    sense="max",
    size=lambda d: len(d["values"]) + slack_bits_needed(float(d["capacity"])),
))


# =========================================================================
# NUMBER PARTITIONING
# =========================================================================

def _partition_build(data: dict) -> Formulation:
    a = np.asarray(data["numbers"], dtype=float)
    n = len(a)
    S = float(a.sum())
    b = QUBOBuilder(n, "number_partition")
    # Minimize (sum_i a_i * s_i)^2 with s_i = 2x_i - 1, which expands to
    # 4*(sum a_i x_i)^2 - 4*S*(sum a_i x_i) + S^2.
    for i in range(n):
        b.linear(i, 4.0 * a[i] * a[i] - 4.0 * S * a[i])
    for i in range(n):
        for j in range(i + 1, n):
            b.quadratic(i, j, 8.0 * a[i] * a[j])
    b.constant(S * S)
    b.notes.append(f"partition {n} numbers, total {S:g}")
    return b.build({"template": "number_partition", "n": n})


def _partition_decode(bits: str, data: dict) -> dict:
    a = np.asarray(data["numbers"], dtype=float)
    n = len(a)
    x = _bits(bits, n)
    g1 = [i for i in range(n) if x[i] == 1]
    g2 = [i for i in range(n) if x[i] == 0]
    return {
        "group_1": [float(a[i]) for i in g1],
        "group_2": [float(a[i]) for i in g2],
        "sum_1": float(a[g1].sum()),
        "sum_2": float(a[g2].sum()),
        "difference": abs(float(a[g1].sum() - a[g2].sum())),
        "assignment": x.tolist(),
    }


register(Template(
    name="number_partition",
    description="Split a list of numbers into two groups with sums as equal as possible.",
    build=_partition_build,
    decode=_partition_decode,
    verify=lambda a, d: ConstraintCheck(True),
    objective=lambda a, d: float(a["difference"]),
    sense="min",
    size=lambda d: len(d["numbers"]),
))


# =========================================================================
# PORTFOLIO SELECTION -- mean/variance with a cardinality constraint
# =========================================================================

def _portfolio_build(data: dict) -> Formulation:
    mu = np.asarray(data["returns"], dtype=float)
    n = len(mu)
    cov = np.asarray(data.get("covariance", np.eye(n)), dtype=float)
    q = float(data.get("risk_aversion", 1.0))
    k = data.get("budget")
    b = QUBOBuilder(n, "portfolio")
    # Minimize  q * x.T Sigma x - mu.T x
    for i in range(n):
        b.linear(i, -float(mu[i]) + q * float(cov[i, i]))
    for i in range(n):
        for j in range(i + 1, n):
            b.quadratic(i, j, 2.0 * q * float(cov[i, j]))
    if k is not None:
        scale = float(np.abs(mu).max() + q * np.abs(cov).max())
        b.penalize_equality(list(range(n)), float(k), suggest_penalty(scale, 3.0), "budget")
    names = data.get("names")
    for i in range(n):
        b.label(i, names[i] if names and i < len(names) else f"asset{i}")
    b.notes.append(f"portfolio: {n} assets, risk_aversion={q:g}, budget={k}")
    return b.build({"template": "portfolio", "n": n})


def _portfolio_decode(bits: str, data: dict) -> dict:
    mu = np.asarray(data["returns"], dtype=float)
    n = len(mu)
    cov = np.asarray(data.get("covariance", np.eye(n)), dtype=float)
    x = _bits(bits, n).astype(float)
    names = data.get("names")
    chosen = [i for i in range(n) if x[i] == 1]
    return {
        "selected": chosen,
        "selected_names": [names[i] if names and i < len(names) else f"asset{i}" for i in chosen],
        "expected_return": float(mu @ x),
        "variance": float(x @ cov @ x),
        "count": len(chosen),
        "assignment": [int(v) for v in x],
    }


def _portfolio_verify(ans: dict, data: dict) -> ConstraintCheck:
    k = data.get("budget")
    if k is not None and ans["count"] != int(k):
        return ConstraintCheck(False, [f"selected {ans['count']} assets, budget requires exactly {int(k)}"])
    return ConstraintCheck(True)


def _portfolio_objective(ans: dict, data: dict) -> float:
    q = float(data.get("risk_aversion", 1.0))
    return float(ans["expected_return"] - q * ans["variance"])


register(Template(
    name="portfolio",
    description="Pick a basket of assets balancing expected return against risk, under a position-count budget.",
    build=_portfolio_build,
    decode=_portfolio_decode,
    verify=_portfolio_verify,
    objective=_portfolio_objective,
    sense="max",
    size=lambda d: len(d["returns"]),
))


# =========================================================================
# VERTEX COVER / INDEPENDENT SET / MAX CLIQUE
# =========================================================================

def _vertex_cover_build(data: dict) -> Formulation:
    n = int(data["n"])
    edges = _edges(data)
    b = QUBOBuilder(n, "vertex_cover")
    pen = suggest_penalty(float(n), 2.0)
    for i in range(n):
        b.linear(i, 1.0)
    # Every edge needs at least one endpoint chosen: penalty (1-x_i)(1-x_j).
    for i, j, _w in edges:
        b.constant(pen)
        b.linear(i, -pen)
        b.linear(j, -pen)
        b.quadratic(i, j, pen)
    b.notes.append(f"vertex cover on {n} nodes, {len(edges)} edges")
    return b.build({"template": "vertex_cover", "n": n})


def _cover_decode(bits: str, data: dict) -> dict:
    n = int(data["n"])
    x = _bits(bits, n)
    return {"cover": [i for i in range(n) if x[i] == 1], "size": int(x.sum()), "assignment": x.tolist()}


def _cover_verify(ans: dict, data: dict) -> ConstraintCheck:
    chosen = set(ans["cover"])
    bad = [(i, j) for i, j, _ in _edges(data) if i not in chosen and j not in chosen]
    if bad:
        return ConstraintCheck(False, [f"{len(bad)} edges uncovered, e.g. {bad[:3]}"])
    return ConstraintCheck(True)


register(Template(
    name="vertex_cover",
    description="Choose the fewest nodes that together touch every edge of a graph.",
    build=_vertex_cover_build,
    decode=_cover_decode,
    verify=_cover_verify,
    objective=lambda a, d: float(a["size"]),
    sense="min",
))


def _mis_build(data: dict) -> Formulation:
    n = int(data["n"])
    edges = _edges(data)
    weights = data.get("weights") or [1.0] * n
    b = QUBOBuilder(n, "independent_set")
    pen = suggest_penalty(float(max(weights)), 2.0)
    for i in range(n):
        b.linear(i, -float(weights[i]))
    for i, j, _w in edges:
        b.quadratic(i, j, pen)
    b.notes.append(f"max independent set on {n} nodes, {len(edges)} edges")
    return b.build({"template": "independent_set", "n": n})


def _mis_decode(bits: str, data: dict) -> dict:
    n = int(data["n"])
    x = _bits(bits, n)
    w = data.get("weights") or [1.0] * n
    sel = [i for i in range(n) if x[i] == 1]
    return {"selected": sel, "size": len(sel), "weight": float(sum(w[i] for i in sel)), "assignment": x.tolist()}


def _mis_verify(ans: dict, data: dict) -> ConstraintCheck:
    sel = set(ans["selected"])
    bad = [(i, j) for i, j, _ in _edges(data) if i in sel and j in sel]
    if bad:
        return ConstraintCheck(False, [f"{len(bad)} chosen pairs are adjacent, e.g. {bad[:3]}"])
    return ConstraintCheck(True)


register(Template(
    name="independent_set",
    description="Select the largest set of items with no conflicts between any two chosen items.",
    build=_mis_build,
    decode=_mis_decode,
    verify=_mis_verify,
    objective=lambda a, d: float(a["weight"]),
    sense="max",
))


# =========================================================================
# GRAPH COLORING -- scheduling/conflict problems in disguise
# =========================================================================

def _coloring_build(data: dict) -> Formulation:
    n = int(data["n"])
    k = int(data.get("k", 3))
    edges = _edges(data)
    nv = n * k
    b = QUBOBuilder(nv, "graph_coloring")
    pen = suggest_penalty(1.0, 2.0)

    def v(node: int, color: int) -> int:
        return node * k + color

    for node in range(n):
        b.penalize_one_hot([v(node, c) for c in range(k)], pen, "one_color_per_node")
    for i, j, _w in edges:
        for c in range(k):
            b.quadratic(v(i, c), v(j, c), pen)
    b.notes.append(f"coloring {n} nodes with {k} colors -> {nv} variables")
    return b.build({"template": "graph_coloring", "n": n, "k": k})


def _coloring_decode(bits: str, data: dict) -> dict:
    n, k = int(data["n"]), int(data.get("k", 3))
    x = _bits(bits, n * k).reshape(n, k)
    colors = []
    for node in range(n):
        row = np.nonzero(x[node])[0]
        colors.append(int(row[0]) if len(row) else -1)
    names = data.get("names")
    groups: dict[int, list] = {}
    for node, c in enumerate(colors):
        label = names[node] if names and node < len(names) else node
        groups.setdefault(c, []).append(label)
    return {"colors": colors, "groups": {str(c): v for c, v in sorted(groups.items())}}


def _coloring_verify(ans: dict, data: dict) -> ConstraintCheck:
    colors = ans["colors"]
    viol = []
    if -1 in colors:
        viol.append(f"{colors.count(-1)} nodes received no color")
    clash = [(i, j) for i, j, _ in _edges(data) if colors[i] == colors[j] and colors[i] != -1]
    if clash:
        viol.append(f"{len(clash)} adjacent pairs share a color, e.g. {clash[:3]}")
    return ConstraintCheck(not viol, viol)


register(Template(
    name="graph_coloring",
    description="Assign one of k labels to each item so no two conflicting items share a label.",
    build=_coloring_build,
    decode=_coloring_decode,
    verify=_coloring_verify,
    objective=lambda a, d: float(sum(1 for i, j, _ in _edges(d) if a["colors"][i] == a["colors"][j])),
    sense="min",
    size=lambda d: int(d["n"]) * int(d.get("k", 3)),
))


# =========================================================================
# ASSIGNMENT -- agents to tasks, one each
# =========================================================================

def _assignment_build(data: dict) -> Formulation:
    C = np.asarray(data["costs"], dtype=float)   # [agent, task]
    na, nt = C.shape
    nv = na * nt
    b = QUBOBuilder(nv, "assignment")
    pen = suggest_penalty(float(np.abs(C).max()) * max(na, nt), 2.0)

    def v(a: int, t: int) -> int:
        return a * nt + t

    for a in range(na):
        for t in range(nt):
            b.linear(v(a, t), float(C[a, t]))
    for a in range(na):
        b.penalize_one_hot([v(a, t) for t in range(nt)], pen, "one_task_per_agent")
    for t in range(nt):
        b.penalize_at_most_one([v(a, t) for a in range(na)], pen, "no_task_twice")
    b.notes.append(f"assignment {na} agents x {nt} tasks -> {nv} variables")
    return b.build({"template": "assignment", "na": na, "nt": nt})


def _assignment_decode(bits: str, data: dict) -> dict:
    C = np.asarray(data["costs"], dtype=float)
    na, nt = C.shape
    x = _bits(bits, na * nt).reshape(na, nt)
    agents = data.get("agents")
    tasks = data.get("tasks")
    pairs = []
    total = 0.0
    for a in range(na):
        row = np.nonzero(x[a])[0]
        t = int(row[0]) if len(row) else -1
        pairs.append({
            "agent": agents[a] if agents and a < len(agents) else f"agent{a}",
            "task": (tasks[t] if tasks and 0 <= t < len(tasks) else (str(t) if t >= 0 else None)),
            "cost": float(C[a, t]) if t >= 0 else None,
        })
        if t >= 0:
            total += float(C[a, t])
    return {"assignments": pairs, "total_cost": total, "matrix": x.tolist()}


def _assignment_verify(ans: dict, data: dict) -> ConstraintCheck:
    viol = []
    assigned = [p["task"] for p in ans["assignments"]]
    if any(t is None for t in assigned):
        viol.append("some agents received no task")
    real = [t for t in assigned if t is not None]
    if len(set(real)) != len(real):
        viol.append("a task was assigned to more than one agent")
    return ConstraintCheck(not viol, viol)


register(Template(
    name="assignment",
    description="Match agents to tasks one-for-one at minimum total cost.",
    build=_assignment_build,
    decode=_assignment_decode,
    verify=_assignment_verify,
    objective=lambda a, d: float(a["total_cost"]),
    sense="min",
    size=lambda d: int(np.asarray(d["costs"]).shape[0] * np.asarray(d["costs"]).shape[1]),
))


# =========================================================================
# FEATURE SELECTION -- relevance minus redundancy, fixed cardinality
# =========================================================================

def _feature_build(data: dict) -> Formulation:
    rel = np.asarray(data["relevance"], dtype=float)
    n = len(rel)
    red = np.asarray(data.get("redundancy", np.zeros((n, n))), dtype=float)
    k = data.get("k")
    alpha = float(data.get("alpha", 1.0))
    b = QUBOBuilder(n, "feature_selection")
    for i in range(n):
        b.linear(i, -float(rel[i]))
    for i in range(n):
        for j in range(i + 1, n):
            b.quadratic(i, j, 2.0 * alpha * float(red[i, j]))
    if k is not None:
        scale = float(np.abs(rel).max() + alpha * np.abs(red).max())
        b.penalize_equality(list(range(n)), float(k), suggest_penalty(scale, 3.0), "cardinality")
    names = data.get("names")
    for i in range(n):
        b.label(i, names[i] if names and i < len(names) else f"f{i}")
    b.notes.append(f"feature selection: {n} candidates, k={k}")
    return b.build({"template": "feature_selection", "n": n})


def _feature_decode(bits: str, data: dict) -> dict:
    rel = np.asarray(data["relevance"], dtype=float)
    n = len(rel)
    x = _bits(bits, n)
    names = data.get("names")
    sel = [i for i in range(n) if x[i] == 1]
    return {
        "selected": sel,
        "selected_names": [names[i] if names and i < len(names) else f"f{i}" for i in sel],
        "count": len(sel),
        "total_relevance": float(rel[sel].sum()) if sel else 0.0,
        "assignment": x.tolist(),
    }


def _feature_verify(ans: dict, data: dict) -> ConstraintCheck:
    k = data.get("k")
    if k is not None and ans["count"] != int(k):
        return ConstraintCheck(False, [f"selected {ans['count']} features, asked for exactly {int(k)}"])
    return ConstraintCheck(True)


def _feature_objective(ans: dict, data: dict) -> float:
    rel = np.asarray(data["relevance"], dtype=float)
    n = len(rel)
    red = np.asarray(data.get("redundancy", np.zeros((n, n))), dtype=float)
    alpha = float(data.get("alpha", 1.0))
    sel = ans["selected"]
    pen = sum(red[i, j] for a, i in enumerate(sel) for j in sel[a + 1:])
    return float(rel[sel].sum() - alpha * pen) if sel else 0.0


register(Template(
    name="feature_selection",
    description="Pick the most informative, least redundant subset of features for a model.",
    build=_feature_build,
    decode=_feature_decode,
    verify=_feature_verify,
    objective=_feature_objective,
    sense="max",
    size=lambda d: len(d["relevance"]),
))


# =========================================================================
# BIN PACKING / shift scheduling -- items into a fixed number of bins
# =========================================================================

def _binpack_build(data: dict) -> Formulation:
    sizes = np.asarray(data["sizes"], dtype=float)
    n = len(sizes)
    nb = int(data.get("bins", 2))
    cap = float(data["capacity"])
    nv = n * nb
    b = QUBOBuilder(nv, "bin_packing")
    pen = suggest_penalty(float(sizes.sum()), 2.0)

    def v(item: int, bin_: int) -> int:
        return item * nb + bin_

    # Each item in exactly one bin.
    for i in range(n):
        b.penalize_one_hot([v(i, j) for j in range(nb)], pen, "item_once")
    # Soft capacity: squared overload per bin, which also spreads load evenly.
    w = pen / max(1.0, cap)
    for j in range(nb):
        idx = [v(i, j) for i in range(n)]
        for a in range(n):
            b.linear(idx[a], w * (sizes[a] ** 2 - 2.0 * cap * sizes[a]))
            for c in range(a + 1, n):
                b.quadratic(idx[a], idx[c], 2.0 * w * sizes[a] * sizes[c])
    b.notes.append(f"pack {n} items into {nb} bins of capacity {cap:g}")
    return b.build({"template": "bin_packing", "n": n, "bins": nb})


def _binpack_decode(bits: str, data: dict) -> dict:
    sizes = np.asarray(data["sizes"], dtype=float)
    n = len(sizes)
    nb = int(data.get("bins", 2))
    x = _bits(bits, n * nb).reshape(n, nb)
    names = data.get("names")
    bins: dict[int, list] = {j: [] for j in range(nb)}
    placed = []
    for i in range(n):
        row = np.nonzero(x[i])[0]
        j = int(row[0]) if len(row) else -1
        placed.append(j)
        if j >= 0:
            bins[j].append(names[i] if names and i < len(names) else i)
    loads = {j: float(sum(sizes[i] for i in range(n) if placed[i] == j)) for j in range(nb)}
    return {"bins": {str(j): v for j, v in bins.items()}, "loads": {str(j): v for j, v in loads.items()},
            "placement": placed}


def _binpack_verify(ans: dict, data: dict) -> ConstraintCheck:
    cap = float(data["capacity"])
    viol = []
    if -1 in ans["placement"]:
        viol.append("some items were not placed in any bin")
    over = {j: l for j, l in ans["loads"].items() if l > cap + 1e-9}
    if over:
        viol.append(f"bins over capacity {cap:g}: {over}")
    return ConstraintCheck(not viol, viol)


register(Template(
    name="bin_packing",
    description="Distribute items across a fixed number of bins without exceeding capacity.",
    build=_binpack_build,
    decode=_binpack_decode,
    verify=_binpack_verify,
    objective=lambda a, d: float(max(a["loads"].values()) - min(a["loads"].values())),
    sense="min",
    size=lambda d: len(d["sizes"]) * int(d.get("bins", 2)),
))
