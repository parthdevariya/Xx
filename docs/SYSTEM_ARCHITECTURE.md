# SYSTEM_ARCHITECTURE.md — X

## 1. Shape of the system

```
                    ┌──────────────────────── Render ────────────────────────┐
 Browser ──HTTPS──▶ │ x-web (Next.js)  ──/api/* rewrite──▶  x-api (FastAPI)  │
    │               │                                        │  REST + WS     │
    └──── WSS (short-lived ticket) ─────────────────────────▶│                │
                    │                                        ▼                │
                    │                    PostgreSQL  ◀──── x-worker (Python)  │
                    │      (state, job queue, events)       runs executions   │
                    │                    Redis (optional: rate limits)        │
                    └─────────────────────────────────────────────────────────┘
                                    │                    │
                       AI providers (HTTPS)    Quantum providers (SDKs/HTTPS)
```

- **x-web** — Next.js 15 / React / TypeScript / Tailwind / Framer Motion. Holds no secrets. All REST calls go through a same-origin `/api` rewrite so the session cookie is first-party.
- **x-api** — FastAPI. Auth, RBAC, admin, configuration, execution submission, WebSocket event stream, OpenAPI at `/docs`.
- **x-worker** — the same codebase started as `python -m app.worker`. Claims jobs from the `background_jobs` table and runs them. Locally the API can run an embedded worker thread (`X_EMBEDDED_WORKER=true`).
- **PostgreSQL** — the single source of truth, including the job queue (`SELECT … FOR UPDATE SKIP LOCKED`) and the execution event log. SQLite is used for local development and the test suite.
- **Redis** — optional. Used for rate limiting when `REDIS_URL` is set; in-memory limits otherwise.

**Why the queue lives in PostgreSQL, not Redis/Celery:** executions, their events and their jobs must be consistent with each other and survive restarts. A database queue gives that transactionally with one fewer moving part; throughput needs (tens of concurrent executions) are far below where it matters. Redis remains available for caching and limits. This is a deliberate deviation from the brief's recommended stack.

**Why the WebSocket tails the events table instead of Redis pub/sub:** the worker and the API are separate processes. Events are written to `execution_events` with a per-execution sequence number; the socket streams rows with `seq > last_seen`. This means a reconnecting client replays nothing it missed, every message on screen corresponds to a stored backend event, and a REST endpoint (`GET /api/executions/{id}/events?after=`) gives an identical polling fallback.

## 2. Backend module layout

```
backend/
  app/
    main.py                FastAPI app, routers, middleware
    config.py              settings from environment
    db.py                  engine/session, dialect helpers
    security.py            argon2 hashing, JWT sessions, Fernet credential encryption
    deps.py                current user, permission checks
    models/                SQLAlchemy models (one file per domain)
    api/                   routers: auth, users, ai, quantum, intellect, scenarios, executions, admin, ws
    services/audit.py      audit log writer
    ai/                    Engine A — providers/, router.py, service.py
    quantum/               Engine B — service.py, selection.py (wraps qos)
    intellect/             Engine C — source/, importer.py, pipeline.py, conflicts.py, frameworks.py
    orchestration/         intake.py, planner.py, executor.py, benchmark.py, report.py
    scenarios/             seed data and validation
    worker.py              job runner
  qos/                     vendored quantum-os library (unchanged)
  migrations/              Alembic
  tests/
```

Every engine is reached only through its service interface. The orchestrator never imports a provider directly.

## 3. Engine A — AI

- **Adapters** implement one interface: `complete(messages, model, options) → Completion(text, json, usage, latency, raw_model)`.
  - `anthropic` — Anthropic Messages API.
  - `openai_compatible` — OpenAI, Azure OpenAI, Google Gemini (OpenAI-compatible endpoint), Ollama, LM Studio, vLLM, OpenRouter, Groq and any other compatible endpoint, distinguished by base URL and auth header.
  - `deterministic_test` — scripted responses for automated tests and labelled offline demos. Every result it produces carries `provider_kind = "test"` and is displayed as **Test provider — not a real model**.
- Adding a provider type = one adapter file + registration. No orchestration change.
- **Providers and models are DB rows** (`ai_providers`, `ai_models`) managed in the admin console. Credentials are Fernet-encrypted in `ai_credentials`; the API returns only a masked hint (`sk-…9f2c`).
- **Router** (`ai/router.py`) scores active models against a request (required capability, context size, cost ceiling, latency preference, provider allow/deny) using the active `ai_routing_policies` row, returns a ranked list, and the service walks it as a fallback chain. Every attempt is logged in `ai_execution_logs` with tokens, cost and latency.
- **Health** — `POST /api/ai/providers/{id}/health` makes a minimal real call and stores the result in `provider_health`.

