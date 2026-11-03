"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { GlitchText } from "@/components/fx/GlitchText";
import { Badge, ErrorNote, ExecBadge, Spinner, cx, fmtNum } from "@/components/ui";
import { api } from "@/lib/api";
import type { ExecEvent, Execution, ExecutionTrace } from "@/lib/types";

type Engine = "ai" | "intellect" | "quantum";
const META: Record<Engine, { title: string; color: string; tagline: string }> = {
  ai: { title: "AI ENGINE", color: "#45d9f5", tagline: "Model routing · calls · tokens · fallbacks" },
  intellect: { title: "INTELLECT ENGINE", color: "#3cf59a", tagline: "X Layers · 13 ordered stages · guardrails · conflicts" },
  quantum: { title: "QUANTUM ENGINE", color: "#7c8cff", tagline: "Selection · circuit · shots · measurement" },
};
const STATE_STYLE: Record<string, string> = {
  applied: "border-green/60 bg-green/15 text-green shadow-[0_0_8px_rgba(60,245,154,0.45)]",
  not_applicable: "border-line-strong text-muted",
  disabled: "border-line text-muted line-through opacity-60",
  not_assessed: "border-amber/40 text-amber",
};

function Stat({ label, value, color }: { label: string; value: React.ReactNode; color: string }) {
  return (
    <div className="rounded-[3px] border border-line bg-black/40 px-3 py-2">
      <div className="font-mono text-[9.5px] tracking-[0.2em] text-muted">{label}</div>
      <div className="font-mono text-lg" style={{ color }}>{value}</div>
    </div>
  );
}

function EngineEvents({ events, engine, color }: { events: ExecEvent[]; engine: Engine; color: string }) {
  const mine = events.filter((e) => e.engine === engine);
  if (!mine.length) return null;
  return (
    <div className="x-scanlines max-h-48 overflow-y-auto rounded-[3px] border border-line bg-black/60 p-2 font-mono text-[11.5px]">
      {mine.map((e) => <div key={e.seq} className="text-dim"><span style={{ color }}>▸</span> {e.message}</div>)}
    </div>
  );
}

// ------------------------------------------------------------------ AI

