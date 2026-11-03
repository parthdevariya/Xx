"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { MatrixView } from "./MatrixView";
import { ProofView } from "./ProofView";
import { Badge, ContentBadge, Empty, ExecBadge, JsonView, KV, Notice, Table, Tabs, Td, cx, fmtNum } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { BenchmarkMetric, Execution, MatrixResult, ProofResult, Section } from "@/lib/types";

type Tab = "matrix" | "proof" | "summary" | "solution" | "method" | "reasoning" | "calc" | "quantum" | "benchmark" | "raw";

function sec(ex: Execution, key: string): Section | null {
  const v = ex.final_output?.[key];
  return v && typeof v === "object" ? (v as Section) : null;
}

function Prose({ text }: { text: string }) {
  return <div className="whitespace-pre-wrap text-[14px] leading-relaxed text-text">{text}</div>;
}

function SectionBlock({ title, s, children }: { title: string; s: Section | null; children?: React.ReactNode }) {
  if (!s && !children) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="x-label !text-dim">{title}</h3>
        {s && <ContentBadge cls={s.class} />}
      </div>
      {children ?? <Content value={s!.content} />}
    </div>
  );
}

function Content({ value }: { value: unknown }) {
  if (typeof value === "string") return <Prose text={value} />;
  if (Array.isArray(value)) {
    if (!value.length) return <span className="text-sm text-muted">None.</span>;
    return <ul className="list-disc space-y-1 pl-5 text-sm text-text">{value.map((v, i) => <li key={i}>{typeof v === "string" ? v : JSON.stringify(v)}</li>)}</ul>;
  }
  return <JsonView value={value} />;
}

