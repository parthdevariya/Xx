"""Intellect Testing Laboratory: lab runs, expectations, comparisons and regression suites."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import IntellectExecutionLog, IntellectRun, IntellectTestCase, IntellectVersion, utcnow
from .pipeline import run_framework


def count_questions(text: str) -> int:
    """Questions in the reply, excluding quoted drafts (text inside quotation marks or blockquotes)."""
    stripped = re.sub(r"(?m)^>.*$", "", text)
    stripped = re.sub(r"[\"“][^\"”]*[\"”]", "", stripped)
    return stripped.count("?")


def rule_states(db: Session, run: IntellectRun) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for log in db.scalars(select(IntellectExecutionLog).where(IntellectExecutionLog.run_id == run.id)
                          .order_by(IntellectExecutionLog.position)):
        for s in log.rule_states:
            out.setdefault(s["rule"], []).append({**s, "stage": log.position, "mode": log.mode})
    return out


def evaluate(db: Session, run: IntellectRun, expected: dict) -> dict:
    states = rule_states(db, run)
    applied = {code for code, ss in states.items() if any(s["state"] == "applied" for s in ss)}
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    if run.status != "completed":
        check("run completed", False, f"run status {run.status}: {run.error}")
    for code in expected.get("must_apply", []):
        check(f"{code} applied", code in applied, "; ".join(s["reason"] for s in states.get(code, []))[:300])
    for code in expected.get("must_not_apply", []):
        check(f"{code} not applied", code not in applied)
    text = run.final_output or ""
    for phrase in expected.get("must_contain", []):
        check(f"reply contains '{phrase}'", phrase.lower() in text.lower())
    for phrase in expected.get("must_not_contain", []):
        check(f"reply avoids '{phrase}'", phrase.lower() not in text.lower())
    if "max_questions" in expected:
        n = count_questions(text)
        check(f"at most {expected['max_questions']} question(s)", n <= expected["max_questions"], f"found {n}")
    if expected.get("guardrail_audit_clean", True):
        audit = (run.summary or {}).get("guardrail_audit") or {}
        breaches = audit.get("breaches", [])
        check("guardrail audit clean", not breaches, ", ".join(b.get("rule", "") for b in breaches))
    passed = all(c["passed"] for c in checks) if checks else run.status == "completed"
    return {"passed": passed, "checks": checks, "assessment_mode": run.assessment_mode}


def compare_runs(db: Session, a: IntellectRun, b: IntellectRun) -> dict:
    sa, sb = rule_states(db, a), rule_states(db, b)

    def summary(ss):
        states = {s["state"] for s in ss}
        return "applied" if "applied" in states else sorted(states)[0] if states else "absent"
    diffs = []
    for code in sorted(set(sa) | set(sb)):
        x, y = summary(sa.get(code, [])), summary(sb.get(code, []))
        if x != y:
            diffs.append({"rule": code, "a": x, "b": y})
    return {"a": a.id, "b": b.id, "a_switches": a.layer_switches, "b_switches": b.layer_switches,
            "rule_differences": diffs, "a_output": a.final_output, "b_output": b.final_output}


def run_case(db: Session, case: IntellectTestCase, version: IntellectVersion, user_id: str | None,
             origin: str = "lab") -> tuple[IntellectRun, dict]:
    res = run_framework(db, version, case.prompt, layer_switches=case.layer_switches, origin=origin,
                        test_case_id=case.id, user_id=user_id)
    outcome = evaluate(db, res.run, case.expected or {})
    res.run.summary = {**res.run.summary, "evaluation": outcome}
    case.last_run_id = res.run.id
    case.last_outcome = "pass" if outcome["passed"] else "fail"
    db.flush()
    return res.run, outcome


def run_lab_job(db: Session, payload: dict) -> dict:
    """Background lab run (14 model calls is too long for an HTTP request)."""
    from .pipeline import IntellectUnavailable
    version = db.get(IntellectVersion, payload["version_id"])
    case = db.get(IntellectTestCase, payload["test_case_id"]) if payload.get("test_case_id") else None
    try:
        if case:
            run, outcome = run_case(db, case, version, payload.get("user_id"))
            db.commit()
            return {"run_id": run.id, "evaluation": outcome}
        res = run_framework(db, version, payload["prompt"], layer_switches=payload.get("layer_switches") or {},
                            origin="lab", user_id=payload.get("user_id"))
        db.commit()
        return {"run_id": res.run.id}
    except IntellectUnavailable as e:
        db.commit()
        return {"error": str(e)}


def run_regression(db: Session, framework_id: str, version_id: str, user_id: str | None) -> dict:
    version = db.get(IntellectVersion, version_id)
    cases = db.scalars(select(IntellectTestCase).where(IntellectTestCase.framework_id == framework_id)).all()
    results = []
    for case in cases:
        try:
            run, outcome = run_case(db, case, version, user_id, origin="regression")
            results.append({"case": case.name, "passed": outcome["passed"], "run_id": run.id})
        except Exception as e:  # noqa: BLE001
            case.last_outcome = "error"
            results.append({"case": case.name, "passed": False, "error": str(e)[:500]})
        db.commit()
    summary = {"version": version.label, "total": len(results), "passed": sum(r["passed"] for r in results),
               "results": results, "at": utcnow().isoformat()}
    version.validation = {**(version.validation or {}), "regression": summary}
    db.commit()
    return summary