function AIView({ trace, execution, color }: { trace: ExecutionTrace; execution: Execution | null; color: string }) {
  const calls = trace.ai_calls;
  if (!calls.length) return <p className="text-sm text-muted">No AI calls in this execution{execution ? "" : " (none selected)"}. Configure a provider in Admin → AI Management to activate the AI engine.</p>;
  const tokIn = calls.reduce((s, c) => s + c.input_tokens, 0), tokOut = calls.reduce((s, c) => s + c.output_tokens, 0);
  const maxLat = Math.max(1, ...calls.map((c) => c.latency_ms));
  const models = Array.from(new Set(calls.filter((c) => c.status !== "error").map((c) => c.model)));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Stat label="CALLS" value={calls.length} color={color} />
        <Stat label="TOKENS IN" value={tokIn.toLocaleString()} color={color} />
        <Stat label="TOKENS OUT" value={tokOut.toLocaleString()} color={color} />
        <Stat label="COST (EST.)" value={`$${calls.reduce((s, c) => s + c.cost_usd, 0).toFixed(4)}`} color={color} />
        <Stat label="FALLBACKS / ERRORS" value={`${calls.filter((c) => c.status === "fallback").length} / ${calls.filter((c) => c.status === "error").length}`} color={color} />
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-xs"><span className="x-label">Models</span>{models.map((m) => <Badge key={m} tone="cyan">{m}</Badge>)}
        {calls.some((c) => c.kind === "deterministic_test") && <Badge tone="red">Test provider</Badge>}</div>
      <div className="space-y-1">
        <div className="x-label mb-1">Neural link — every model call, in order</div>
        {calls.map((c, i) => (
          <motion.div key={i} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(i * 0.04, 1.2) }}
            className="grid grid-cols-[24px_minmax(0,1.3fr)_minmax(0,1fr)_70px] items-center gap-2 font-mono text-[11px]">
            <span className="text-muted">{String(i + 1).padStart(2, "0")}</span>
            <span className={cx("truncate", c.status === "error" ? "text-red" : "text-text")} title={c.error || c.purpose}>{c.purpose || "call"}</span>
            <div className="h-2.5 rounded-sm bg-white/5">
              <motion.div className="h-2.5 rounded-sm" style={{ background: c.status === "error" ? "#ff5f6d" : color, boxShadow: `0 0 8px ${color}` }}
                initial={{ width: 0 }} animate={{ width: `${(c.latency_ms / maxLat) * 100}%` }} transition={{ duration: 0.8, delay: Math.min(i * 0.04, 1.2) }} />
            </div>
            <span className="text-right text-muted">{(c.latency_ms / 1000).toFixed(2)}s</span>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Intellect

function IntellectView({ trace, color }: { trace: ExecutionTrace; color: string }) {
  const runs = trace.intellect_runs;
  const [i, setI] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  if (!runs.length) return <p className="text-sm text-muted">The Intellect pipeline did not run in this execution. It runs in AI + Intellect, Intellect vs AI, Hybrid, Benchmark and All Combinations modes (and needs an AI provider).</p>;
  const run = runs[Math.min(i, runs.length - 1)];
  const counts = run.stages.flatMap((s) => s.rule_states).reduce<Record<string, number>>((a, r) => ({ ...a, [r.state]: (a[r.state] ?? 0) + 1 }), {});
  const audit = run.summary?.guardrail_audit as { performed?: boolean; breaches?: { rule: string }[] } | undefined;
  return (
    <div className="space-y-4">
      {runs.length > 1 && (
        <div className="flex flex-wrap gap-1.5">{runs.map((r, k) => (
          <button key={r.id} onClick={() => { setI(k); setOpen(null); }}
            className={cx("rounded-[2px] border px-2 py-1 font-mono text-[11px]", k === i ? "border-green text-green" : "border-line text-muted hover:text-text")}>RUN {k + 1}</button>
        ))}</div>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Stat label="STAGES" value={run.stages.length} color={color} />
        <Stat label="RULES APPLIED" value={counts.applied ?? 0} color={color} />
        <Stat label="NOT APPLICABLE" value={counts.not_applicable ?? 0} color="#93a39b" />
        <Stat label="CONFLICTS" value={run.conflicts.length} color={run.conflicts.length ? "#ffb84d" : color} />
        <Stat label="GUARDRAIL AUDIT" value={!audit?.performed ? "—" : audit.breaches?.length ? `${audit.breaches.length} FLAG` : "CLEAN"} color={audit?.breaches?.length ? "#ff5f6d" : color} />
      </div>
      {run.assessment_mode !== "model" && <p className="text-xs text-amber">Assessment mode: {run.assessment_mode} — {run.assessment_mode === "test" ? "deterministic test provider, not a real model" : "rules could not be evaluated"}.</p>}
      <div className="relative pl-6">
        <div className="absolute bottom-2 left-[9px] top-2 w-px bg-gradient-to-b from-green/70 via-green/30 to-transparent" />
        {run.stages.map((s, k) => {
          const applied = s.rule_states.filter((r) => r.state === "applied");
          return (
            <motion.div key={s.position} initial={{ opacity: 0, x: -14 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: k * 0.09 }} className="relative mb-2">
              <motion.span className="absolute -left-6 top-2.5 flex h-[18px] w-[18px] items-center justify-center rounded-full border font-mono text-[9px]"
                style={{ borderColor: s.status === "skipped" ? "#64716b" : color, color: s.status === "skipped" ? "#64716b" : "#03110a", background: s.status === "skipped" ? "transparent" : color }}
                initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: k * 0.09 + 0.1, type: "spring" }}>{s.position}</motion.span>
              <button onClick={() => setOpen(open === s.position ? null : s.position)}
                className={cx("w-full rounded-[3px] border p-2.5 text-left transition-colors", open === s.position ? "border-green/50 bg-green/[0.05]" : "border-line hover:border-green/30")}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm" style={{ color }}>{s.layer}</span>
                  <Badge>{s.mode.replace("_", " ")}</Badge>
                  <span className="text-[11px] text-muted">{s.status}</span>
                  <span className="ml-auto font-mono text-[10.5px] text-muted">{applied.length} applied · {s.latency_ms ? `${(s.latency_ms / 1000).toFixed(1)}s` : "—"}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {s.rule_states.map((r) => <span key={r.rule} title={`${r.state}: ${r.reason}`} className={cx("rounded-sm border px-1 font-mono text-[10px]", STATE_STYLE[r.state] ?? "border-line text-muted")}>{r.rule}</span>)}
                </div>
              </button>
              <AnimatePresence>
                {open === s.position && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                    <div className="space-y-2 border-x border-b border-green/20 bg-black/50 p-3 text-xs">
                      {s.output && <div className="whitespace-pre-wrap text-text">{s.output}</div>}
                      {s.rule_states.filter((r) => r.state === "applied" || r.state === "not_applicable").map((r) => (
                        <div key={r.rule} className="text-muted"><span className={r.state === "applied" ? "text-green" : ""}>{r.rule}</span> — {r.reason}</div>
                      ))}
                      {s.model && <div className="font-mono text-[10.5px] text-muted">{s.model}</div>}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          );
        })}
      </div>
      {run.conflicts.length > 0 && (
        <div className="space-y-1">
          <div className="x-label">Conflicts resolved by the source hierarchy</div>
          {run.conflicts.map((c, k) => <div key={k} className="text-xs text-dim"><span className="font-mono text-amber">{c.rules.join(" vs ")}</span> → <span className="text-green">{c.winner}</span> ({c.hierarchy_step})</div>)}
        </div>
      )}
      <div className="flex flex-wrap gap-3 text-[10.5px] text-muted">
        {Object.entries(STATE_STYLE).map(([k, v]) => <span key={k} className="flex items-center gap-1"><span className={cx("rounded-sm border px-1 font-mono", v)}>ID</span>{k.replace("_", " ")}</span>)}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Quantum

function Circuit({ qubits, algorithm, color, reduced }: { qubits: number; algorithm: string; color: string; reduced: boolean }) {
  const n = Math.max(1, Math.min(qubits, 12));
  const p = Number(/_p(\d+)/.exec(algorithm)?.[1] ?? (algorithm.startsWith("qaoa") ? 1 : 2));
  const isQaoa = algorithm.startsWith("qaoa");
  const cols = 2 + p * 2 + 1;
  const W = 120 + cols * 70, H = 24 + n * 26;
  const x = (c: number) => 70 + c * 70;
  const y = (q: number) => 22 + q * 26;
  return (
    <div className="overflow-x-auto rounded-[3px] border border-line bg-black/60 p-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto min-w-[560px]" style={{ width: "100%" }} role="img"
        aria-label={`Schematic of ${algorithm}: ${qubits} qubits, ${p} layer(s)`}>
        {Array.from({ length: n }, (_, q) => (
          <g key={q}>
            <text x={8} y={y(q) + 4} fontSize="10" fill="#64716b" fontFamily="monospace">q{q}</text>
            <line x1={36} y1={y(q)} x2={W - 20} y2={y(q)} stroke="rgba(124,140,255,0.35)" />
          </g>
        ))}
        {Array.from({ length: n }, (_, q) => (
          <g key={"h" + q}><rect x={x(0) - 11} y={y(q) - 9} width={22} height={18} fill="#0b0f22" stroke={color} />
            <text x={x(0)} y={y(q) + 4} fontSize="10" fill={color} textAnchor="middle" fontFamily="monospace">H</text></g>
        ))}
        {Array.from({ length: p }, (_, l) => (
          <g key={"l" + l}>
            <rect x={x(1 + l * 2) - 22} y={y(0) - 11} width={44} height={y(n - 1) - y(0) + 22} rx={3} fill="rgba(124,140,255,0.10)" stroke={color} />
            <text x={x(1 + l * 2)} y={y(0) - 14} fontSize="9" fill={color} textAnchor="middle" fontFamily="monospace">{isQaoa ? `U_C(γ${l + 1})` : `ENT ${l + 1}`}</text>
            {Array.from({ length: n }, (_, q) => (
              <g key={q}><rect x={x(2 + l * 2) - 13} y={y(q) - 9} width={26} height={18} fill="#0b0f22" stroke="#45d9f5" />
                <text x={x(2 + l * 2)} y={y(q) + 4} fontSize="9" fill="#45d9f5" textAnchor="middle" fontFamily="monospace">{isQaoa ? "Rx" : "Ry"}</text></g>
            ))}
            <text x={x(2 + l * 2)} y={y(0) - 14} fontSize="9" fill="#45d9f5" textAnchor="middle" fontFamily="monospace">{isQaoa ? `U_B(β${l + 1})` : "θ"}</text>
          </g>
        ))}
        {Array.from({ length: n }, (_, q) => (
          <g key={"m" + q}><rect x={x(cols - 1) - 12} y={y(q) - 9} width={24} height={18} fill="#0b0f22" stroke="#3cf59a" />
            <path d={`M${x(cols - 1) - 7} ${y(q) + 4} Q${x(cols - 1)} ${y(q) - 6} ${x(cols - 1) + 7} ${y(q) + 4}`} fill="none" stroke="#3cf59a" /></g>
        ))}
        {!reduced && (
          <motion.rect y={8} width={4} height={H - 16} fill={color} opacity={0.5} style={{ filter: `drop-shadow(0 0 6px ${color})` }}
            initial={{ x: 40 }} animate={{ x: [40, W - 24] }} transition={{ duration: 3.2, repeat: Infinity, ease: "linear" }} />
        )}
      </svg>
      <div className="mt-1 text-[10.5px] text-muted">Schematic of the algorithm structure ({qubits} qubits{qubits > 12 ? ", first 12 drawn" : ""}, {p} layer{p > 1 ? "s" : ""}) — not the transpiled hardware circuit.</div>
    </div>
  );
}

function QuantumView({ trace, execution, color, reduced }: { trace: ExecutionTrace; execution: Execution | null; color: string; reduced: boolean }) {
  const qd = execution?.plan?.quantum_decision;
  const job = trace.quantum_jobs.find((j) => j.status === "completed") ?? trace.quantum_jobs[0];
  const counts = job?.result?.top_counts ?? [];
  const maxC = Math.max(1, ...counts.map(([, c]) => c));
  return (
    <div className="space-y-4">
      {qd && (
        <div className="rounded-[3px] border p-3" style={{ borderColor: `${color}55` }}>
          <div className="mb-1 font-mono text-[10.5px] tracking-[0.2em]" style={{ color }}>SELECTION ENGINE {"//"} {qd.decision.replace(/_/g, " ").toUpperCase()}</div>
          <p className="text-sm text-dim">{qd.explanation}</p>
        </div>
      )}
      {!job ? <p className="text-sm text-muted">No quantum job ran in this execution{qd ? " — see the selection decision above" : ""}.</p> : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
            <Stat label="BACKEND" value={<span className="text-sm">{job.backend_key}</span>} color={color} />
            <Stat label="ALGORITHM" value={<span className="text-sm">{job.algorithm}</span>} color={color} />
            <Stat label="QUBITS" value={job.qubits} color={color} />
            <Stat label="DEPTH" value={job.circuit_depth} color={color} />
            <Stat label="SHOTS" value={job.shots.toLocaleString()} color={color} />
            <Stat label="WALL TIME" value={`${job.wall_time_s.toFixed(2)}s`} color={color} />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs"><ExecBadge cls={job.execution_class} />
            {job.result?.objective_value !== undefined && <span className="text-dim">objective <span className="font-mono text-text">{fmtNum(job.result.objective_value)}</span> · {job.result.feasible ? "feasible" : "infeasible"}</span>}
            {job.error && <span className="text-red">{job.error}</span>}</div>
          <Circuit qubits={job.qubits} algorithm={job.algorithm} color={color} reduced={reduced} />
          {counts.length > 0 && (
            <div>
              <div className="x-label mb-2">Measurement histogram — most frequent bitstrings</div>
              <div className="flex h-36 items-end gap-1.5">
                {counts.map(([b, c], k) => (
                  <div key={b} className="flex min-w-0 flex-1 flex-col items-center gap-1">
                    <span className="font-mono text-[9.5px] text-muted">{c}</span>
                    <motion.div className="w-full rounded-t-sm" style={{ background: `linear-gradient(180deg, ${color}, ${color}44)`, boxShadow: `0 0 10px ${color}66` }}
                      initial={{ height: 0 }} animate={{ height: `${(c / maxC) * 100}px` }} transition={{ duration: 0.9, delay: k * 0.07 }} />
                    <span className="w-full truncate text-center font-mono text-[8.5px] text-dim" title={b}>{b}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
      {qd && (
        <details className="rounded-[3px] border border-line p-2 text-xs">
          <summary className="cursor-pointer text-dim">The 15 factors evaluated</summary>
          <div className="mt-2 grid gap-x-4 gap-y-1 sm:grid-cols-2">
            {Object.entries(qd.factors).map(([k, v]) => <div key={k}><span className="text-muted">{k.replace(/_/g, " ")}:</span> <span className="text-text">{v === null ? "—" : String(v)}</span></div>)}
          </div>
        </details>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ shell

export function EngineInspector({ engine, execution, events, onClose, onSwitch, reducedMotion }: {
  engine: Engine | null; execution: Execution | null; events: ExecEvent[]; onClose: () => void;
  onSwitch: (e: Engine) => void; reducedMotion: boolean;
}) {
  const [trace, setTrace] = useState<ExecutionTrace | null>(null);
  const [error, setError] = useState<unknown>(null);
  const running = !!execution && ["queued", "running"].includes(execution.status);

  useEffect(() => {
    if (!engine) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [engine, onClose]);

  useEffect(() => {
    if (!engine) return;
    setError(null);
    if (!execution) { setTrace({ intellect_runs: [], ai_calls: [], quantum_jobs: [] }); return; }
    let stop = false;
    const load = () => api.get<ExecutionTrace>(`/executions/${execution.id}/trace`).then((t) => { if (!stop) setTrace(t); }).catch(setError);
    load();
    const t = running ? setInterval(load, 2500) : null;
    return () => { stop = true; if (t) clearInterval(t); };
  }, [engine, execution?.id, running, execution]);

  return (
    <AnimatePresence>
      {engine && (
        <motion.div key="inspector" className="fixed inset-0 z-50 flex items-stretch justify-center overflow-y-auto bg-black/80 p-3 backdrop-blur-md sm:p-8"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
          <motion.div role="dialog" aria-modal="true" aria-label={META[engine].title}
            className="x-panel x-scanlines relative my-auto w-full max-w-6xl overflow-hidden p-0"
            initial={{ scale: 0.92, opacity: 0, filter: "blur(6px)" }} animate={{ scale: 1, opacity: 1, filter: "blur(0px)" }}
            exit={{ scale: 0.96, opacity: 0 }} transition={{ type: "spring", stiffness: 220, damping: 24 }}
            style={{ borderColor: `${META[engine].color}55`, boxShadow: `0 0 60px -20px ${META[engine].color}` }}>
            {!reducedMotion && (
              <motion.div aria-hidden className="pointer-events-none absolute inset-x-0 h-24"
                style={{ background: `linear-gradient(180deg, transparent, ${META[engine].color}14, transparent)` }}
                initial={{ top: "-10%" }} animate={{ top: ["-10%", "110%"] }} transition={{ duration: 3.5, repeat: Infinity, ease: "linear" }} />
            )}
            <header className="relative flex items-center justify-between gap-3 border-b px-5 py-3" style={{ borderColor: `${META[engine].color}33` }}>
              <div className="flex items-center gap-3">
                <motion.span className="h-3 w-3 rotate-45 border" style={{ borderColor: META[engine].color, background: running ? META[engine].color : "transparent" }}
                  animate={running && !reducedMotion ? { opacity: [0.4, 1, 0.4] } : undefined} transition={{ duration: 1.2, repeat: Infinity }} />
                <div>
                  <GlitchText text={META[engine].title} className="font-mono text-base tracking-[0.3em]" />
                  <div className="font-mono text-[10px] tracking-[0.18em] text-muted">{META[engine].tagline}{execution ? ` · EXEC ${execution.id.slice(0, 8)}` : ""}</div>
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                {(["intellect", "ai", "quantum"] as Engine[]).map((k) => (
                  <button key={k} onClick={() => onSwitch(k)} aria-pressed={k === engine}
                    className="hidden rounded-[2px] border px-2 py-1 font-mono text-[10px] tracking-[0.15em] sm:inline"
                    style={{ borderColor: k === engine ? META[k].color : "rgba(140,255,200,0.12)", color: k === engine ? META[k].color : "#64716b" }}>
                    {k.toUpperCase()}
                  </button>
                ))}
                <button onClick={onClose} className="rounded border border-line-strong px-2.5 py-1 font-mono text-xs text-dim hover:text-text" aria-label="Close inspector">ESC ✕</button>
              </div>
            </header>
            <div className="relative space-y-4 p-5">
              <ErrorNote error={error} />
              {!trace ? <Spinner /> : engine === "ai" ? <AIView trace={trace} execution={execution} color={META.ai.color} />
                : engine === "intellect" ? <IntellectView trace={trace} color={META.intellect.color} />
                : <QuantumView trace={trace} execution={execution} color={META.quantum.color} reduced={reducedMotion} />}
              <EngineEvents events={events} engine={engine} color={META[engine].color} />
              {!execution && <p className="text-xs text-muted">Run or open an execution to inspect what this engine did.</p>}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