function Answer({ answer }: { answer: Record<string, unknown> }) {
  const tour = (answer.tour_names ?? answer.tour) as unknown[] | undefined;
  return (
    <div className="space-y-3">
      {Array.isArray(tour) && (
        <div>
          <div className="x-label mb-1.5">Route</div>
          <div className="flex flex-wrap items-center gap-1.5">
            {[...tour, tour[0]].map((t, i) => (
              <span key={i} className="flex items-center gap-1.5">
                <span className="rounded border border-green/30 bg-green/5 px-2 py-0.5 font-mono text-xs text-green">{String(t)}</span>
                {i < tour.length && <span className="text-muted">→</span>}
              </span>
            ))}
          </div>
        </div>
      )}
      <KV items={Object.entries(answer).filter(([k]) => k !== "assignment").map(([k, v]) => [
        k.replace(/_/g, " "),
        Array.isArray(v) ? <span className="font-mono text-xs">{v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ")}</span>
          : typeof v === "object" && v !== null ? <span className="font-mono text-xs">{JSON.stringify(v)}</span>
          : typeof v === "number" ? fmtNum(v) : String(v),
      ])} />
    </div>
  );
}

function SolverCard({ title, c, execClass }: { title: string; c: Record<string, unknown>; execClass: string }) {
  if (c.error) return <Notice tone="warn">{title}: {String(c.error)}</Notice>;
  const counts = (c.top_counts as [string, number][] | undefined) ?? [];
  const max = Math.max(1, ...counts.map(([, n]) => n));
  return (
    <div className="rounded-md border border-line p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-display text-sm font-medium">{title}</span>
        <ExecBadge cls={execClass} />
        <ContentBadge cls="computed" />
      </div>
      <KV items={[
        ["Algorithm", <span key="a" className="font-mono text-xs">{String(c.algorithm)} on {String(c.backend_key)}</span>],
        ["Objective", fmtNum(c.objective_value)],
        ["Feasible", c.feasible ? "yes" : <span className="text-amber">no — {(c.violations as string[] | undefined)?.join("; ")}</span>],
        ["Optimality", c.proven_optimal ? "proven optimum of the encoding" : "not proven"],
        ["Variables", fmtNum(c.num_vars)],
        ...(c.qubits ? [["Qubits / depth / shots", `${c.qubits} / ${c.circuit_depth} / ${c.shots}`] as [string, React.ReactNode]] : []),
        ["Wall time", `${Number(c.wall_time_s ?? 0).toFixed(3)} s`],
      ]} />
      {counts.length > 0 && (
        <div className="mt-3">
          <div className="x-label mb-1">Most frequent measurement outcomes</div>
          <div className="space-y-1">
            {counts.map(([b, n]) => (
              <div key={b} className="grid grid-cols-[1fr_auto] items-center gap-2 font-mono text-[11px]">
                <div className="relative h-4 overflow-hidden rounded bg-white/[0.03]">
                  <div className="absolute inset-y-0 left-0 bg-blue/30" style={{ width: `${(n / max) * 100}%` }} />
                  <span className="relative px-1.5 text-dim">{b}</span>
                </div>
                <span className="text-muted">{n}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function BenchmarkView({ b }: { b: NonNullable<Execution["benchmark"]> }) {
  const objectives = b.metrics.filter((m) => m.metric === "objective_value" && m.value !== null) as (BenchmarkMetric & { value: number })[];
  const max = Math.max(1e-9, ...objectives.map((m) => Math.abs(m.value)));
  const approaches = Array.from(new Set(b.metrics.map((m) => m.approach)));
  const metrics = Array.from(new Set(b.metrics.map((m) => m.metric)));
  const cell = (a: string, k: string) => {
    const m = b.metrics.find((x) => x.approach === a && x.metric === k);
    if (!m) return <span className="text-muted">—</span>;
    return <span title={m.notes}>{m.value === null ? m.text : `${fmtNum(m.value)}${m.unit ? " " + m.unit : ""}`}</span>;
  };
  return (
    <div className="space-y-4">
      <Notice>{b.conclusion}</Notice>
      {objectives.length > 0 && (
        <div>
          <div className="x-label mb-2">Objective value by approach (same objective function)</div>
          <div className="space-y-1.5">
            {objectives.map((m) => (
              <div key={m.approach} className="grid grid-cols-[150px_1fr_70px] items-center gap-2 text-xs">
                <span className="truncate text-dim">{m.approach}</span>
                <div className="h-3 rounded bg-white/[0.03]">
                  <div className={cx("h-3 rounded", m.approach.startsWith("quantum") ? "bg-blue/60" : m.approach.startsWith("ai") ? "bg-cyan/60" : "bg-green/60")}
                    style={{ width: `${(Math.abs(m.value) / max) * 100}%` }} />
                </div>
                <span className="text-right font-mono">{fmtNum(m.value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <Table head={["Metric", ...approaches]}>
        {metrics.map((k) => (
          <tr key={k}>
            <Td className="text-muted">{k.replace(/_/g, " ")}</Td>
            {approaches.map((a) => <Td key={a} mono>{cell(a, k)}</Td>)}
          </tr>
        ))}
      </Table>
      <div>
        <div className="x-label mb-1.5">Methodology</div>
        <KV items={Object.entries(b.methodology).map(([k, v]) => [k.replace(/_/g, " "), v])} />
      </div>
      <div>
        <div className="x-label mb-1.5">Environment · input hash <span className="font-mono normal-case">{b.input_sha256.slice(0, 16)}…</span></div>
        <JsonView value={b.environment} maxHeight={160} />
      </div>
    </div>
  );
}

export function Results({ execution }: { execution: Execution | null }) {
  const [tab, setTab] = useState<Tab>("summary");
  const { can } = useAuth();
  const proofResult = execution?.results?.find((r) => r.step === "proof")?.content as ProofResult | undefined;
  const hasProof = !!proofResult?.criteria;
  const matrixResult = execution?.results?.find((r) => r.step === "combinations")?.content as MatrixResult | undefined;
  const hasMatrix = !!matrixResult?.combinations;
  useEffect(() => {
    if (hasMatrix) setTab("matrix");
    else if (hasProof) setTab("proof");
  }, [hasProof, hasMatrix, execution?.id]);
  if (!execution) return <Empty>Results appear here: executive summary, solution, methodology, reasoning trace, calculations, quantum contribution, benchmark and limitations.</Empty>;
  const done = execution.status === "completed";
  const results = execution.results ?? [];
  const classical = results.find((r) => r.step === "classical");
  const quantum = results.find((r) => r.step === "quantum");
  const ai = results.find((r) => r.step === "ai_reason");
  const intellect = results.find((r) => r.step === "intellect");
  const detail = sec(execution, "detailed_solution");
  const tabs: { value: Tab; label: string }[] = [
    ...(hasMatrix ? [{ value: "matrix" as Tab, label: "All combinations" }] : []),
    ...(hasProof ? [{ value: "proof" as Tab, label: "Without vs With Intellect" }] : []),
    { value: "summary", label: "Summary" }, { value: "solution", label: "Solution" }, { value: "method", label: "Methodology" },
    { value: "reasoning", label: "Reasoning" }, { value: "calc", label: "Calculations" }, { value: "quantum", label: "Quantum" },
    ...(execution.benchmark ? [{ value: "benchmark" as Tab, label: "Benchmark" }] : []), { value: "raw", label: "Raw" },
  ];
  return (
    <div className="space-y-4">
      {execution.cached && <Notice tone="warn">{execution.cached.label}</Notice>}
      {execution.result_source === "test" && (
        <Notice tone="warn">Model-generated sections in this result came from the deterministic test provider, not from a real AI model.</Notice>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Tabs tabs={tabs} value={tab} onChange={setTab} />
        {done && (
          <div className="flex gap-2 text-xs">
            <a className="rounded border border-line-strong px-2 py-1 text-dim hover:text-text" href={`/api/executions/${execution.id}/report.md`}>Export .md</a>
            <a className="rounded border border-line-strong px-2 py-1 text-dim hover:text-text" href={`/api/executions/${execution.id}/report.json`}>Export .json</a>
          </div>
        )}
      </div>
      {!done && tab !== "raw" && execution.status !== "failed" && <p className="text-sm text-muted">Execution {execution.status}. Sections fill in as steps complete.</p>}

      {tab === "matrix" && matrixResult && <MatrixView m={matrixResult} />}
      {tab === "proof" && proofResult && <ProofView proof={proofResult} />}
      {tab === "summary" && (
        <div className="space-y-5">
          <SectionBlock title="Executive summary" s={sec(execution, "executive_summary")} />
          <SectionBlock title="Confidence" s={sec(execution, "confidence")} />
          <SectionBlock title="Assumptions" s={sec(execution, "assumptions")} />
          <SectionBlock title="Limitations" s={sec(execution, "limitations")} />
        </div>
      )}
      {tab === "solution" && (
        <div className="space-y-5">
          {detail ? (
            <SectionBlock title="Detailed solution" s={detail}>
              {typeof detail.content === "object" && detail.content && "answer" in (detail.content as object) ? (
                <div className="space-y-2">
                  <div className="flex flex-wrap gap-2 text-xs text-muted">
                    <span>Source: {String((detail.content as Record<string, unknown>).source)}</span>
                    <ExecBadge cls={String((detail.content as Record<string, unknown>).execution_class)} />
                  </div>
                  <Answer answer={(detail.content as Record<string, unknown>).answer as Record<string, unknown>} />
                </div>
              ) : <Content value={detail.content} />}
            </SectionBlock>
          ) : <p className="text-sm text-muted">No solution yet.</p>}
          <SectionBlock title="AI answer, independently verified" s={sec(execution, "ai_answer_verification")} />
          <SectionBlock title="Interpretation" s={sec(execution, "interpretation")} />
        </div>
      )}
      {tab === "method" && <SectionBlock title="Methodology" s={sec(execution, "methodology")} />}
      {tab === "reasoning" && (
        <div className="space-y-5">
          {intellect ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <ContentBadge cls={intellect.content_class} />
                <Badge>{String((intellect.content.summary as Record<string, unknown>)?.assessment_mode ?? "")}</Badge>
                {can("intellect.read") && Boolean(intellect.content.run_id) && (
                  <Link className="text-xs text-green hover:underline" href={`/admin/intellect/runs/${String(intellect.content.run_id)}`}>Open full 13-stage trace →</Link>
                )}
              </div>
              {intellect.content.error ? <Notice tone="warn">{String(intellect.content.error)}</Notice> : <Prose text={String(intellect.content.final_output ?? "")} />}
              <KV items={[
                ["Rules applied", ((intellect.content.summary as Record<string, unknown>)?.rules_applied as string[] | undefined)?.join(", ") || "none"],
                ["Delivery preset", JSON.stringify((intellect.content.summary as Record<string, unknown>)?.preset ?? null)],
                ["Guardrail audit", (() => {
                  const a = (intellect.content.summary as Record<string, unknown>)?.guardrail_audit as Record<string, unknown> | undefined;
                  if (!a?.performed) return "not performed";
                  const b = (a.breaches as { rule: string }[]) ?? [];
                  return b.length ? <span className="text-amber">flagged: {b.map((x) => x.rule).join(", ")}</span> : "no breaches flagged";
                })()],
              ]} />
            </>
          ) : <p className="text-sm text-muted">The Intellect framework did not run in this mode.</p>}
          {ai && (
            <div className="space-y-2 border-t border-line pt-4">
              <div className="flex items-center gap-2"><h3 className="x-label !text-dim">AI answer</h3><ContentBadge cls={ai.content_class} /></div>
              {ai.content.error ? <Notice tone="warn">{String(ai.content.error)}</Notice> : <Prose text={String(ai.content.answer ?? "")} />}
            </div>
          )}
        </div>
      )}
      {tab === "calc" && (
        <div className="grid gap-3 lg:grid-cols-2">
          {classical && <SolverCard title="Classical" c={classical.content} execClass={classical.execution_class} />}
          {quantum && <SolverCard title="Quantum" c={quantum.content} execClass={quantum.execution_class} />}
          {!classical && !quantum && <p className="text-sm text-muted">No computed results in this execution.</p>}
        </div>
      )}
      {tab === "quantum" && (() => {
        const qd = execution.plan?.quantum_decision;
        if (!qd) return <p className="text-sm text-muted">No quantum evaluation.</p>;
        return (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="cyan">{qd.decision.replace(/_/g, " ")}</Badge>
              {qd.route && <ExecBadge cls={qd.route.execution_class} />}
            </div>
            <Prose text={qd.explanation} />
            <Table head={["Factor", "Evaluation"]}>
              {Object.entries(qd.factors).map(([k, v]) => (
                <tr key={k}><Td className="text-muted">{k.replace(/_/g, " ")}</Td><Td>{v === null ? <span className="text-muted">not evaluated</span> : String(v)}</Td></tr>
              ))}
            </Table>
            <SectionBlock title="Classical comparison" s={sec(execution, "classical_comparison")} />
          </div>
        );
      })()}
      {tab === "benchmark" && execution.benchmark && <BenchmarkView b={execution.benchmark} />}
      {tab === "raw" && <JsonView value={{ final_output: execution.final_output, results: execution.results, plan: execution.plan }} maxHeight={520} />}
    </div>
  );
}
