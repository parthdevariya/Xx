"use client";

import { Badge, Button, ExecBadge, KV, StatusDot, cx, fmtNum } from "@/components/ui";
import { api } from "@/lib/api";
import type { ExecEvent, Execution, PlanStep } from "@/lib/types";

const DECISION_TONE: Record<string, "green" | "cyan" | "blue" | "amber" | "neutral"> = {
  quantum_recommended: "blue", quantum_experimental: "blue", quantum_simulation_recommended: "cyan",
  classical_preferred: "neutral", quantum_not_applicable: "neutral", insufficient_information: "amber",
};

function duration(ex: Execution) {
  if (!ex.started_at) return null;
  const a = new Date(ex.started_at + (ex.started_at.endsWith("Z") ? "" : "Z")).getTime();
  const b = ex.finished_at ? new Date(ex.finished_at + (ex.finished_at.endsWith("Z") ? "" : "Z")).getTime() : Date.now();
  return `${((b - a) / 1000).toFixed(1)} s`;
}

export function Insights({ execution }: { execution: Execution | null }) {
  if (!execution) {
    return <p className="text-sm text-muted">Insights appear when an execution starts: complexity, models, active rules, quantum eligibility, baselines, timing and cost — all from the backend record.</p>;
  }
  const s = (execution.problem?.structured ?? {}) as Record<string, unknown>;
  const qd = execution.plan?.quantum_decision;
  const classical = execution.results?.find((r) => r.step === "classical")?.content as Record<string, unknown> | undefined;
  const quantum = execution.results?.find((r) => r.step === "quantum");
  const intellect = execution.results?.find((r) => r.step === "intellect")?.content as Record<string, unknown> | undefined;
  const isummary = (intellect?.summary ?? {}) as Record<string, unknown>;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusDot status={execution.status} />
        <span className="text-sm text-text">{execution.status.replace("_", " ")}</span>
        <Badge>{execution.mode_label}</Badge>
        {execution.result_source === "test" && <Badge tone="red">Test provider</Badge>}
        {execution.is_demo && <Badge tone="green">Demo run</Badge>}
      </div>
      <KV items={[
        ["Category", String(s.category ?? "—")],
        ["Complexity", String(s.complexity ?? "—")],
        ["Formulation", s.solver_template ? <span className="font-mono text-xs">{String(s.solver_template)}</span> : "none (reasoning)"],
        ["Intake method", String(s.method ?? "—").replace(/_/g, " ")],
        ["AI model", execution.ai_model ? `${execution.ai_provider} / ${execution.ai_model}` : "—"],
        ["Framework", execution.framework_version ? `X Layers ${execution.framework_version}` : "—"],
        ["Rules applied", isummary.rules_applied ? String((isummary.rules_applied as string[]).length) : "—"],
        ["Quantum", qd ? <Badge className="!whitespace-normal" tone={DECISION_TONE[qd.decision] ?? "neutral"}>{qd.decision.replace(/_/g, " ")}</Badge> : "—"],
        ["Quantum backend", quantum ? <span className="inline-flex flex-wrap items-center gap-1.5"><span className="font-mono text-xs">{execution.quantum_backend}</span><ExecBadge cls={quantum.execution_class} /></span> : "—"],
        ["Classical baseline", classical ? `${classical.algorithm} · ${classical.proven_optimal ? "proven optimum" : "best found"}` : "—"],
        ["Result quality", classical ? `objective ${fmtNum(classical.objective_value)} · ${classical.feasible ? "feasible" : "infeasible"}` : "—"],
        ["Duration", duration(execution)],
        ["Cost", `$${execution.actual_cost_usd.toFixed(4)} actual · $${execution.estimated_cost_usd.toFixed(4)} est.`],
      ]} />
      {execution.error && <p className={cx("rounded-md border px-3 py-2 text-xs", execution.status === "awaiting_input" ? "border-amber/30 text-amber" : "border-red/30 text-red")}>{execution.error}</p>}
    </div>
  );
}

// Live step status from recorded events (the stored plan is the pre-run snapshot).
const STEP_EVENTS: Record<string, { done: RegExp; active: RegExp }> = {
  classical: { done: /^classical\.completed$/, active: /^classical\.started$/ },
  quantum: { done: /^quantum\.(completed|unavailable)$/, active: /^quantum\.job_submitted$/ },
  ai_reason: { done: /^ai\.(completed|unavailable)$/, active: /^ai\.started$/ },
  ai_explain: { done: /^ai\.(completed|unavailable)$/, active: /^ai\.started$/ },
  intellect: { done: /^intellect\.(completed|failed)$/, active: /^intellect\.activated$/ },
  benchmark: { done: /^benchmark\.completed$/, active: /^benchmark\.started$/ },
  synthesize: { done: /^execution\.completed$/, active: /^$/ },
};

function liveStatus(step: PlanStep, events: ExecEvent[], execStatus: string): string {
  if (step.status !== "planned") return step.status;
  const m = STEP_EVENTS[step.key];
  if (m && events.some((e) => m.done.test(e.type))) return "completed";
  if (m && events.some((e) => m.active.test(e.type))) return execStatus === "running" ? "running" : execStatus;
  if (["failed", "cancelled"].includes(execStatus)) return "not run";
  return "planned";
}

export function PlanView({ execution, events, onRun }: { execution: Execution; events: ExecEvent[]; onRun: () => void }) {
  const plan = execution.plan;
  if (!plan) return null;
  const canStart = execution.status === "planned";
  async function cancel() {
    await api.post(`/executions/${execution.id}/cancel`);
  }
  return (
    <div className="space-y-3">
      <ol className="space-y-1.5">
        {plan.steps.map((s, i) => {
          const st = liveStatus(s, events, execution.status);
          return (
            <li key={s.key} className="grid grid-cols-[22px_1fr_auto] items-start gap-2 text-sm">
              <span className="pt-0.5 font-mono text-[11px] text-muted">{String(i + 1).padStart(2, "0")}</span>
              <div className="min-w-0">
                <div className={cx(st === "skipped" ? "text-muted line-through decoration-muted/40" : "text-text")}>{s.title}</div>
                {s.reason && <div className="text-[11.5px] text-muted">{s.reason}</div>}
              </div>
              <Badge tone={st === "skipped" || st === "not run" ? "neutral" : st === "completed" ? "green" : st === "failed" ? "red" : "cyan"}>{st}</Badge>
            </li>
          );
        })}
      </ol>
      {plan.quantum_decision && (
        <p className="rounded-md border border-line bg-white/[0.02] p-2.5 text-[12.5px] text-dim">
          <span className="text-muted">Quantum selection:</span> {plan.quantum_decision.explanation}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <span>Estimated AI calls: {plan.estimates?.ai_calls ?? 0}</span>
        <span>· Quantum cost: ${Number(plan.estimates?.quantum_cost_usd ?? 0).toFixed(4)}</span>
      </div>
      <div className="flex gap-2">
        {canStart && <Button variant="primary" size="sm" onClick={onRun}>Run this plan</Button>}
        {["planned", "queued", "running"].includes(execution.status) && <Button size="sm" variant="ghost" onClick={cancel}>Cancel</Button>}
      </div>
    </div>
  );
}
