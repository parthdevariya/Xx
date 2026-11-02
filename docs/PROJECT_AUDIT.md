# PROJECT_AUDIT.md — X platform, initial technical assessment

Date: 3 November 2026 · Auditor: build agent · Scope: everything that exists before X is built.

## 1. What was found

| Location | What it is | State |
|---|---|---|
| `c:\projects\X` | Target repository | **Empty.** No code, no git history, no config. |
| `Downloads\X_Layers_v0.3B_Rules.pdf` | Authoritative Intellect framework source | 19 pages, text-extractable. 10 layers, 93 rules, order, hierarchy, guardrails, library note. Copied to `docs/source/`. |
| `c:\projects\quantum-os` | Python quantum orchestration library ("Quantum OS") | Working. **64/64 tests pass** (pytest, 13.8 s). numpy-only core. |
| `c:\projects\xintellect` | Node 22 "Super Intellect Lab" decision engine + two static HTML pages | Working. **48/48 tests pass** (`node --test`, 2.5 s). |

Because the X folder is empty, there is no in-place application to extend. The two sibling projects are the
existing assets; both are earlier work towards the same product and are audited below as "the existing project".
Neither sibling has been modified.

## 2. Existing functionality inventory

### 2.1 quantum-os (Python) — reuse as the core of Engine B

| Module | Function | Assessment |
|---|---|---|
| `qos/sim/statevector.py` | Pure-numpy statevector simulator (≤ ~22 qubits) | Works; genuine local quantum simulation with no SDK. |
| `qos/algorithms/{qaoa,vqe,grover}.py` | QAOA, VQE, Grover on the local simulator | Works, tested. |
| `qos/algorithms/classical.py` | Exhaustive (≤24 vars), simulated annealing, tabu search | Works — the classical baseline. |
| `qos/formulations/library.py` | 11 templates (max-cut, TSP, knapsack, number partition, portfolio, vertex cover, independent set, graph colouring, assignment, feature selection, bin packing), each with build/decode/verify/true-objective | Works. Correctly scores on the true objective, not penalised energy. |
| `qos/broker/{estimator,selector}.py` | Resource estimation (qubits, depth, shots, fidelity, cost, time) and backend scoring with hard gates | Works. Basis for the Quantum Selection Engine. |
| `qos/providers/*` | Adapters: local, IBM (Qiskit Runtime), AWS Braket, Azure Quantum, D-Wave, Google/Cirq; `simulated`/hardware declared per backend | Local works; cloud adapters import SDKs lazily and report "unavailable" when SDK/credentials are absent. **Not verified against live accounts** (no credentials on this machine). |
| `qos/intent/*` | Regex + optional LLM goal → template parsing | Works for its templates; superseded in X by the orchestration intake, kept as a fallback classifier. |
| `qos/runtime/orchestrator.py` | parse → compile → plan → execute (+fallbacks) → baseline → decode → verify | Works. Synchronous. |
| `qos/api/*`, `qos/cli.py` | Minimal FastAPI + CLI | Not reused (X has its own API). |

### 2.2 xintellect (Node) — reuse ideas, not code

| Area | Assessment |
|---|---|
| LLM adapters (Anthropic, OpenAI-compatible) | Work; small. Pattern reused (provider-independent adapter, refuse rather than fake). |
| `pipeline/intellect.js` | An "intellect repair" step: a single LLM pass that revises a formulation. **Not** the X Layers framework — no layers, no rules, no order. Not reusable for Engine C. |
| `domain/verify.js`, `solvers/*` | Verification separated from solving; energies recomputed; `hardware`/`simulated` provenance mandatory. **Design principles adopted in X.** Code is Node and duplicates quantum-os in Python. |
| SQLite store, HTTP routes | Single-tenant, no auth beyond an optional API key. Not reused. |
| `index.html`, `simulator.html` (≈4,000 lines) | Static demo pages. Visual reference only; contain client-side simulated activity, which X must not do. |

## 3. Gap analysis

| Required by brief | Exists? | Gap |
|---|---|---|
| Next.js command centre | No | Build from scratch. |
| FastAPI backend, REST + WebSocket | Partial (toy API in quantum-os) | Build. |
| PostgreSQL schema, migrations | No | Build (SQLAlchemy 2 + Alembic; SQLite for local/test). |
| Auth, RBAC, audit | No | Build. |
| AI Engine (registry, routing, fallback, usage, cost) | Adapters only (Node) | Build in Python. |
| Quantum Engine | **Yes, substantially** (quantum-os) | Wrap with DB-backed providers/backends/algorithms, async jobs, six-way suitability decision, job history. |
| Intellect Engine (X Layers v0.3B) | **No** | Build entirely: importer, DB model, 13-stage pipeline, guardrails, conflicts, versions, builder, lab. |
| Hybrid orchestration | Partial (quantum pipeline only) | Build intake → plan → multi-engine execution → benchmark → report. |
| Scenario library (DB-driven) | Example JSON files only | Build. |
| Benchmarking | Classical-vs-quantum comparison only | Generalise across six modes. |
| Admin console | No | Build. |
| Render deployment | No | Build `render.yaml`, docs. |

## 4. Decisions: reuse vs replace

1. **Reuse quantum-os** by vendoring `qos/` into `backend/qos/` unchanged, with its 64 tests. X adds a service layer on top; the library itself is not rewritten.
2. **Do not port xintellect's Node code.** Its stack conflicts with the Python backend and its solvers duplicate quantum-os. Its verification and provenance principles are adopted.
3. **Build the Intellect Engine new**, sourced only from the PDF.
4. **Greenfield frontend** in Next.js; xintellect HTML is reference only.

## 5. Architectural limitations and risks found

- **No credentials available** (no AI keys, no quantum accounts). Live AI and hardware paths can be built and unit-tested with recorded HTTP fixtures, but not exercised end to end here.
- **No Docker, PostgreSQL or Redis on the dev machine.** Local runs and tests use SQLite; PostgreSQL-specific behaviour (row locking, triggers) is covered by dialect-aware code and must be verified on first Render deploy.
- **quantum-os is synchronous** and local simulation is capped near 22 qubits. X runs it in background workers; larger instances fall to classical or hardware routes, and the selection engine says so.
- **The Intellect rules are natural language.** Deciding whether a rule "applies" requires judgment; without an AI provider that judgment cannot be made. X therefore records applicability as either *model-assessed* or *not assessed*, and never pretends a keyword match is the rule being applied (see SYSTEM_ARCHITECTURE §5).
- **PDF text extraction artefacts:** typographic ligatures (ﬁ, ﬀ, ﬂ) and line wraps. The importer normalises these glyphs to plain letters and re-joins wrapped lines; no words are changed. Normalisation is recorded per rule and covered by tests.