## 4. Engine B — Quantum

- `backend/qos` (quantum-os) supplies simulators, algorithms, templates, estimators, broker and cloud adapters.
- `quantum/service.py` adds: DB-backed provider/backend/algorithm registry; credentials from `quantum_credentials` injected into adapters at run time; jobs persisted in `quantum_jobs`; every result stamped with an **execution class**:
  `hardware` · `cloud_simulator` · `local_simulator` · `classical` · `cached` · `test`.
  The class comes from the backend's declared modality, never from the caller, and is shown on every result.
- **Quantum Selection Engine** (`quantum/selection.py`) returns exactly one of:

  | Decision | When |
  |---|---|
  | `quantum_not_applicable` | Problem has no quantum-compatible structure (not optimisation / search / ground-state), or no template maps it. |
  | `insufficient_information` | A template matches but required data is missing; the missing fields are listed. |
  | `classical_preferred` | Exact or heuristic classical methods are expected to match or beat any available quantum route (e.g. ≤ 24 variables are solved exactly by enumeration), or no quantum backend fits the qubit or cost budget. |
  | `quantum_simulation_recommended` | The user is studying quantum behaviour (AI+Quantum or Benchmark mode) and the formulation fits a simulator. Classical remains the reference. |
  | `quantum_experimental` | A credentialed hardware backend fits the qubits, depth, cost and queue limits. Results are research data, not an advantage claim. |
  | `quantum_recommended` | Only when the algorithm record carries admin-entered **benefit evidence** for this problem class and size. None ships by default, so X does not recommend quantum out of the box. |

  Each decision includes the 15 evaluated factors (type, structure, size, complexity, algorithm match, resources, qubits, depth, shots, noise, queue, cost, expected quality, classical alternative, potential benefit) and the plain-language reason.

## 5. Engine C — Intellect

### 5.1 Data

The framework is data, not code. `intellect_frameworks` → `intellect_versions` (draft / in_review / published / archived) → `intellect_layers` → `intellect_rules`. The execution sequence is stored on the version as an ordered list of stages, e.g. `{"layer": "TP", "mode": "frame"}`. The v0.3B content is produced by `intellect/importer.py` from `docs/source/X_Layers_v0.3B_Rules.pdf` and checked into `intellect/source/x_layers_v0_3B.json` with a SHA-256 per rule. Acceptance tests re-parse the PDF and compare.

### 5.2 Pipeline

For v0.3B the stored sequence is:

```
1 CB · 2 TP(frame) · 3 HM(read) · 4 EFV(select preset) · 5 RL · 6 IE · 7 UL · 8 MC
· 9 TP(check) · 10 FD · 11 VL · 12 HM(speak) · 13 EFV(apply preset)
```

Stages run strictly in order. Each stage is one AI call that receives: the problem, the outputs of earlier stages, and the **verbatim text of that stage's layer rules loaded from the database at run time**. It returns structured JSON: per-rule `applies | not_applicable` with a reason, the stage output, and any rule conflicts it detected. EFV(select) returns a delivery preset (register, pace, intensity, with the rule IDs that justify it). The source defines no named presets, so none are invented. EFV(apply) shapes the final text with that preset.

The source does not split HM rules between read and speak, so both HM stages see all enabled HM rules and the trace records which ones each stage applied.

### 5.3 What "rule applied" means

The trace distinguishes four states for every rule in every run:

| State | Meaning |
|---|---|
| `disabled` | Switched off by configuration (never possible for protected rules). |
| `not_assessed` | No AI provider was available, so the rule could not be evaluated. X does not substitute keyword matching for the rule's judgment. |
| `not_applicable` | Model-assessed: the rule's *Not when* condition held or its *When* condition did not. A reason is stored. |
| `applied` | Model-assessed as applicable and used in the stage output. |

### 5.4 Guardrails

MC-14, HM-11, UL-01, HM-13, RL-03, RL-05, MC-17, MC-18, MC-19 and HM-20 are `is_protected = true`. They are enforced at three levels:

