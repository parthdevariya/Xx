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
    "intellect_vs_ai": "Intellect vs AI (judged proof)",
    "classical": "Classical Computation",
    "quantum": "Quantum Only",
    "classical_quantum": "Classical vs Quantum",
    "ai_classical": "AI + Classical",
    "classical_intellect": "Classical + Intellect",
    "ai_quantum": "AI + Quantum",
    "hybrid": "Full Hybrid X",
    "benchmark": "Comparative Benchmark",
    "matrix": "All Combinations Matrix",
}

# What each mode runs — shown to administrators and users.
MODE_INFO = {
    "ai_only": {"engines": ["ai"], "needs": ["ai"],
                "description": "One model answers directly. The baseline every other mode is compared with."},
    "ai_intellect": {"engines": ["ai", "intellect"], "needs": ["ai"],
                     "description": "The full Intellect framework: 13 ordered stages, protected guardrails, conflict "
                                    "resolution and a final guardrail audit."},
    "intellect_vs_ai": {"engines": ["ai", "intellect"], "needs": ["ai"],
                        "description": "AI Only and AI + Intellect answer the same problem independently, then a "
                                       "blind judge scores both against a rubric fixed before the run, plus "
                                       "deterministic checks. Shows which rules made the difference."},
    "classical": {"engines": ["classical"], "needs": ["solver"],
                  "description": "Classical solver only: exhaustive search (proven optimum) or heuristics."},
    "quantum": {"engines": ["quantum"], "needs": ["solver"],
                "description": "Quantum algorithm only, on the best available simulator or hardware."},
    "classical_quantum": {"engines": ["classical", "quantum"], "needs": ["solver"],
                          "description": "Classical and quantum on the same encoding, scored by the same true "
                                         "objective, with a benchmark report. No AI involved."},
    "ai_classical": {"engines": ["classical", "ai"], "needs": ["solver", "ai"],
                     "description": "Classical computation, then AI explains the verified result."},
    "classical_intellect": {"engines": ["classical", "intellect", "ai"], "needs": ["solver", "ai"],
                            "description": "Computation plus judgment: the verified optimum is reviewed by the "
                                           "Intellect framework, which can flag what the optimiser cannot see."},
    "ai_quantum": {"engines": ["quantum", "classical", "ai"], "needs": ["solver"],
                   "description": "Quantum study with a classical reference and AI interpretation."},
    "hybrid": {"engines": ["quantum", "classical", "intellect", "ai"], "needs": ["solver|ai"],
               "description": "Everything that applies: quantum if suitable, classical, then Intellect review of "
                              "the computed evidence."},
    "matrix": {"engines": ["ai", "intellect", "classical", "quantum"], "needs": ["solver|ai"],
               "description": "Every valid engine combination (11) on the same problem: AI Only, AI + Intellect, "
                              "AI + Quantum, AI + Intellect + Quantum, Classical vs Quantum and the rest. Each AI "
                              "answer is scored by one blind judge on the same rubric; computation by the true "
                              "objective. Combinations that cannot contribute are marked not applicable."},
    "benchmark": {"engines": ["quantum", "classical", "ai", "intellect"], "needs": ["solver|ai"],
                  "description": "Every eligible approach runs independently on the same input and is compared; "
                                 "includes the judged Intellect-vs-AI proof when a rubric exists."},
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
    elif mode == "intellect_vs_ai":
        steps.append(ai_step() | {"title": "AI Only (independent answer)"})
        steps.append(intellect_step("AI + Intellect (independent answer)"))
        steps.append(_step("proof", "system", "Blind judged comparison against the rubric",
                           "planned" if ai_ok else "skipped", "" if ai_ok else no_ai))
    elif mode == "classical":
        steps.append(classical_step())
    elif mode == "quantum":
        steps += quantum_steps(force_study=True)
    elif mode == "classical_quantum":
        steps += quantum_steps(force_study=True)
        steps.append(classical_step())
        steps.append(_step("benchmark", "system", "Classical vs quantum benchmark"))
    elif mode == "ai_classical":
        steps.append(classical_step())
        steps.append(_step("ai_explain", "ai", "AI interpretation of the verified result",
                           "planned" if ai_ok and computable else "skipped",
                           no_ai if not ai_ok else no_solver))
    elif mode == "classical_intellect":
        steps.append(classical_step())
        steps.append(intellect_step("Intellect review of the computed evidence"))
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
    elif mode == "matrix":
        steps += quantum_steps(force_study=True)
        steps.append(classical_step())
        combos_n = 11 if computable else 2
        steps.append(_step("combinations", "system", f"All engine combinations ({combos_n} applicable) + blind judge",
                           "planned" if (ai_ok or computable) else "skipped", "" if (ai_ok or computable) else no_ai))
    elif mode == "benchmark":
        steps += quantum_steps(force_study=True)
        steps.append(classical_step())
        steps.append(ai_step() | {"title": "AI Only (independent attempt)"})
        steps.append(intellect_step("AI + Intellect (independent attempt)"))
        if ai_ok and problem.get("rubric"):
            steps.append(_step("proof", "system", "Blind judged comparison against the rubric"))
        steps.append(_step("benchmark", "system", "Benchmark comparison"))
    steps.append(_step("synthesize", "system", "Final result and report"))

    planned = [s for s in steps if s["status"] == "planned"]
    ai_calls = (4 * (len(version.pipeline) + 1) + 5 if computable else 2 * (len(version.pipeline) + 1) + 2)         if version and mode == "matrix" and ai_ok else 0
    ai_calls += sum(1 for s in planned if s["engine"] == "ai") + (
        (len(version.pipeline) + 1) if version and any(s["key"] == "intellect" for s in planned) else 0)
    q = next((s for s in planned if s["key"] == "quantum"), None)
    return {
        "mode": mode, "mode_label": MODES[mode], "steps": steps, "quantum_decision": decision,
        "estimates": {"ai_calls": ai_calls,
                      "quantum_cost_usd": decision.get("route", {}).get("est_cost_usd", 0.0) if q else 0.0},
        "baselines": ["classical"] if computable else [],
        "runnable": any(s["key"] not in ("synthesize", "benchmark", "proof") for s in planned),
    }
