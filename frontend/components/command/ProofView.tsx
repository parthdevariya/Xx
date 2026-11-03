"use client";

import { motion } from "framer-motion";
import { Badge, cx } from "@/components/ui";
import type { ArmMetrics, ProofResult, ProofVerdict } from "@/lib/types";

const CYAN = "#45d9f5";
const GREEN = "#3cf59a";
const WITHOUT = "WITHOUT INTELLECT";
const WITH = "WITH INTELLECT";

function Gauge({ label, sub, score, total, color, lead }: {
  label: string; sub: string; score: number; total: number; color: string; lead: boolean;
}) {
  const r = 46;
  const c = 2 * Math.PI * r;
  const frac = total ? score / total : 0;
  return (
    <div className={cx("relative flex flex-col items-center rounded-[3px] border p-4", lead ? "border-green/50 bg-green/[0.05]" : "border-line")}>
      <svg viewBox="0 0 120 120" className="h-36 w-36" role="img" aria-label={`${label}: ${score} of ${total} criteria met`}>
        <circle cx="60" cy="60" r={r} fill="none" stroke="rgba(140,255,200,0.08)" strokeWidth="8" />
        {Array.from({ length: total }).map((_, i) => {
          const a = (i / total) * Math.PI * 2 - Math.PI / 2;
          return <line key={i} x1={60 + 54 * Math.cos(a)} y1={60 + 54 * Math.sin(a)} x2={60 + 58 * Math.cos(a)} y2={60 + 58 * Math.sin(a)}
            stroke={i < score ? color : "rgba(140,255,200,0.15)"} strokeWidth="2" />;
        })}
        <motion.circle cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
          transform="rotate(-90 60 60)" strokeDasharray={c} initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - frac) }} transition={{ duration: 1.4, ease: "easeOut" }}
          style={{ filter: `drop-shadow(0 0 6px ${color})` }} />
        <text x="60" y="58" textAnchor="middle" className="font-display" fontSize="28" fill="#e9fff3">{score}</text>
        <text x="60" y="76" textAnchor="middle" fontSize="10" fill="#7d8a84" fontFamily="monospace">OF {total}</text>
      </svg>
      <div className="font-mono text-[11px] tracking-[0.18em]" style={{ color }}>{label}</div>
      <div className="mt-0.5 text-[11px] text-muted">{sub}</div>
      {lead && <Badge tone="green" className="mt-1.5">Leads</Badge>}
    </div>
  );
}

function Cell({ v }: { v: ProofVerdict }) {
  const state = v.pass === null ? "na" : v.pass ? "pass" : "fail";
  return (
    <div className="min-w-0">
      <div className={cx("font-mono text-xs font-semibold", state === "pass" ? "text-green" : state === "fail" ? "text-red" : "text-muted")}>
        {state === "pass" ? "✔ PASS" : state === "fail" ? "✖ FAIL" : "— NOT JUDGED"}
      </div>
      {v.evidence && <blockquote className="mt-1 border-l border-line-strong pl-2 text-[12px] italic text-dim">“{v.evidence}”</blockquote>}
      {v.reason && v.reason !== "deterministic check" && <div className="mt-1 text-[11.5px] text-muted">{v.reason}</div>}
    </div>
  );
}

type Row = { label: string; a: string; b: string; delta?: string; good?: boolean; note?: string };

function metricRows(proof: ProofResult, m: { ai_only: ArmMetrics; ai_intellect: ArmMetrics } | undefined): Row[] {
  const { score, total } = proof;
  const d = score.ai_intellect - score.ai_only;
  const rows: Row[] = [{ label: "Criteria met", a: `${score.ai_only} / ${total}`, b: `${score.ai_intellect} / ${total}`,
    delta: d ? `${d > 0 ? "+" : ""}${d}` : "same", good: d ? d > 0 : undefined }];
  if (!m) return rows;
  const num = (label: string, a?: number, b?: number, fmt = (x: number) => String(x), note?: string, lowerIsBetter = false) => {
    if (a === undefined || b === undefined) return;
    const diff = b - a;
    rows.push({ label, a: fmt(a), b: fmt(b), note,
      delta: diff === 0 ? "same" : `${diff > 0 ? "+" : "−"}${fmt(Math.abs(diff))}`,
      good: lowerIsBetter && diff !== 0 ? diff < 0 : undefined });
  };
  num("Questions asked back", m.ai_only.questions, m.ai_intellect.questions, String, "fewer is usually better", true);
  num("Answer length (words)", m.ai_only.words, m.ai_intellect.words);
  num("Reasoning stages", m.ai_only.stages, m.ai_intellect.stages);
  num("Rules checked", m.ai_only.rules_checked, m.ai_intellect.rules_checked);
  num("Rules applied", m.ai_only.rules_applied, m.ai_intellect.rules_applied);
  if (m.ai_intellect.guardrail_audit) rows.push({ label: "Guardrail audit", a: m.ai_only.guardrail_audit ?? "none", b: m.ai_intellect.guardrail_audit });
  num("AI calls", m.ai_only.ai_calls, m.ai_intellect.ai_calls);
  num("Model time", m.ai_only.model_time_s, m.ai_intellect.model_time_s, (x) => `${x.toFixed(1)} s`, "the price of thinking it through");
  num("Cost", m.ai_only.cost_usd, m.ai_intellect.cost_usd, (x) => `$${x.toFixed(4)}`);
  return rows;
}