1. **Database.** `CHECK (NOT is_protected OR is_active)` on `intellect_rules`, plus triggers that reject updates to the text, conditions, priority or protected flag of a protected rule, and reject deleting one.
2. **Service layer.** `frameworks.py` refuses those operations with an audit-logged 403, whatever the caller's role.
3. **Pipeline.** Protected rules run even when their layer is switched off. Switching MC off removes only its non-protected Core Principles. After stage 13, a separate guardrail audit, recorded outside the 13-stage sequence, re-checks the final text against the ten protected rules and flags any breach.

### 5.5 Conflict resolution

`conflicts.py` is deterministic. Each rule has an effective tier: protected rules sit at tier 1, and every other rule takes its layer's tier from the source hierarchy (RL/IE → 2, MC → 3, VL/TP/UL/FD → 4, CB → 5, HM/EFV → 6). The higher tier wins; within a tier, the lower P number wins; a tie goes to the judgment stage. Custom layers must declare a tier from 2 to 6, enforced by a `CHECK` constraint, so custom content can never reach tier 1. Every conflict is stored with its rule IDs, layers, description, the hierarchy step applied, the decision, and the stage.

### 5.6 Versions, builder, import, lab

- A published version is immutable. Editing creates a draft copy. Publishing runs validation, and for any version derived from v0.3B that validation requires all 93 source rules present with matching hashes and all 10 guardrails protected and active. Otherwise publication stops with the discrepancy listed.
- Rollback re-points the framework's active version to an earlier published one.
- Imports (PDF, DOCX, TXT, JSON, CSV) produce a draft with an import report covering extracted rules, duplicates by normalised-text similarity, suggested layer mappings, possible conflicts and suggested test cases. Imported rules start inactive.
- The Testing Laboratory runs any version, published or draft, with layer toggles, shows the full trace, compares configurations side by side, and stores regression cases with expected outcomes.
- `library/` reference documents (LIBRARY.md, HUMAN_SIGNALS.md) are stored as reference-library entries with `executable = false`. The pipeline never loads them.

## 6. Hybrid orchestration

```
submit ─▶ intake ─▶ plan (visible) ─▶ [user confirms if cost > 0] ─▶ queue ─▶ worker
                                                                       │
     steps: ai_reason | intellect_pipeline | classical_solve | quantum_select | quantum_solve | benchmark | synthesize
                                                                       │
                                     events ─▶ execution_events ─▶ WebSocket ─▶ Command Centre
```

- **Intake** turns input into a structured problem: category, objectives, constraints, required outputs, missing information, complexity, and the matched solver template with data. It uses AI when a provider is available. Otherwise it falls back to the quantum-os pattern classifier, which handles optimisation templates only, and records which method it used.
- **Planner** maps the mode to steps:

  | Mode | Steps |
  |---|---|
  | 1 AI Only | ai_reason → synthesize |
  | 2 AI + Intellect | intellect_pipeline → synthesize |
  | 3 Classical | classical_solve → synthesize |
  | 4 AI + Quantum | (ai formulate if needed) → quantum_select → quantum_solve + classical reference → synthesize |
  | 5 Full Hybrid | quantum_select → classical_solve → quantum_solve if selected → intellect_pipeline over the computed evidence → synthesize |
  | 6 Benchmark | each eligible mode independently on the same input → benchmark → synthesize |

  Steps whose engine is unavailable are marked `skipped` with the reason. They are never faked.
- **Results** keep four kinds of content apart: `computed` (solver output, verified against the true objective), `model_generated` (AI text), `assumption`, and `estimate`. The UI labels each.
- **Benchmarks** run only where a method applies, use the same input and the same true-objective function, and record environment, seeds, timings and versions. The report states that speed differences on simulators are not evidence of quantum advantage.

## 7. Security

- Sessions: JWT in an `HttpOnly; Secure; SameSite=Lax` cookie. State-changing requests also require the `X-CSRF-Token` header to match a non-HttpOnly cookie (double submit).
- Passwords: argon2id. Login is rate-limited and lockout events are audited.
- RBAC: roles → permissions, checked server-side on every protected route (`require("intellect.rules.write")`).
- Credentials: Fernet (`X_ENCRYPTION_KEY`), write-only through the API, shown masked.
- Uploads: extension and MIME allow-list, 10 MB cap, parsed as data only. X never executes uploaded code.
- Prompt-injection posture: user and imported content is passed to models inside delimited data blocks. Guardrails are enforced by the database and the pipeline, not by prompts the user can influence. Imported framework text cannot become active without approval.
- CORS is limited to the frontend origin. Errors return a correlation ID, never stack traces.
