"use client";

import { motion } from "framer-motion";
import { Badge, cx } from "@/components/ui";
import type { ProofResult, ProofVerdict } from "@/lib/types";

function Gauge({ label, score, total, color, lead }: { label: string; score: number; total: number; color: string; lead: boolean }) {
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

export function ProofView({ proof }: { proof: ProofResult }) {
  const { score, total } = proof;
  const intellectLeads = score.ai_intellect > score.ai_only;
  const aiLeads = score.ai_only > score.ai_intellect;
  return (
    <div className="space-y-5">
      <div className={cx("rounded-[3px] border px-4 py-3 font-mono text-[13px]",
        intellectLeads ? "border-green/40 bg-green/[0.06] text-green" : aiLeads ? "border-amber/40 bg-amber/10 text-amber" : "border-line text-dim")}>
        <span className="mr-2 text-[10.5px] tracking-[0.2em] opacity-70">VERDICT //</span>{proof.verdict}
      </div>

      <div className="grid gap-4 md:grid-cols-[1fr_auto_1fr] md:items-center">
        <Gauge label="AI ONLY" score={score.ai_only} total={total} color="#45d9f5" lead={aiLeads} />
        <div className="text-center font-display text-2xl tracking-[0.3em] text-muted">VS</div>
        <Gauge label="AI + INTELLECT" score={score.ai_intellect} total={total} color="#3cf59a" lead={intellectLeads} />
      </div>

      {proof.rules_behind_wins.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="x-label">Rules behind the difference</span>
          {proof.rules_behind_wins.map((r) => <Badge key={r} tone="green">{r}</Badge>)}
        </div>
      )}

      <div className="overflow-x-auto rounded-[3px] border border-line">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="bg-white/[0.02]">
            <tr>{["Criterion (fixed before the run)", "AI Only", "AI + Intellect", "Rules"].map((h) => <th key={h} className="x-label px-3 py-2 font-normal">{h}</th>)}</tr>
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

      <div className="grid gap-3 lg:grid-cols-2">
        {([["AI ONLY", proof.answers.ai_only, "border-cyan/30", "text-cyan"], ["AI + INTELLECT", proof.answers.ai_intellect, "border-green/30", "text-green"]] as const).map(([l, t, b, tc]) => (
          <div key={l} className={cx("rounded-[3px] border bg-black/40 p-3", b)}>
            <div className={cx("mb-2 font-mono text-[10.5px] tracking-[0.2em]", tc)}>{l} {"// ANSWER"}</div>
            <div className="max-h-80 overflow-y-auto whitespace-pre-wrap text-[13.5px] leading-relaxed text-text">{t}</div>
          </div>
        ))}
      </div>

      <div className="space-y-1 text-[11.5px] text-muted">
        <div>Judge: {proof.judge.model || "—"}{proof.judge.test_provider && " (TEST PROVIDER — not a real model)"} · blind order: response 1 = {proof.judge.order.response_1}, response 2 = {proof.judge.order.response_2} · rubric: {proof.rubric_source}</div>
        <div>{proof.method_note}</div>
        {proof.judge.error && <div className="text-amber">Judge error: {proof.judge.error}</div>}
      </div>
    </div>
  );
}
