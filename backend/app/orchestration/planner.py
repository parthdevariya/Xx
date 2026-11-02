"""Computational planning: mode + structured problem + quantum decision → ordered, visible steps.

Steps whose engine cannot run are included with status "skipped" and the reason, so the plan the user
sees is the plan that runs.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..ai import service as ai
from ..models import IntellectFramework, IntellectVersion
from ..quantum import selection

MODES = {
    "ai_only": "AI Only",
    "ai_intellect": "AI + Intellect",
    "classical": "Classical Computation",
    "ai_quantum": "AI + Quantum",
    "hybrid": "Full Hybrid X",
    "benchmark": "Comparative Benchmark",
}


def _step(key, engine, title, status="planned", reason="", **extra):
    return {"key": key, "engine": engine, "title": title, "status": status, "reason": reason, **extra}


def active_framework_version(db: Session, slug: str = "x-layers") -> IntellectVersion | None:
    from sqlalchemy import select
    fw = db.scalar(select(IntellectFramework).where(IntellectFramework.slug == slug))
    if fw is None or fw.active_version_id is None:
        return None
    return db.get(IntellectVersion, fw.active_version_id)


def plan(db: Session, *, mode: str, problem: dict, allow_hardware: bool = False, max_cost_usd: float = 0.0,
         framework_slug: str = "x-layers") -> dict:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    template = problem.get("solver_template")
    data = problem.get("template_data") or {}
    missing = problem.get("missing_information") or []
    ai_ok = ai.any_model_available(db, allow_test=ai.test_provider_allowed(db))
    version = active_framework_version(db, framework_slug)
    no_ai = "no AI provider is configured and available (Admin → AI Management)"
    no_solver = ("the problem has no solver formulation" if not template else
                 f"required data is missing: {'; '.join(missing)}" if missing else "")

    decision = selection.evaluate(db, template=template, data=data, missing=missing if template else None,
                                  mode=mode, allow_hardware=allow_hardware, max_cost_usd=max_cost_usd,
                                  eligibility=problem.get("quantum_eligibility", "evaluate"))
    run_q = decision["run_quantum"]
    q_reason = decision["explanation"]
    computable = bool(template) and not missing
    steps: list[dict] = [_step("intake", "system", "Problem intake and classification", status="completed")]

    def ai_step():
        return _step("ai_reason", "ai", "AI reasoning", "planned" if ai_ok else "skipped", "" if ai_ok else no_ai)

    def intellect_step(title="Intellect framework (13 stages)"):
        if version is None:
            return _step("intellect", "intellect", title, "skipped", "no published framework version")
        return _step("intellect", "intellect", f"{title} — {version.label}", "planned" if ai_ok else "skipped",
                     "" if ai_ok else no_ai, framework_version=version.label)

    def classical_step():
        return _step("classical", "classical", "Classical solver (baseline)",
                     "planned" if computable else "skipped", no_solver)

    def quantum_steps(force_study: bool):
        s = [_step("quantum_select", "quantum", "Quantum suitability evaluation", "completed",
                   decision=decision["decision"])]
        if run_q:
            route = decision.get("route", {})
            s.append(_step("quantum", "quantum", f"Quantum execution — {route.get('algorithm')} on "
                                                 f"{route.get('backend_name')}", execution_class=route.get(
                                                     "execution_class")))
        elif force_study and decision.get("simulation_available"):
            route = decision.get("route", {})
            s.append(_step("quantum", "quantum", f"Quantum simulation for comparison — {route.get('algorithm')} on "
                                                 f"{route.get('backend_name')}", execution_class=route.get(
                                                     "execution_class"), note="comparison only"))
        else:
            s.append(_step("quantum", "quantum", "Quantum execution", "skipped", q_reason))
        return s

    if mode == "ai_only":
        steps.append(ai_step())
    elif mode == "ai_intellect":
        steps.append(intellect_step())
    elif mode == "classical":
        steps.append(classical_step())
    elif mode == "ai_quantum":
        steps += quantum_steps(force_study=True)
        steps.append(classical_step() | {"title": "Classical reference for comparison"})
        steps.append(_step("ai_explain", "ai", "AI interpretation of computed results",
                           "planned" if ai_ok else "skipped", "" if ai_ok else no_ai))
    elif mode == "hybrid":
        steps += quantum_steps(force_study=False)
        steps.append(classical_step())
        steps.append(intellect_step("Intellect review of the computed evidence" if computable else
                                    "Intellect framework (13 stages)"))
    elif mode == "benchmark":
        steps += quantum_steps(force_study=True)
        steps.append(classical_step())
        steps.append(ai_step() | {"title": "AI Only (independent attempt)"})
        steps.append(intellect_step("AI + Intellect (independent attempt)"))
        steps.append(_step("benchmark", "system", "Benchmark comparison"))
    steps.append(_step("synthesize", "system", "Final result and report"))

    planned = [s for s in steps if s["status"] == "planned"]
    ai_calls = sum(1 for s in planned if s["engine"] == "ai") + (
        (len(version.pipeline) + 1) if version and any(s["key"] == "intellect" for s in planned) else 0)
    q = next((s for s in planned if s["key"] == "quantum"), None)
    return {
        "mode": mode, "mode_label": MODES[mode], "steps": steps, "quantum_decision": decision,
        "estimates": {"ai_calls": ai_calls,
                      "quantum_cost_usd": decision.get("route", {}).get("est_cost_usd", 0.0) if q else 0.0},
        "baselines": ["classical"] if computable else [],
        "runnable": any(s["key"] not in ("synthesize", "benchmark") for s in planned),
    }
