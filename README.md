# X — Hybrid AI + Quantum + Intellect computational platform

X takes a problem, decides which computational engines genuinely apply, runs them through one shared orchestration layer, and returns a traceable, benchmarked result. Each part of the result is labelled by how it was produced.

- **AI** — provider-independent model layer (Anthropic, OpenAI-compatible: OpenAI, Azure OpenAI, Gemini, Ollama, LM Studio, vLLM…) with routing, fallback, usage and cost logging.
- **Quantum** — built on the vendored `quantum-os` library: a local statevector simulator, QAOA, VQE and Grover, classical baselines, and adapters for IBM, Braket, Azure, D-Wave and Google. A six-way **Quantum Selection Engine** decides when quantum computation applies, and does not recommend it by default.
- **Intellect** — the X Layers v0.3B framework (10 layers, 93 rules) imported verbatim from `docs/source/X_Layers_v0.3B_Rules.pdf`. It runs as the exact 13-stage source sequence, with database-enforced guardrails, deterministic conflict resolution, versioning, a Framework Builder, imports and a Testing Laboratory.

## Repository

```
backend/    FastAPI app (app/), vendored quantum-os (qos/), Alembic migrations, tests
frontend/   Next.js command centre (/) and administration console (/admin)
docs/       PROJECT_AUDIT, SYSTEM_ARCHITECTURE, DATABASE_SCHEMA, IMPLEMENTATION_ROADMAP,
            PRODUCTION_DEPLOYMENT, source/X_Layers_v0.3B_Rules.pdf
render.yaml Render Blueprint (x-web, x-api, x-worker, PostgreSQL, Key Value)
```

## Quick start (local)

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
cp .env.example .env    # set X_SECRET_KEY, X_BOOTSTRAP_ADMIN_EMAIL/PASSWORD
.venv/Scripts/python -m uvicorn app.main:app --port 8000

cd ../frontend && npm install && npm run dev   # http://localhost:3000
```

The API documentation is served at `http://localhost:8000/docs` (OpenAPI at `/openapi.json`).

With no API keys configured, X still works fully for computed problems: classical solvers and quantum simulation. AI-dependent steps are shown as **skipped (no AI provider)** and are never faked. Add a key in Admin → AI Management to enable them.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest
```

The suite has 122 tests and uses no network or paid APIs. It covers Intellect acceptance (93 rules byte-for-byte against the PDF, the exact sequence, guardrails blocked at the database, service and API levels, the hierarchy, versioning, and publication blocking), every execution mode end to end, the Anthropic adapter's request shape and refusal handling, router fallback, quantum selection decisions, and imports.

## Honesty rules built into the code

- Every quantum result carries an execution class (`hardware`, `cloud_simulator`, `local_simulator`, `classical`, `cached`, `test`) derived from the backend's modality, never from the caller.
- Results are labelled `computed`, `model_generated`, `assumption`, `estimate`, `cached` or `test`.
- Live-console messages are stored backend events. The core animation reflects real engine states.
- Benchmarks score every approach with the same true-objective function and state that simulator timings are not evidence of quantum advantage.
- `quantum_recommended` requires admin-entered, cited benefit evidence. None ships.

See `docs/IMPLEMENTATION_ROADMAP.md` for what is complete, what awaits credentials, and the known limitations.
