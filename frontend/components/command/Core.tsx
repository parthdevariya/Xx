"use client";

import { motion } from "framer-motion";
import type { EngineState } from "./useExecution";

const ENGINES = [
  { key: "intellect", label: "INTELLECT", color: "#3cf59a", angle: -90 },
  { key: "ai", label: "AI", color: "#45d9f5", angle: 150 },
  { key: "quantum", label: "QUANTUM", color: "#7c8cff", angle: 30 },
] as const;

const R = 118;
const C = 170;

function pos(angle: number) {
  const a = (angle * Math.PI) / 180;
  return { x: C + R * Math.cos(a), y: C + R * Math.sin(a) };
}

const STATE_LABEL: Record<EngineState, string> = {
  idle: "Idle", initializing: "Initializing", ready: "Ready", processing: "Processing", waiting: "Waiting",
  completed: "Completed", failed: "Failed", unavailable: "Unavailable",
};

/** The X computational core. Node states and flows reflect real engine states derived from backend events. */
export function Core({ states, running, reducedMotion }: {
  states: Record<"ai" | "quantum" | "intellect", EngineState>; running: boolean; reducedMotion: boolean;
}) {
  return (
    <div className="relative mx-auto aspect-square w-full max-w-[340px]">
      <svg viewBox="0 0 340 340" className="h-full w-full" role="img"
        aria-label={`Engine states: ${ENGINES.map((e) => `${e.label} ${STATE_LABEL[states[e.key]]}`).join(", ")}`}>
        <defs>
          <radialGradient id="coreGlow">
            <stop offset="0%" stopColor="#3cf59a" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#3cf59a" stopOpacity="0" />
          </radialGradient>
        </defs>
        {[150, 120, 88].map((r, i) => (
          <circle key={r} cx={C} cy={C} r={r} fill="none" stroke="rgba(140,255,200,0.07)" strokeDasharray={i === 1 ? "2 6" : undefined} />
        ))}
        {!reducedMotion && (
          <motion.circle cx={C} cy={C} r={150} fill="none" stroke="rgba(60,245,154,0.25)" strokeWidth={1}
            strokeDasharray="40 900" animate={{ rotate: 360 }} style={{ originX: "170px", originY: "170px" }}
            transition={{ duration: running ? 6 : 24, repeat: Infinity, ease: "linear" }} />
        )}
        {ENGINES.map((e) => {
          const p = pos(e.angle);
          const st = states[e.key];
          const active = st === "processing";
          const dim = st === "unavailable";
          return (
            <g key={e.key}>
              <line x1={C} y1={C} x2={p.x} y2={p.y} stroke={e.color} strokeOpacity={dim ? 0.08 : 0.22} strokeWidth={1} />
              {active && !reducedMotion && [0, 0.5].map((d) => (
                <motion.circle key={d} r={2.6} fill={e.color}
                  initial={{ cx: p.x, cy: p.y, opacity: 0 }}
                  animate={{ cx: [p.x, C], cy: [p.y, C], opacity: [0, 1, 0] }}
                  transition={{ duration: 1.2, repeat: Infinity, delay: d, ease: "easeIn" }} />
              ))}
            </g>
          );
        })}
        {ENGINES.map((a, i) => {
          const b = ENGINES[(i + 1) % 3];
          const pa = pos(a.angle), pb = pos(b.angle);
          return <line key={a.key + b.key} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="rgba(140,255,200,0.05)" />;
        })}
        <circle cx={C} cy={C} r={60} fill="url(#coreGlow)" opacity={running ? 1 : 0.5} />
        <circle cx={C} cy={C} r={34} fill="#070a0b" stroke="rgba(60,245,154,0.4)" />
        <path d={`M${C - 13} ${C - 13} L${C} ${C} L${C + 13} ${C - 13} M${C - 13} ${C + 13} L${C} ${C} L${C + 13} ${C + 13}`}
          stroke="#3cf59a" strokeWidth={2.4} strokeLinecap="round" fill="none" />
        {ENGINES.map((e) => {
          const p = pos(e.angle);
          const st = states[e.key];
          const dim = st === "unavailable";
          return (
            <g key={e.key + "n"} opacity={dim ? 0.45 : 1}>
              {st === "processing" && !reducedMotion && (
                <motion.circle cx={p.x} cy={p.y} r={26} fill="none" stroke={e.color}
                  style={{ transformBox: "fill-box", transformOrigin: "center" }}
                  animate={{ scale: [1, 1.55], opacity: [0.6, 0] }} transition={{ duration: 1.4, repeat: Infinity }} />
              )}
              <circle cx={p.x} cy={p.y} r={26} fill="#0a0e0f" stroke={st === "failed" ? "#ff5f6d" : e.color}
                strokeOpacity={dim ? 0.3 : 0.9} strokeWidth={st === "processing" ? 2 : 1.2} />
              <circle cx={p.x} cy={p.y} r={4} fill={st === "failed" ? "#ff5f6d" : e.color}
                opacity={st === "completed" || st === "processing" ? 1 : st === "ready" || st === "waiting" ? 0.6 : 0.25} />
            </g>
          );
        })}
      </svg>
      {ENGINES.map((e) => {
        const p = pos(e.angle);
        const top = e.angle === -90 ? p.y - 64 : p.y + 30;
        return (
          <div key={e.key + "l"} className="pointer-events-none absolute -translate-x-1/2 text-center"
            style={{ left: `${(p.x / 340) * 100}%`, top: `${(top / 340) * 100}%` }}>
            <div className="font-mono text-[10.5px] tracking-[0.2em]" style={{ color: e.color }}>{e.label}</div>
            <div className="font-mono text-[10px] text-muted">{STATE_LABEL[states[e.key]]}</div>
          </div>
        );
      })}
    </div>
  );
}
