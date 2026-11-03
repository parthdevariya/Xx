"use client";

import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import { Badge, ContentBadge, ExecBadge, cx, fmtNum } from "@/components/ui";
import type { MatrixResult, MatrixRow } from "@/lib/types";

const ENG = [
  { key: "ai", short: "AI", color: "#45d9f5" },
  { key: "intellect", short: "IN", color: "#3cf59a" },
  { key: "classical", short: "CL", color: "#c9d3ce" },
  { key: "quantum", short: "QU", color: "#7c8cff" },
];

function Pips({ engines, size = 22 }: { engines: string[]; size?: number }) {
  return (
    <div className="flex gap-1" aria-label={`Engines: ${engines.join(", ")}`}>
      {ENG.map((e) => {
        const on = engines.includes(e.key);
        return (
          <span key={e.key} className="flex items-center justify-center rounded-[2px] border font-mono text-[9px] font-semibold"
            style={{ width: size, height: size, borderColor: on ? e.color : "rgba(140,255,200,0.12)", color: on ? "#03110a" : "rgba(140,255,200,0.25)",
              background: on ? e.color : "transparent", boxShadow: on ? `0 0 10px -2px ${e.color}` : undefined }}>{e.short}</span>
        );
      })}
    </div>
  );
}

function scoreText(r: MatrixRow) {
  if (!r.rubric) return null;
  return r.rubric.complete ? `${r.rubric.score}/${r.rubric.total}` : `${r.rubric.score}/${r.rubric.total}*`;
}

function bestObjective(r: MatrixRow, sense: "min" | "max" | null) {
  const vals = Object.values(r.computed).filter((c) => c.feasible && c.objective_value !== null).map((c) => c.objective_value as number);
  if (!vals.length) return null;
  return sense === "max" ? Math.max(...vals) : Math.min(...vals);
}

