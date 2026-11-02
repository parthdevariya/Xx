"""Exportable execution reports (Markdown and JSON), stored as execution artifacts."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BenchmarkRun, Execution, ExecutionArtifact, ExecutionResult, IntellectConflict, IntellectRun

CLASS_LABEL = {"computed": "Computed", "model_generated": "Model-generated", "assumption": "Assumption",
               "estimate": "Estimate", "cached": "Cached", "test": "TEST PROVIDER (not a real model)"}


def _fmt_content(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(f"- {x}" for x in c) or "_none_"
    return "```json\n" + json.dumps(c, indent=2, default=str)[:20000] + "\n```"


def build_report(db: Session, execution: Execution) -> tuple[str, dict]:
    problem = execution.problem
    out = execution.final_output or {}
    results = db.scalars(select(ExecutionResult).where(ExecutionResult.execution_id == execution.id)).all()
    bench = db.scalar(select(BenchmarkRun).where(BenchmarkRun.execution_id == execution.id))
    runs = db.scalars(select(IntellectRun).where(IntellectRun.execution_id == execution.id)).all()
    lines = [
        f"# X Execution Report — {execution.id}",
        "",
        f"- Mode: **{execution.mode}**  ·  Status: **{execution.status}**  ·  Result source: "
        f"**{execution.result_source}**",
        f"- Started: {execution.started_at}  ·  Finished: {execution.finished_at}",
        f"- AI: {execution.ai_provider or '—'} {execution.ai_model or ''}  ·  Quantum backend: "
        f"{execution.quantum_backend or '—'} {execution.algorithm or ''}",
        "",
        "## Problem",
        problem.text or (problem.structured or {}).get("problem_text", ""),
        "",
    ]
    order = ["executive_summary", "detailed_solution", "methodology", "reasoning_trace", "supporting_calculations",
             "quantum_contribution", "classical_comparison", "ai_answer_verification", "benchmark", "interpretation",
             "assumptions", "limitations", "confidence"]
    for key in order:
        sec = out.get(key)
        if not sec:
            continue
        lines += [f"## {key.replace('_', ' ').title()}  _[{CLASS_LABEL.get(sec['class'], sec['class'])}]_",
                  _fmt_content(sec["content"]), ""]
    if bench:
        lines += ["## Benchmark metrics", "", "| Approach | Metric | Value | Unit | Notes |", "|---|---|---|---|---|"]
        for m in bench.metrics:
            val = m.text_value if m.value is None else f"{m.value:.6g}"
            lines.append(f"| {m.approach} | {m.metric} | {val} | {m.unit} | {m.notes} |")
        lines += ["", "**Methodology**", _fmt_content(bench.methodology), "", "**Environment**",
                  _fmt_content(bench.environment), "", f"**Conclusion:** {bench.conclusion}", ""]
    for run in runs:
        conflicts = db.scalars(select(IntellectConflict).where(IntellectConflict.run_id == run.id)).all()
        lines += [f"## Intellect run {run.id} ({run.status}, assessment: {run.assessment_mode})",
                  f"Rules applied: {', '.join(run.summary.get('rules_applied', [])) or 'none'}", ""]
        for cf in conflicts:
            lines.append(f"- Conflict {' vs '.join(cf.rule_codes)} → **{cf.winner}** ({cf.hierarchy_step}): "
                         f"{cf.decision}")
        lines.append("")
    md = "\n".join(lines)
    payload = {"execution_id": execution.id, "mode": execution.mode, "status": execution.status,
               "result_source": execution.result_source, "final_output": out,
               "results": [{"step": r.step_key, "engine": r.engine, "class": r.content_class,
                            "execution_class": r.execution_class, "title": r.title, "content": r.content}
                           for r in results],
               "benchmark": ({"conclusion": bench.conclusion, "methodology": bench.methodology,
                              "environment": bench.environment,
                              "metrics": [{"approach": m.approach, "metric": m.metric, "value": m.value,
                                           "text": m.text_value, "unit": m.unit, "notes": m.notes}
                                          for m in bench.metrics]} if bench else None)}
    for kind, name, ctype, content in (("report_md", f"x-report-{execution.id}.md", "text/markdown", md),
                                       ("report_json", f"x-report-{execution.id}.json", "application/json",
                                        json.dumps(payload, default=str, indent=1))):
        existing = db.scalar(select(ExecutionArtifact).where(ExecutionArtifact.execution_id == execution.id,
                                                             ExecutionArtifact.kind == kind))
        if existing:
            existing.content = content
        else:
            db.add(ExecutionArtifact(execution_id=execution.id, kind=kind, name=name, content_type=ctype,
                                     content=content))
    db.commit()
    return md, payload