export function ProofView({ proof }: { proof: ProofResult }) {
  const { score, total } = proof;
  const intellectLeads = score.ai_intellect > score.ai_only;
  const aiLeads = score.ai_only > score.ai_intellect;
  const diff = proof.difference;
  const winRows = proof.criteria.filter((c) => c.ai_intellect.pass && c.ai_only.pass === false);
  const lossRows = proof.criteria.filter((c) => c.ai_only.pass && c.ai_intellect.pass === false);
  const rows = metricRows(proof, diff?.metrics);
  return (
    <div className="space-y-6">
      {/* 1 — headline */}
      <div className={cx("rounded-[3px] border px-4 py-3 font-mono text-[13px]",
        intellectLeads ? "border-green/40 bg-green/[0.06] text-green" : aiLeads ? "border-amber/40 bg-amber/10 text-amber" : "border-line text-dim")}>
        <span className="mr-2 text-[10.5px] tracking-[0.2em] opacity-70">VERDICT //</span>{proof.verdict}
      </div>

      <div className="grid gap-4 md:grid-cols-[1fr_auto_1fr] md:items-center">
        <Gauge label={WITHOUT} sub="the model answering alone" score={score.ai_only} total={total} color={CYAN} lead={aiLeads} />
        <div className="flex flex-col items-center gap-1">
          <div className="font-display text-2xl tracking-[0.3em] text-muted">VS</div>
          {score.ai_intellect !== score.ai_only && (
            <motion.div initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 1.2 }}
              className={cx("rounded-sm border px-2 py-0.5 font-mono text-xs", intellectLeads ? "border-green/50 text-green" : "border-amber/50 text-amber")}>
              {intellectLeads ? "+" : "−"}{Math.abs(score.ai_intellect - score.ai_only)} criteria
            </motion.div>
          )}
        </div>
        <Gauge label={WITH} sub="same model through X Layers" score={score.ai_intellect} total={total} color={GREEN} lead={intellectLeads} />
      </div>

      {/* 2 — what's the difference */}
      <section className="space-y-3">
        <h3 className="x-label !text-dim">What&apos;s the difference</h3>
        {diff?.bottom_line && (
          <div className="rounded-[3px] border border-green/30 bg-green/[0.04] px-4 py-3 text-[14px] leading-relaxed text-text">
            <span className="mr-2 font-mono text-[10.5px] tracking-[0.2em] text-green">BOTTOM LINE //</span>{diff.bottom_line}
          </div>
        )}
        {(winRows.length > 0 || lossRows.length > 0) && (
          <div className="grid gap-2 md:grid-cols-2">
            {winRows.length > 0 && (
              <div className="rounded-[3px] border border-green/30 p-3">
                <div className="mb-1.5 font-mono text-[10.5px] tracking-[0.2em] text-green">ONLY WITH INTELLECT ✔</div>
                <ul className="space-y-1 text-[13px] text-text">
                  {winRows.map((c) => <li key={c.id}>• {c.criterion}{c.rules_applied_by_intellect.length > 0 &&
                    <span className="ml-1 font-mono text-[11px] text-green">[{c.rules_applied_by_intellect.join(", ")}]</span>}</li>)}
                </ul>
              </div>
            )}
            {lossRows.length > 0 && (
              <div className="rounded-[3px] border border-amber/30 p-3">
                <div className="mb-1.5 font-mono text-[10.5px] tracking-[0.2em] text-amber">ONLY WITHOUT INTELLECT</div>
                <ul className="space-y-1 text-[13px] text-text">{lossRows.map((c) => <li key={c.id}>• {c.criterion}</li>)}</ul>
              </div>
            )}
          </div>
        )}
        {diff && diff.differences.length > 0 && (
          <div className="space-y-2">
            {diff.differences.map((d, i) => (
              <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 * i }}
                className="rounded-[3px] border border-line bg-black/30">
                <div className="border-b border-line px-3 py-1.5 font-mono text-[11px] tracking-[0.16em] text-text">{d.aspect.toUpperCase()}</div>
                <div className="grid md:grid-cols-2">
                  <div className="border-line p-3 md:border-r">
                    <div className="mb-1 font-mono text-[10px] tracking-[0.2em] text-cyan">{WITHOUT}</div>
                    <div className="text-[13px] text-dim">{d.ai_only}</div>
                  </div>
                  <div className="p-3">
                    <div className="mb-1 font-mono text-[10px] tracking-[0.2em] text-green">{WITH}</div>
                    <div className="text-[13px] text-text">{d.ai_intellect}</div>
                  </div>
                </div>
                {d.why_it_matters && <div className="border-t border-line px-3 py-2 text-[12px] text-muted"><span className="text-green">Why it matters: </span>{d.why_it_matters}</div>}
              </motion.div>
            ))}
          </div>
        )}
        {proof.rules_behind_wins.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="x-label">Rules behind the difference</span>
            {proof.rules_behind_wins.map((r) => <Badge key={r} tone="green">{r}</Badge>)}
          </div>
        )}
      </section>

      {/* 3 — side by side numbers */}
      <section className="space-y-2">
        <h3 className="x-label !text-dim">Side by side</h3>
        <div className="overflow-x-auto rounded-[3px] border border-line">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="bg-white/[0.02]">
              <tr>
                <th className="x-label px-3 py-2 font-normal">Measure</th>
                <th className="px-3 py-2 font-mono text-[10.5px] font-normal tracking-[0.18em] text-cyan">{WITHOUT}</th>
                <th className="px-3 py-2 font-mono text-[10.5px] font-normal tracking-[0.18em] text-green">{WITH}</th>
                <th className="x-label px-3 py-2 font-normal">Difference</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((r) => (
                <tr key={r.label}>
                  <td className="px-3 py-2 text-dim">{r.label}{r.note && <div className="text-[11px] text-muted">{r.note}</div>}</td>
                  <td className="px-3 py-2 font-mono text-[13px]">{r.a}</td>
                  <td className="px-3 py-2 font-mono text-[13px] text-text">{r.b}</td>
                  <td className={cx("px-3 py-2 font-mono text-[13px]", r.good === true ? "text-green" : r.good === false ? "text-amber" : "text-muted")}>{r.delta ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* 4 — the two answers */}
      <section className="space-y-2">
        <h3 className="x-label !text-dim">The two answers</h3>
        <div className="grid gap-3 lg:grid-cols-2">
          {([[WITHOUT, proof.answers.ai_only, "border-cyan/30", "text-cyan"], [WITH, proof.answers.ai_intellect, "border-green/30", "text-green"]] as const).map(([l, t, b, tc]) => (
            <div key={l} className={cx("rounded-[3px] border bg-black/40 p-3", b)}>
              <div className={cx("mb-2 font-mono text-[10.5px] tracking-[0.2em]", tc)}>{l} {"// ANSWER"}</div>
              <div className="max-h-96 overflow-y-auto whitespace-pre-wrap text-[13.5px] leading-relaxed text-text">{t}</div>
            </div>
          ))}
        </div>
      </section>

      {/* 5 — criterion by criterion evidence */}
      <section className="space-y-2">
        <h3 className="x-label !text-dim">Criterion by criterion (rubric fixed before the run)</h3>
        <div className="overflow-x-auto rounded-[3px] border border-line">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="bg-white/[0.02]">
              <tr>{["Criterion", "Without Intellect", "With Intellect", "Rules"].map((h) => <th key={h} className="x-label px-3 py-2 font-normal">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line">
              {proof.criteria.map((c) => {
                const win = c.ai_intellect.pass && c.ai_only.pass === false;
                return (
                  <tr key={c.id} className={cx(win && "bg-green/[0.035]")}>
                    <td className="w-[34%] px-3 py-2.5 align-top">
                      <div className="text-text">{c.criterion}</div>
                      {c.why && <div className="mt-1 text-[11.5px] text-muted">Trap: {c.why}</div>}
                      <Badge className="mt-1.5" tone={c.method === "deterministic" ? "green" : "cyan"}>{c.method === "deterministic" ? "Computed check" : "Blind judge"}</Badge>
                    </td>
                    <td className="w-[26%] px-3 py-2.5 align-top"><Cell v={c.ai_only} /></td>
                    <td className="w-[26%] px-3 py-2.5 align-top"><Cell v={c.ai_intellect} /></td>
                    <td className="px-3 py-2.5 align-top">
                      <div className="flex flex-wrap gap-1">
                        {c.related_rules.map((r) => (
                          <span key={r} title={c.rules_applied_by_intellect.includes(r) ? "applied in this run" : "linked; not applied in this run"}
                            className={cx("rounded-sm border px-1 font-mono text-[10.5px]",
                              c.rules_applied_by_intellect.includes(r) ? "border-green/50 text-green" : "border-line-strong text-muted")}>{r}</span>
                        ))}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="space-y-1 text-[11.5px] text-muted">
        <div>Judge: {proof.judge.model || "—"}{proof.judge.test_provider && " (TEST PROVIDER — not a real model)"} · blind order: response 1 = {proof.judge.order.response_1}, response 2 = {proof.judge.order.response_2} · rubric: {proof.rubric_source}</div>
        <div>{proof.method_note} The &quot;what&apos;s the difference&quot; notes are written by the same blind judge; counts, time and cost are measured.</div>
        {proof.judge.error && <div className="text-amber">Judge error: {proof.judge.error}</div>}
      </div>
    </div>
  );
}
