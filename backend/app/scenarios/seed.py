"""Initial scenario library. Stored in the database; administrators edit, version, publish and retire
scenarios without code changes. This file only provides the first-run content."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Scenario, ScenarioCategory, ScenarioExecutionPolicy, ScenarioInputSchema, ScenarioVersion

CATEGORIES = [
    ("optimization", "Optimization", "Routing, scheduling, allocation and distribution problems.", ""),
    ("scientific", "Scientific & Mathematical", "Mathematical optimisation and scientific reasoning.", ""),
    ("financial", "Financial & Economic", "Allocation, risk and scenario analysis.",
     "Educational analysis only. Not investment advice."),
    ("healthcare", "Healthcare & Life Sciences", "Research workflows and resource planning.",
     "Research and operations support only. Not clinical diagnosis or medical advice; no patient data."),
    ("defence", "Defence & Security Research", "Logistics, resource allocation and planning for defensive and "
     "humanitarian operations.", "Planning and logistics only. No offensive capability or surveillance."),
    ("business", "Business & Strategic Intelligence", "Decisions with several competing factors.", ""),
]

ALL_MODES = ["ai_only", "ai_intellect", "classical", "ai_quantum", "hybrid", "benchmark"]
REASONING_MODES = ["ai_only", "ai_intellect"]


def _matrix(key, label, help_=""):
    return {"key": key, "label": label, "type": "matrix", "required": True, "help": help_}


def _list(key, label, item="number", help_=""):
    return {"key": key, "label": label, "type": f"list_{item}", "required": True, "help": help_}


SCENARIOS = [
    {
        "slug": "logistics-routing", "category": "optimization", "demo": True, "solver": "tsp",
        "name": "Logistics Routing", "tagline": "Shortest round trip through every depot.",
        "description": "A delivery vehicle leaves the hub, visits each depot once and returns. X encodes the "
                       "tour as a QUBO, solves it exactly with classical search and, where it fits, samples it "
                       "with QAOA on the local quantum simulator.",
        "problem_statement": "Find the shortest round trip visiting every depot exactly once.",
        "demonstrates": "Exact classical optimum vs. quantum simulation on the same encoding; the Quantum "
                        "Selection Engine explaining why classical is preferred at this size.",
        "engines": ["classical", "quantum", "ai", "intellect"],
        "fields": [_matrix("distances", "Distance matrix (km)", "Square, symmetric, zero diagonal"),
                   _list("names", "Depot names", "text")],
        "defaults": {"distances": [[0, 14, 22, 9], [14, 0, 11, 20], [22, 11, 0, 17], [9, 20, 17, 0]],
                     "names": ["Hub", "North", "East", "South"]},
        "expected": "Ordered tour, total distance, proof of optimality where exhaustive search applies.",
        "visualizations": ["route_graph", "benchmark_bars"],
    },
    {
        "slug": "supply-chain-allocation", "category": "optimization", "demo": False, "solver": "assignment",
        "name": "Supply Chain Allocation", "tagline": "Match distribution centres to regions at minimum cost.",
        "description": "Each distribution centre serves exactly one region. Costs combine freight and lead time.",
        "problem_statement": "Assign centres to regions one-to-one at minimum total cost.",
        "demonstrates": "A 25-variable problem beyond local quantum simulation: X says so and uses classical.",
        "engines": ["classical", "quantum", "ai", "intellect"],
        "fields": [_matrix("costs", "Cost matrix [centre × region]"), _list("agents", "Centres", "text"),
                   _list("tasks", "Regions", "text")],
        "defaults": {"costs": [[4, 2, 8, 6, 5], [4, 3, 7, 5, 9], [3, 1, 6, 9, 4], [7, 5, 2, 4, 6], [8, 6, 5, 3, 2]],
                     "agents": ["Pune DC", "Nagpur DC", "Surat DC", "Indore DC", "Raipur DC"],
                     "tasks": ["West", "Central", "North", "East", "South"]},
        "expected": "Assignment table and total cost.",
        "visualizations": ["assignment_matrix", "benchmark_bars"],
    },
    {
        "slug": "manufacturing-scheduling", "category": "optimization", "demo": False, "solver": "graph_coloring",
        "name": "Manufacturing Scheduling", "tagline": "Put conflicting jobs in different shifts.",
        "description": "Jobs that share a machine or crew cannot run in the same shift. Find a conflict-free "
                       "assignment of jobs to k shifts.",
        "problem_statement": "Assign each job one of k shifts so no two conflicting jobs share a shift.",
        "demonstrates": "Constraint satisfaction as a QUBO; feasibility checked independently of the solver.",
        "engines": ["classical", "quantum", "ai", "intellect"],
        "fields": [{"key": "n", "label": "Number of jobs", "type": "number", "required": True, "min": 2, "max": 12},
                   {"key": "k", "label": "Shifts", "type": "number", "required": True, "min": 2, "max": 4},
                   {"key": "edges", "label": "Conflicts (pairs of job indices)", "type": "json", "required": True},
                   _list("names", "Job names", "text")],
        "defaults": {"n": 6, "k": 3, "edges": [[0, 1], [0, 2], [1, 2], [1, 3], [2, 4], [3, 4], [3, 5], [4, 5]],
                     "names": ["Casting", "Milling", "Welding", "Painting", "Assembly", "Testing"]},
        "expected": "Shift per job, with any conflicts listed.",
        "visualizations": ["conflict_graph"],
    },
    {
        "slug": "energy-load-balancing", "category": "optimization", "demo": True, "solver": "number_partition",
        "name": "Energy Load Balancing", "tagline": "Split loads across two feeders as evenly as possible.",
        "description": "Industrial loads must be connected to one of two feeders. Imbalance increases losses.",
        "problem_statement": "Partition the loads into two groups with sums as equal as possible.",
        "demonstrates": "A 10-qubit problem small enough for QAOA simulation, benchmarked against exact search.",
        "engines": ["classical", "quantum", "ai", "intellect"],
        "fields": [_list("numbers", "Loads (kW)")],
        "defaults": {"numbers": [42, 37, 28, 25, 19, 17, 14, 11, 8, 5]},
        "expected": "Two load groups and the imbalance in kW.",
        "visualizations": ["partition_bars", "benchmark_bars"],
    },
    {
        "slug": "portfolio-allocation", "category": "financial", "demo": True, "solver": "portfolio",
        "name": "Portfolio Allocation", "tagline": "Pick a basket balancing return and risk.",
        "description": "Choose exactly `budget` assets from eight sectors, trading expected return against "
                       "covariance risk (mean-variance with a position-count budget).",
        "problem_statement": "Select the asset basket that maximises return minus risk-aversion × variance.",
        "demonstrates": "Quantum simulation vs. exact classical on an 8-qubit problem, plus Intellect review of "
                        "the recommendation's assumptions.",
        "engines": ["classical", "quantum", "ai", "intellect"],
        "fields": [_list("returns", "Expected returns"), _matrix("covariance", "Covariance matrix"),
                   _list("names", "Asset names", "text"),
                   {"key": "budget", "label": "Assets to hold", "type": "number", "required": True, "min": 1},
                   {"key": "risk_aversion", "label": "Risk aversion", "type": "number", "required": True,
                    "min": 0}],
        "defaults": {
            "returns": [0.12, 0.10, 0.09, 0.07, 0.05, 0.14, 0.08, 0.11],
            "covariance": [[0.040, 0.012, 0.008, 0.002, 0.001, 0.020, 0.004, 0.010],
                           [0.012, 0.035, 0.010, 0.003, 0.001, 0.015, 0.005, 0.011],
                           [0.008, 0.010, 0.030, 0.004, 0.002, 0.009, 0.006, 0.007],
                           [0.002, 0.003, 0.004, 0.015, 0.001, 0.003, 0.002, 0.003],
                           [0.001, 0.001, 0.002, 0.001, 0.010, 0.002, 0.001, 0.002],
                           [0.020, 0.015, 0.009, 0.003, 0.002, 0.060, 0.005, 0.014],
                           [0.004, 0.005, 0.006, 0.002, 0.001, 0.005, 0.022, 0.006],
                           [0.010, 0.011, 0.007, 0.003, 0.002, 0.014, 0.006, 0.028]],
            "names": ["TECH", "FIN", "HEALTH", "UTIL", "BOND", "CRYPTO", "ENERGY", "INDUS"],
            "budget": 4, "risk_aversion": 2.0},
        "expected": "Selected assets, expected return, variance, objective.",
        "visualizations": ["allocation_bars", "benchmark_bars"],
    },
    {
        "slug": "project-portfolio-selection", "category": "business", "demo": False, "solver": "knapsack",
        "name": "Investment Project Selection", "tagline": "Fund the most valuable projects within budget.",
        "description": "Each project has an estimated value and a cost. Choose the set that maximises value "
                       "without exceeding the budget.",
        "problem_statement": "0/1 knapsack: maximise total value subject to total cost ≤ budget.",
        "demonstrates": "Inequality constraints via slack bits, and how they inflate qubit counts.",
        "engines": ["classical", "quantum", "ai", "intellect"],
        "fields": [_list("values", "Project value (₹ lakh)"), _list("weights", "Project cost (₹ lakh)"),
                   {"key": "capacity", "label": "Budget (₹ lakh)", "type": "number", "required": True, "min": 1},
                   _list("names", "Project names", "text")],
        "defaults": {"values": [60, 100, 120, 80, 30], "weights": [10, 20, 30, 15, 5], "capacity": 50,
                     "names": ["CRM upgrade", "New plant line", "Export channel", "Automation", "Training"]},
        "expected": "Funded projects, total value and cost.",
        "visualizations": ["allocation_bars"],
    },
    {
        "slug": "molecular-candidate-prioritization", "category": "healthcare", "demo": False,
        "solver": "feature_selection", "name": "Molecular Candidate Prioritisation",
        "tagline": "Shortlist diverse, relevant candidates for assay.",
        "description": "Choose k candidate compounds that score highly on a pre-computed relevance measure while "
                       "avoiding redundant (structurally similar) picks. Scores are illustrative inputs supplied "
                       "by the researcher.",
        "problem_statement": "Select k items maximising relevance minus α × pairwise redundancy.",
        "demonstrates": "Diversity-aware selection; research workflow support only.",
        "engines": ["classical", "quantum", "ai", "intellect"],
        "fields": [_list("relevance", "Relevance score per candidate"),
                   _matrix("redundancy", "Pairwise similarity (0–1)"),
                   {"key": "k", "label": "Candidates to select", "type": "number", "required": True, "min": 1},
                   {"key": "alpha", "label": "Redundancy penalty α", "type": "number", "required": True},
                   _list("names", "Candidate IDs", "text")],
        "defaults": {"relevance": [0.91, 0.88, 0.74, 0.69, 0.66, 0.52],
                     "redundancy": [[0, 0.8, 0.2, 0.1, 0.3, 0.1], [0.8, 0, 0.25, 0.15, 0.2, 0.1],
                                    [0.2, 0.25, 0, 0.6, 0.1, 0.2], [0.1, 0.15, 0.6, 0, 0.2, 0.3],
                                    [0.3, 0.2, 0.1, 0.2, 0, 0.4], [0.1, 0.1, 0.2, 0.3, 0.4, 0]],
                     "k": 3, "alpha": 1.0, "names": ["CMP-101", "CMP-102", "CMP-205", "CMP-206", "CMP-310",
                                                     "CMP-411"]},
        "expected": "Shortlist with relevance and redundancy scores.",
        "visualizations": ["allocation_bars"],
    },
    {
        "slug": "hospital-staff-allocation", "category": "healthcare", "demo": False, "solver": "assignment",
        "name": "Medical Resource Allocation", "tagline": "Allocate on-call teams to wards.",
        "description": "Operational rostering: match on-call teams to wards to minimise travel and skill-mismatch "
                       "cost. No patient data is used.",
        "problem_statement": "One team per ward, minimum total cost.",
        "demonstrates": "Operations optimisation in healthcare without clinical claims.",
        "engines": ["classical", "quantum", "ai", "intellect"],
        "fields": [_matrix("costs", "Cost matrix [team × ward]"), _list("agents", "Teams", "text"),
                   _list("tasks", "Wards", "text")],
        "defaults": {"costs": [[3, 7, 5, 8], [6, 2, 7, 4], [5, 6, 2, 7], [8, 4, 6, 3]],
                     "agents": ["Team A", "Team B", "Team C", "Team D"],
                     "tasks": ["ICU", "Emergency", "Paediatrics", "General"]},
        "expected": "Team-to-ward roster and total cost.",
        "visualizations": ["assignment_matrix"],
    },
    {
        "slug": "relief-depot-coverage", "category": "defence", "demo": False, "solver": "vertex_cover",
        "name": "Humanitarian Relief Depot Coverage",
        "tagline": "Fewest depots so every supply route touches one.",
        "description": "Disaster-relief logistics: choose the fewest staging depots so every supply route "
                       "(edge between towns) has a depot at one end.",
        "problem_statement": "Minimum vertex cover of the route network.",
        "demonstrates": "Resource allocation for defensive and humanitarian logistics.",
        "engines": ["classical", "quantum", "ai", "intellect"],
        "fields": [{"key": "n", "label": "Towns", "type": "number", "required": True, "min": 2, "max": 16},
                   {"key": "edges", "label": "Routes (pairs of town indices)", "type": "json", "required": True},
                   _list("names", "Town names", "text")],
        "defaults": {"n": 7, "edges": [[0, 1], [0, 2], [1, 3], [2, 3], [3, 4], [4, 5], [4, 6], [5, 6]],
                     "names": ["Kochi", "Aluva", "Thrissur", "Kottayam", "Alappuzha", "Kollam", "Pathanamthitta"]},
        "expected": "Depot towns and confirmation that every route is covered.",
        "visualizations": ["conflict_graph"],
    },
    {
        "slug": "strategic-decision-review", "category": "business", "demo": True, "solver": "",
        "name": "Strategic Decision Review", "tagline": "A hard business decision, through all ten layers.",
        "description": "A reasoning-only scenario. The decision is analysed through the X Intellect framework: "
                       "clarity, perception, reality checks, logic, causes, ethics, long-range view and judgment.",
        "problem_statement": "Should we take the decision described below, and on what conditions?",
        "demonstrates": "The 13-stage Intellect pipeline, rule activation, skipped-rule reasons and conflicts. "
                        "Quantum is correctly judged not applicable.",
        "engines": ["ai", "intellect"],
        "fields": [{"key": "decision", "label": "Describe the decision", "type": "textarea", "required": True}],
        "defaults": {"decision": "Our 40-person firm has been offered a contract that would double revenue but "
                                 "requires moving our two senior engineers to the client site for 18 months. One "
                                 "of them cares for an elderly parent. The client wants an answer by Friday."},
        "expected": "Recommendation, main reason, deciding condition, stakeholders, risks.",
        "visualizations": ["intellect_trace"], "modes": REASONING_MODES + ["hybrid"],
    },
    {
        "slug": "hypothesis-evaluation", "category": "scientific", "demo": False, "solver": "",
        "name": "Scientific Hypothesis Evaluation", "tagline": "What does the evidence actually support?",
        "description": "Evaluate a claim and its evidence: claim type, source quality, alternative explanations, "
                       "base rates and what would falsify it.",
        "problem_statement": "Assess the hypothesis and evidence below.",
        "demonstrates": "RL and IE layers (truth) leading the conflict hierarchy.",
        "engines": ["ai", "intellect"],
        "fields": [{"key": "hypothesis", "label": "Hypothesis and evidence", "type": "textarea", "required": True}],
        "defaults": {"hypothesis": "A pilot of 40 students found that those using a new study app scored 12% "
                                   "higher. The vendor says this proves the app improves learning."},
        "expected": "Claim classification, evidence quality, alternative explanations, conclusion and confidence.",
        "visualizations": ["intellect_trace"], "modes": REASONING_MODES,
    },
]


def seed_scenarios(db: Session) -> None:
    cats = {}
    for pos, (slug, name, desc, notice) in enumerate(CATEGORIES):
        c = db.scalar(select(ScenarioCategory).where(ScenarioCategory.slug == slug))
        if c is None:
            c = ScenarioCategory(slug=slug, name=name, description=desc, notice=notice, position=pos)
            db.add(c)
        cats[slug] = c
    db.flush()
    for pos, s in enumerate(SCENARIOS):
        if db.scalar(select(Scenario).where(Scenario.slug == s["slug"])):
            continue
        sc = Scenario(slug=s["slug"], category_id=cats[s["category"]].id, status="published", is_demo=s["demo"],
                      position=pos)
        db.add(sc)
        db.flush()
        v = ScenarioVersion(scenario_id=sc.id, version_no=1, name=s["name"], tagline=s["tagline"],
                            description=s["description"], problem_statement=s["problem_statement"],
                            demonstrates=s["demonstrates"], solver_template=s["solver"], engines=s["engines"],
                            expected_output=s["expected"], visualizations=s["visualizations"],
                            recommended_framework_slug="x-layers",
                            quantum_eligibility="evaluate" if s["solver"] else "never",
                            benchmark_config={"approaches": ["classical", "quantum_simulation", "ai_only",
                                                             "ai_intellect"]} if s["solver"] else
                            {"approaches": ["ai_only", "ai_intellect"]})
        db.add(v)
        db.flush()
        db.add(ScenarioInputSchema(version_id=v.id, fields=s["fields"], defaults=s["defaults"]))
        modes = s.get("modes", ALL_MODES)
        db.add(ScenarioExecutionPolicy(scenario_id=sc.id, allowed_modes=modes,
                                       default_mode="hybrid" if "hybrid" in modes else modes[-1]))
        sc.current_version_id = v.id
    db.flush()


def seed_proof_scenarios(db: Session) -> None:
    """Intellect Proof Lab + Computation-and-Judgment scenarios; retire the original library once."""
    from ..models import SystemSetting
    from .proof_seed import ALL_MODES as P_ALL, CATEGORIES as P_CATS, PROOF_SCENARIOS, REASONING_MODES

    cats = {c.slug: c for c in db.scalars(select(ScenarioCategory))}
    base = len(cats)
    for i, (slug, name, desc, notice) in enumerate(P_CATS):
        if slug not in cats:
            cats[slug] = ScenarioCategory(slug=slug, name=name, description=desc, notice=notice, position=-10 + i)
            db.add(cats[slug])
    db.flush()
    for pos, s in enumerate(PROOF_SCENARIOS):
        if db.scalar(select(Scenario).where(Scenario.slug == s["slug"])):
            continue
        solver = s.get("solver", "")
        sc = Scenario(slug=s["slug"], category_id=cats[s["category"]].id, status="published", is_demo=s["demo"],
                      position=-100 + pos)
        db.add(sc)
        db.flush()
        engines = ["classical", "quantum", "ai", "intellect"] if solver else ["ai", "intellect"]
        v = ScenarioVersion(
            scenario_id=sc.id, version_no=1, name=s["name"], tagline=s["tagline"], description=s["description"],
            problem_statement=s.get("problem_statement", "Respond to the situation below."),
            demonstrates=s["demonstrates"], solver_template=solver, engines=engines,
            expected_output="Side-by-side AI Only vs AI + Intellect answers, a blind rubric score, the rules behind "
                            "the difference" + ("; plus the proven optimum and quantum comparison" if solver else ""),
            visualizations=["proof_scoreboard", "intellect_trace"] + (["benchmark_bars"] if solver else []),
            recommended_framework_slug="x-layers", quantum_eligibility="evaluate" if solver else "never",
            benchmark_config={"approaches": ["ai_only", "ai_intellect"] + (["classical", "quantum_simulation"]
                                                                           if solver else []),
                              "rubric": s["rubric"]})
        db.add(v)
        db.flush()
        fields = s.get("fields") or [{"key": "situation", "label": "The situation (edit freely)",
                                      "type": "textarea", "required": True}]
        defaults = s.get("defaults") or {"situation": s["situation"]}
        db.add(ScenarioInputSchema(version_id=v.id, fields=fields, defaults=defaults))
        modes = P_ALL if solver else REASONING_MODES
        db.add(ScenarioExecutionPolicy(scenario_id=sc.id, allowed_modes=modes,
                                       default_mode="benchmark" if solver else "intellect_vs_ai"))
        sc.current_version_id = v.id
    flag = db.get(SystemSetting, "scenario_library")
    if flag is None or (flag.value or {}).get("version", 1) < 2:
        legacy = {s["slug"] for s in SCENARIOS}
        for sc in db.scalars(select(Scenario).where(Scenario.slug.in_(legacy), Scenario.status == "published")):
            sc.status = "retired"
        if flag is None:
            db.add(SystemSetting(key="scenario_library", value={"version": 2},
                                 description="Library v2: Intellect Proof scenarios; original scenarios retired "
                                             "(re-publish from Admin → Scenarios if needed)."))
        else:
            flag.value = {"version": 2}
        flag = db.get(SystemSetting, "scenario_library")
    # Library v3: enable the All Combinations Matrix on every scenario once.
    if (flag.value or {}).get("version", 1) < 3:
        for pol in db.scalars(select(ScenarioExecutionPolicy)):
            if "matrix" not in (pol.allowed_modes or []):
                pol.allowed_modes = [*pol.allowed_modes, "matrix"]
        flag.value = {"version": 3}
    db.flush()