export function MatrixView({ m }: { m: MatrixResult }) {
  const rows = m.combinations;
  const [sel, setSel] = useState<string>(() => rows.find((r) => r.key === "ai+intellect" && r.applicable)?.key ?? rows.find((r) => r.applicable)?.key ?? rows[0].key);
  const selected = rows.find((r) => r.key === sel)!;
  const judged = rows.filter((r) => r.rubric);
  const maxScore = Math.max(1, ...judged.map((r) => r.rubric!.total));
  const computedRows = rows.filter((r) => r.applicable && Object.keys(r.computed).length && !r.engines.includes("ai"));
  const objVals = computedRows.map((r) => bestObjective(r, m.sense)).filter((v): v is number => v !== null);
  const objMax = Math.max(1e-9, ...objVals.map(Math.abs));
  const topScore = Math.max(-1, ...judged.filter((r) => r.rubric!.complete).map((r) => r.rubric!.score));
  const criteriaById = useMemo(() => Object.fromEntries(m.rubric.map((c) => [c.id, c])), [m.rubric]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-green/15 pb-2 font-mono text-[11px] tracking-[0.18em] text-green/80">
        <span>ENGINE COMBINATION MATRIX {"//"} {rows.length} CONFIGURATIONS · {rows.filter((r) => r.applicable).length} APPLICABLE</span>
        <span className="text-muted">JUDGE: {m.judge.model || "—"}{m.judge.test_provider ? " (TEST PROVIDER)" : ""} · BLIND</span>
      </div>

      {m.insights.length > 0 && (
        <div className="x-scanlines rounded-[3px] border border-green/25 bg-black/50 p-3 font-mono text-[12.5px]">
          {m.insights.map((t, i) => (
            <motion.div key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.12 }}
              className="text-[#b8ffd9]"><span className="text-green/50">&gt;&gt; </span>{t}</motion.div>
          ))}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-[3px] border border-line p-3">
          <div className="x-label mb-3">Rubric score — same blind judge, same criteria</div>
          {judged.length === 0 ? <p className="text-sm text-muted">No AI answers were produced (AI not configured).</p> : (
            <div className="space-y-2">
              {[...judged].sort((a, b) => b.rubric!.score - a.rubric!.score).map((r, i) => {
                const hasI = r.engines.includes("intellect");
                const color = hasI ? "#3cf59a" : "#45d9f5";
                return (
                  <button key={r.key} onClick={() => setSel(r.key)} className="grid w-full grid-cols-[150px_1fr_44px] items-center gap-2 text-left text-xs">
                    <span className={cx("truncate", sel === r.key ? "text-text" : "text-dim")}>{r.label}</span>
                    <div className="relative h-4 overflow-hidden rounded-[2px] bg-white/[0.04]">
                      <motion.div className="absolute inset-y-0 left-0 rounded-[2px]" style={{ background: color, boxShadow: `0 0 12px ${color}` }}
                        initial={{ width: 0 }} animate={{ width: `${(r.rubric!.score / maxScore) * 100}%` }} transition={{ duration: 1, delay: i * 0.08 }} />
                      {r.rubric!.complete && r.rubric!.score === topScore && <span className="absolute right-1 top-0 font-mono text-[9px] leading-4 text-black">★</span>}
                    </div>
                    <span className="text-right font-mono" style={{ color }}>{scoreText(r)}</span>
                  </button>
                );
              })}
              <div className="flex gap-4 pt-1 text-[11px] text-muted">
                <span><span className="mr-1 inline-block h-2 w-2 bg-green" />with Intellect</span>
                <span><span className="mr-1 inline-block h-2 w-2 bg-cyan" />without Intellect</span>
                {judged.some((r) => !r.rubric!.complete) && <span>* some criteria not judged</span>}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-[3px] border border-line p-3">
          <div className="x-label mb-3">Computed objective — classical vs quantum (same true objective{m.sense ? `, ${m.sense === "min" ? "lower" : "higher"} is better` : ""})</div>
          {computedRows.length === 0 ? <p className="text-sm text-muted">No solver formulation for this problem: classical and quantum have nothing to compute, so their combinations are marked not applicable.</p> : (
            <div className="space-y-2">
              {computedRows.map((r, i) => {
                const v = bestObjective(r, m.sense);
                return (
                  <button key={r.key} onClick={() => setSel(r.key)} className="grid w-full grid-cols-[150px_1fr_60px] items-center gap-2 text-left text-xs">
                    <span className="truncate text-dim">{r.label}</span>
                    <div className="h-4 rounded-[2px] bg-white/[0.04]">
                      <motion.div className="h-4 rounded-[2px] bg-blue/70" initial={{ width: 0 }}
                        animate={{ width: v === null ? 0 : `${(Math.abs(v) / objMax) * 100}%` }} transition={{ duration: 1, delay: i * 0.1 }} />
                    </div>
                    <span className="text-right font-mono text-blue">{fmtNum(v)}</span>
                  </button>
                );
              })}
              <div className="flex flex-wrap gap-1.5 pt-1">
                {Object.entries(Object.assign({}, ...computedRows.map((r) => r.computed)) as MatrixRow["computed"]).map(([k, c]) => (
                  <span key={k} className="flex items-center gap-1 text-[11px] text-muted">{k}: <ExecBadge cls={c.execution_class} />{c.proven_optimal && <Badge tone="green">proven</Badge>}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {judged.length > 0 && (
        <div className="overflow-x-auto rounded-[3px] border border-line">
          <table className="w-full min-w-[720px] text-xs">
            <thead>
              <tr className="bg-white/[0.02]">
                <th className="x-label px-3 py-2 text-left font-normal">Criterion</th>
                {judged.map((r) => (
                  <th key={r.key} className="px-1.5 py-2 font-normal">
                    <button onClick={() => setSel(r.key)} className="mx-auto flex flex-col items-center gap-1" title={r.label}><Pips engines={r.engines} size={14} /></button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {m.rubric.map((c) => (
                <tr key={c.id}>
                  <td className="max-w-[320px] px-3 py-2 text-dim">{c.criterion}</td>
                  {judged.map((r) => {
                    const v = r.rubric!.criteria.find((x) => x.id === c.id);
                    return (
                      <td key={r.key} className="px-1.5 py-2 text-center">
                        <span title={v?.evidence || v?.reason} className={cx("inline-block h-5 w-5 rounded-[2px] font-mono text-[11px] leading-5",
                          v?.pass ? "bg-green/80 text-black shadow-[0_0_8px_rgba(60,245,154,0.7)]" : v?.pass === false ? "bg-red/25 text-red" : "bg-white/5 text-muted")}>
                          {v?.pass ? "✓" : v?.pass === false ? "✗" : "·"}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
        {rows.map((r, i) => (
          <motion.button key={r.key} onClick={() => setSel(r.key)} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.04 }}
            className={cx("relative rounded-[3px] border p-3 text-left transition-all",
              sel === r.key ? "border-green/70 bg-green/[0.07] shadow-[0_0_22px_-8px_rgba(60,245,154,0.9)]" : r.applicable ? "border-line hover:border-green/35" : "border-line/50 opacity-45")}>
            <div className="flex items-start justify-between gap-2">
              <Pips engines={r.engines} />
              {r.applicable ? (scoreText(r) ? <span className="font-mono text-sm text-green">{scoreText(r)}</span>
                : <span className="font-mono text-sm text-blue">{fmtNum(bestObjective(r, m.sense))}</span>)
                : <span className="font-mono text-[10px] tracking-wider text-muted">N/A</span>}
            </div>
            <div className="mt-2 font-display text-[13.5px] text-text">{r.label}</div>
            <div className="mt-0.5 line-clamp-2 text-[11.5px] text-muted">{r.applicable ? (r.rules_applied.length ? `${r.rules_applied.length} rules applied` : Object.keys(r.computed).length && !r.answer ? "computed result" : `${r.latency_s}s`) : r.reason}</div>
          </motion.button>
        ))}
      </div>

      <motion.div key={selected.key} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="rounded-[3px] border border-green/25 bg-black/40 p-4">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <Pips engines={selected.engines} size={24} />
          <span className="font-display text-lg text-text">{selected.label}</span>
          {selected.applicable && selected.answer && <ContentBadge cls={selected.content_class} />}
          {selected.rubric && <Badge tone="green">rubric {scoreText(selected)}</Badge>}
        </div>
        {!selected.applicable ? <p className="text-sm text-amber">Not applicable — {selected.reason}</p> : (
          <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
            <div className="space-y-3">
              {selected.answer ? (
                <div className="max-h-96 overflow-y-auto whitespace-pre-wrap text-[13.5px] leading-relaxed text-text">{selected.answer}</div>
              ) : <p className="text-sm text-muted">Pure computation: no written answer. See the computed result.</p>}
              {selected.rules_applied.length > 0 && (
                <div className="flex flex-wrap gap-1">{selected.rules_applied.map((r) => <span key={r} className="rounded-sm border border-green/40 px-1 font-mono text-[10.5px] text-green">{r}</span>)}</div>
              )}
            </div>
            <div className="space-y-3">
              {Object.entries(selected.computed).map(([k, c]) => (
                <div key={k} className="rounded-[3px] border border-line p-2.5 text-xs">
                  <div className="mb-1 flex items-center gap-2"><span className="font-mono uppercase text-dim">{k}</span><ExecBadge cls={c.execution_class} /></div>
                  <div className="grid grid-cols-2 gap-y-0.5 text-muted">
                    <span>Objective</span><span className="font-mono text-text">{fmtNum(c.objective_value)}</span>
                    <span>Feasible</span><span className="text-text">{c.feasible ? "yes" : "no"}</span>
                    <span>Optimality</span><span className="text-text">{c.proven_optimal ? "proven" : "not proven"}</span>
                    <span>Algorithm</span><span className="font-mono text-text">{c.algorithm}</span>
                    {c.qubits > 0 && <><span>Qubits</span><span className="font-mono text-text">{c.qubits}</span></>}
                    <span>Wall time</span><span className="font-mono text-text">{c.wall_time_s.toFixed(3)} s</span>
                  </div>
                </div>
              ))}
              {selected.rubric && (
                <div className="space-y-1.5">
                  {selected.rubric.criteria.map((v) => (
                    <div key={v.id} className="text-xs">
                      <span className={cx("mr-1.5 font-mono", v.pass ? "text-green" : v.pass === false ? "text-red" : "text-muted")}>{v.pass ? "✓" : v.pass === false ? "✗" : "·"}</span>
                      <span className="text-dim">{criteriaById[v.id]?.criterion ?? v.id}</span>
                      {v.evidence && <div className="ml-4 italic text-muted">“{v.evidence}”</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </motion.div>
      <p className="text-[11.5px] text-muted">{m.method_note} Rubric: {m.rubric_source}.{m.judge.error ? ` Judge: ${m.judge.error}` : ""}</p>
    </div>
  );
}
