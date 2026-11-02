# IMPLEMENTATION_ROADMAP.md — X

Status as of 3 November 2026. "Verified" means covered by automated tests or exercised end to end on the running system during development.

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Audit, architecture, schema, roadmap | Done — `PROJECT_AUDIT.md`, `SYSTEM_ARCHITECTURE.md`, `DATABASE_SCHEMA.md`, this file |
| 2 | Foundation: auth, RBAC, DB, migrations, config, audit, design system | Done, verified |
| 3 | AI Engine: registry, models, credentials, routing, fallback, usage/cost | Done. Adapters verified with mocked transports; **live calls await an API key** |
| 4 | Intellect Engine: import, pipeline, guardrails, conflicts, builder, lab, versions | Done, verified (acceptance suite) |
| 5 | Quantum Engine: adapters, local simulator, algorithm registry, selection engine, jobs | Done. Local simulation verified; **hardware awaits SDKs + credentials** |
| 6 | Hybrid orchestration: intake, planning, six modes, monitoring | Done, verified |
| 7 | Scenario library: DB-driven, versioned, 11 initial scenarios | Done, verified |
| 8 | Command Centre | Done; verified in a real browser (desktop and phone width) |
| 9 | Administration console and reporting | Done: 17 screens plus rule and run detail views; dashboard, providers, Intellect, scenarios, policies and users rendered in a real browser against the live backend |
| 10 | QA and deployment | Tests and CI done; Render Blueprint and guide done; **first Render deploy not yet performed** |

## Completed features

- X Layers v0.3B imported from the PDF: 10 layers, 93 rules, original IDs, wording, conditions, priority and provenance, each with a SHA-256. Re-parsing the PDF must reproduce the checked-in pack exactly (test).
- The exact 13-stage source sequence, stored as data. Source stages cannot be reordered; custom stages can.
- 10 protected guardrails, enforced by database CHECK constraints and triggers, by the service layer and by the pipeline, and confirmed through the API. Switching MC off leaves MC-14/17/18/19 running.
- Deterministic conflict resolution under the source hierarchy, plus model-reported and source-declared ("X overrides") conflicts with a full trace.
- Framework Builder: create, duplicate, draft, custom layers (tiers 2–6) and custom rules (inactive by default), review, publish, reject, roll back, diff. Publication is blocked when any of the 93 source rules or 10 guardrails is missing or altered.
- Imports from PDF, DOCX, TXT, JSON and CSV, producing an inactive draft and a report covering duplicates, layer mapping, conflicts including attempts to override protected rules, and suggested tests.
- Testing Laboratory: lab runs through the job queue, per-rule states with reasons, comparisons, expectations, and regression suites.
- AI adapters: Anthropic (official SDK; structured output, explicit effort, refusal handling with server-side fallback) and OpenAI-compatible (OpenAI, Azure, Gemini, Ollama, LM Studio, vLLM…), plus a labelled deterministic test provider. Includes the router, the fallback chain, and logs of tokens, cost and latency.
- Quantum: local statevector simulator (≤22 qubits) running QAOA, VQE and Grover; classical exhaustive search, simulated annealing and tabu; a six-way selection engine with 15 factors; an execution class on every result; jobs and logs.
- Orchestration: six modes; a visible plan before execution (with optional review-before-run); asynchronous worker; cancellation; event stream; AI answers verified with the solver's true objective; benchmarks with methodology and environment; Markdown and JSON reports.
- Command Centre: initialisation sequence from real status (skippable, reduced-motion), computational core driven by real engine states, problem console with file upload and generated scenario forms, scenario library, live console (WebSocket with polling fallback), insights, results workspace with content labels, Demo Mode with explicitly labelled cached results.
- Security: argon2id, session table with revocation, CSRF double-submit, RBAC on every route, account lockout, rate limits (Redis or local), Fernet-encrypted write-only credentials, upload type and size checks, prompt-injection delimiting, CORS restricted to the frontend origin, production configuration gate, audit log.

## Partially completed

