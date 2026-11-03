"use client";

import { motion } from "framer-motion";
import type { ExecEvent } from "@/lib/types";
import type { EngineState } from "./useExecution";

const S = 400;
const C = S / 2;
const NODE_R = 112;

const ENGINES = [
  { key: "intellect", label: "INTELLECT", color: "#3cf59a", angle: -90 },
  { key: "ai", label: "AI", color: "#45d9f5", angle: 150 },
  { key: "quantum", label: "QUANTUM", color: "#7c8cff", angle: 30 },
] as const;

const STATE_LABEL: Record<EngineState, string> = {
  idle: "IDLE", initializing: "INIT", ready: "READY", processing: "PROCESSING", waiting: "STANDBY",
  completed: "COMPLETE", failed: "FAULT", unavailable: "OFFLINE",
};

type StageState = "pending" | "active" | "done" | "skipped";

function polar(r: number, deg: number) {
  const a = (deg * Math.PI) / 180;
  return { x: C + r * Math.cos(a), y: C + r * Math.sin(a) };
}

function arc(r1: number, r2: number, a0: number, a1: number) {
  const p0 = polar(r2, a0), p1 = polar(r2, a1), p2 = polar(r1, a1), p3 = polar(r1, a0);
  const large = a1 - a0 > 180 ? 1 : 0;
  return `M${p0.x} ${p0.y} A${r2} ${r2} 0 ${large} 1 ${p1.x} ${p1.y} L${p2.x} ${p2.y} A${r1} ${r1} 0 ${large} 0 ${p3.x} ${p3.y}Z`;
}