- **Administration console.** All screens are built and wired to the API. Scenario input fields are edited as JSON (no visual form builder). Two endpoints added late, test-case editing (`PUT /api/intellect/test-cases/{id}`) and routing-policy deletion (`DELETE /api/ai/routing-policies/{id}`), exist in the API but have no UI controls yet. The Conflict Resolution screen lists conflicts across all versions, although the API now supports `?version_id=`.
- **Intake for free-text problems without AI.** Falls back to the quantum-os keyword classifier, which recognises optimisation templates only, and says so.
- **AI-only answers in benchmarks.** These are verified against the true objective for item-selection templates (knapsack, portfolio, feature selection, vertex cover, independent set, number partition, max-cut). For TSP, assignment, graph colouring and bin packing they are reported as "not comparable".
- **VQE and Grover.** These are available in the library and the selection engine, but no initial scenario binds to them yet. Scenario templates currently cover the QUBO family.
- **Source framework revisions.** A new version of the source PDF must be turned into a new source pack with `scripts/build_source_pack.py`, which refuses on any discrepancy, and reviewed. Imports detect changes to source rules but never apply them.

## Awaiting credentials or accounts

- Live AI calls (any provider): add a key in Admin → AI Management, then run **Check health**.
- AI-dependent steps (AI-only, AI + Intellect, Intellect review in Hybrid, AI interpretation, AI intake) are skipped with that reason until a provider is configured.

## Awaiting physical quantum hardware access

- IBM Quantum, Amazon Braket (IonQ, Rigetti, IQM), Azure Quantum (Quantinuum, IonQ, Rigetti), D-Wave Leap and Google. Adapters exist in the vendored library but are **not verified against live accounts**. Each needs its SDK (`requirements-quantum.txt`), a credential in Admin, the orchestration policy `allow_hardware`, a scenario policy permitting hardware, and a cost cap.
- NVIDIA CUDA-Q and PennyLane adapters are **not implemented**; the brief lists them as candidates. Add them as `qos.providers.*` adapters.

## Known limitations

- Local QAOA simulation slows with size. A 16-qubit, p=3 TSP took about 60 seconds on the development machine. The selection engine caps local simulation at 22 qubits.
- The Intellect pipeline makes 14 model calls per run (13 stages plus the guardrail audit), which affects latency and cost. A compact mode has not been implemented.
- Rule applicability is judged by the model per stage. Without a model, every rule is recorded `not_assessed`, never keyword-matched.
- The source does not split HM rules between read and speak, so both HM stages see all HM rules and the trace shows which each applied.
- File storage: uploaded problem attachments are parsed to text and only metadata is stored; files are not kept. Add object storage if originals must be retained.
- Malware scanning of uploads is not implemented; uploads are parsed as data only (never executed) and limited by type and size.
- Multi-tenancy is not implemented (single organisation, role-based).
- PostgreSQL-specific paths (JSONB, triggers) are covered by dialect-aware code but have been run only against SQLite locally. They will be exercised on the first Render deploy.

## Remaining production risks

1. First deploy on PostgreSQL has not been run. Watch the `0002` trigger migration and the seeding logs.
2. Losing or rotating `X_ENCRYPTION_KEY` makes stored credentials unreadable. Back the key up outside Render.
3. Model latency and cost per Intellect run: set the AI routing policy and the per-call cost cap before opening access widely.
4. The embedded worker is for development only. Production must run x-worker with `X_EMBEDDED_WORKER=false` (the Blueprint does).
5. The WebSocket goes directly to x-api. Restrictive proxies may block it; the UI falls back to polling automatically.

## Next steps

1. Deploy to Render and run the verification checklist in `PRODUCTION_DEPLOYMENT.md`.
2. Add an Anthropic (or other) key and run the Intellect regression suite in the Testing Laboratory with real test cases written by the framework owner.
3. Connect one hardware provider (IBM Quantum or D-Wave Leap free tiers) and run a hardware-labelled benchmark.
4. Add VQE/ground-state and Grover scenarios, and CUDA-Q/PennyLane adapters.