function hexagon(cx: number, cy: number, r: number) {
  return Array.from({ length: 6 }, (_, i) => {
    const a = (Math.PI / 3) * i - Math.PI / 6;
    return `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
  }).join(" ");
}

/** Intellect stage states from real events (event.data.position is the stage number). */
export function stageStates(events: ExecEvent[]): { states: StageState[]; total: number } {
  let total = 13;
  const st: Record<number, StageState> = {};
  for (const e of events) {
    const pos = Number((e.data as { position?: number })?.position);
    if (!pos) continue;
    total = Math.max(total, pos);
    if (e.type === "intellect.stage_started") st[pos] = "active";
    else if (e.type === "intellect.stage_completed") st[pos] = "done";
    else if (e.type === "intellect.stage_skipped") st[pos] = "skipped";
  }
  return { states: Array.from({ length: total }, (_, i) => st[i + 1] ?? "pending"), total };
}

/** The X reactor. Every lit element maps to a real engine state or recorded pipeline event. */
export function Core({ states, running, reducedMotion, events = [] }: {
  states: Record<"ai" | "quantum" | "intellect", EngineState>; running: boolean; reducedMotion: boolean;
  events?: ExecEvent[];
}) {
  const { states: stages, total } = stageStates(events);
  const anyStage = stages.some((s) => s !== "pending");
  const seg = 360 / total;
  const spin = (sec: number) => (reducedMotion ? undefined : { rotate: 360, transition: { duration: sec, repeat: Infinity, ease: "linear" as const } });
  const spinBack = (sec: number) => (reducedMotion ? undefined : { rotate: -360, transition: { duration: sec, repeat: Infinity, ease: "linear" as const } });
  const origin = { originX: `${C}px`, originY: `${C}px` };

  return (
    <div className="relative mx-auto aspect-square w-full max-w-[400px]">
      <svg viewBox={`0 0 ${S} ${S}`} className="h-full w-full" role="img"
        aria-label={`Engine states: ${ENGINES.map((e) => `${e.label} ${STATE_LABEL[states[e.key]]}`).join(", ")}.` +
          (anyStage ? ` Intellect stages complete: ${stages.filter((s) => s === "done").length} of ${total}.` : "")}>
        <defs>
          <radialGradient id="rx-core">
            <stop offset="0%" stopColor="#3cf59a" stopOpacity="0.55" />
            <stop offset="45%" stopColor="#3cf59a" stopOpacity="0.12" />
            <stop offset="100%" stopColor="#3cf59a" stopOpacity="0" />
          </radialGradient>
          <filter id="rx-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.4" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        {/* Intellect pipeline ring: 13 segments lit by real stage events */}
        <g aria-hidden>
          {stages.map((s, i) => {
            const a0 = -90 + i * seg + 1.6, a1 = -90 + (i + 1) * seg - 1.6;
            const fill = s === "done" ? "#3cf59a" : s === "active" ? "#b8ffd9" : s === "skipped" ? "rgba(100,113,107,0.35)" : "rgba(60,245,154,0.07)";
            const mid = polar(196, -90 + (i + 0.5) * seg);
            return (
              <g key={i}>
                {s === "active" && !reducedMotion ? (
                  <motion.path d={arc(178, 190, a0, a1)} fill={fill} filter="url(#rx-glow)"
                    animate={{ opacity: [0.35, 1, 0.35] }} transition={{ duration: 0.9, repeat: Infinity }} />
                ) : (
                  <path d={arc(178, 190, a0, a1)} fill={fill} filter={s === "done" ? "url(#rx-glow)" : undefined}
                    stroke="rgba(60,245,154,0.18)" strokeWidth={0.5} />
                )}
                <text x={mid.x} y={mid.y} fill={s === "pending" ? "rgba(140,255,200,0.25)" : "rgba(184,255,217,0.8)"}
                  fontSize="7.5" fontFamily="monospace" textAnchor="middle" dominantBaseline="middle">{i + 1}</text>
              </g>
            );
          })}
        </g>

        {/* tick ring */}
        <motion.g aria-hidden style={origin} animate={spin(running ? 30 : 120)}>
          {Array.from({ length: 72 }, (_, i) => {
            const p0 = polar(166, i * 5), p1 = polar(i % 6 === 0 ? 158 : 162, i * 5);
            return <line key={i} x1={p0.x} y1={p0.y} x2={p1.x} y2={p1.y} stroke="rgba(60,245,154,0.28)" strokeWidth={i % 6 === 0 ? 1.2 : 0.6} />;
          })}
        </motion.g>
        <motion.circle aria-hidden cx={C} cy={C} r={148} fill="none" stroke="rgba(69,217,245,0.35)" strokeWidth={1}
          strokeDasharray="60 18 4 18" style={origin} animate={spinBack(running ? 14 : 60)} />
        <motion.circle aria-hidden cx={C} cy={C} r={138} fill="none" stroke="rgba(60,245,154,0.18)" strokeWidth={6}
          strokeDasharray="2 10" style={origin} animate={spin(running ? 20 : 90)} />

        {/* triangle lattice between engines */}
        {ENGINES.map((a, i) => {
          const b = ENGINES[(i + 1) % 3];
          const pa = polar(NODE_R, a.angle), pb = polar(NODE_R, b.angle);
          return <line key={a.key + b.key} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="rgba(140,255,200,0.08)" strokeDasharray="3 5" />;
        })}

        {/* beams engine -> core */}
        {ENGINES.map((e) => {
          const p = polar(NODE_R, e.angle);
          const st = states[e.key];
          const active = st === "processing";
          const done = st === "completed";
          return (
            <g key={e.key + "beam"}>
              <line x1={C} y1={C} x2={p.x} y2={p.y} stroke={e.color} strokeOpacity={st === "unavailable" ? 0.06 : done ? 0.45 : 0.16}
                strokeWidth={done ? 1.6 : 1} />
              {active && (
                <>
                  <motion.line x1={p.x} y1={p.y} x2={C} y2={C} stroke={e.color} strokeWidth={3} strokeLinecap="round"
                    strokeDasharray="10 22" filter="url(#rx-glow)"
                    animate={reducedMotion ? undefined : { strokeDashoffset: [0, -64] }}
                    transition={{ duration: 0.7, repeat: Infinity, ease: "linear" }} />
                  {!reducedMotion && [0, 0.33, 0.66].map((d) => (
                    <motion.circle key={d} r={3} fill="#fff"
                      initial={{ cx: p.x, cy: p.y, opacity: 0 }}
                      animate={{ cx: [p.x, C], cy: [p.y, C], opacity: [0, 1, 0] }}
                      transition={{ duration: 1, repeat: Infinity, delay: d, ease: "easeIn" }} />
                  ))}
                </>
              )}
            </g>
          );
        })}

        {/* core */}
        <motion.circle cx={C} cy={C} r={running ? 78 : 64} fill="url(#rx-core)"
          animate={running && !reducedMotion ? { opacity: [0.6, 1, 0.6] } : undefined}
          transition={{ duration: 1.6, repeat: Infinity }} />
        <motion.polygon points={hexagon(C, C, 46)} fill="none" stroke="rgba(60,245,154,0.35)" strokeWidth={1}
          style={{ transformBox: "fill-box", transformOrigin: "center" }} animate={spin(running ? 8 : 40)} />
        <circle cx={C} cy={C} r={36} fill="#030605" stroke="rgba(60,245,154,0.75)" strokeWidth={1.4} filter="url(#rx-glow)" />
        <path d={`M${C - 14} ${C - 14} L${C} ${C} L${C + 14} ${C - 14} M${C - 14} ${C + 14} L${C} ${C} L${C + 14} ${C + 14}`}
          stroke="#3cf59a" strokeWidth={2.8} strokeLinecap="round" fill="none" filter="url(#rx-glow)" />

        {/* engine nodes */}
        {ENGINES.map((e) => {
          const p = polar(NODE_R, e.angle);
          const st = states[e.key];
          const color = st === "failed" ? "#ff5f6d" : e.color;
          const dim = st === "unavailable";
          return (
            <g key={e.key + "node"} opacity={dim ? 0.4 : 1}>
              {st === "processing" && !reducedMotion && (
                <motion.polygon points={hexagon(p.x, p.y, 30)} fill="none" stroke={color}
                  style={{ transformBox: "fill-box", transformOrigin: "center" }}
                  animate={{ scale: [1, 1.7], opacity: [0.8, 0] }} transition={{ duration: 1.3, repeat: Infinity }} />
              )}
              <polygon points={hexagon(p.x, p.y, 30)} fill="rgba(3,8,6,0.92)" stroke={color}
                strokeWidth={st === "processing" ? 2.2 : 1.2} strokeOpacity={dim ? 0.4 : 0.95}
                filter={st === "processing" || st === "completed" ? "url(#rx-glow)" : undefined} />
              <polygon points={hexagon(p.x, p.y, 22)} fill="none" stroke={color} strokeOpacity={0.25} />
              <circle cx={p.x} cy={p.y} r={5} fill={color}
                opacity={st === "completed" || st === "processing" ? 1 : st === "ready" || st === "waiting" ? 0.55 : 0.2} />
            </g>
          );
        })}
      </svg>

      {ENGINES.map((e) => {
        const p = polar(NODE_R, e.angle);
        const top = e.angle === -90 ? p.y - 66 : p.y + 34;
        const st = states[e.key];
        return (
          <div key={e.key + "l"} className="pointer-events-none absolute -translate-x-1/2 text-center"
            style={{ left: `${(p.x / S) * 100}%`, top: `${(top / S) * 100}%` }}>
            <div className="font-mono text-[10.5px] tracking-[0.24em]" style={{ color: e.color, textShadow: `0 0 8px ${e.color}88` }}>{e.label}</div>
            <div className={`font-mono text-[9.5px] tracking-[0.14em] ${st === "processing" ? "text-text" : "text-muted"}`}>{STATE_LABEL[st]}</div>
          </div>
        );
      })}
      {anyStage && (
        <div className="pointer-events-none absolute bottom-0 left-1/2 -translate-x-1/2 font-mono text-[10px] tracking-[0.18em] text-green/80">
          INTELLECT PIPELINE {stages.filter((s) => s === "done").length}/{total}
        </div>
      )}
    </div>
  );
}
