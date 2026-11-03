"use client";

import { motion } from "framer-motion";
import { liveStatus } from "@/components/command/Insights";
import { cx } from "@/components/ui";
import type { ExecEvent, Execution } from "@/lib/types";

const ENGINE_COLOR: Record<string, string> = {
  system: "#c9d3ce", ai: "#45d9f5", quantum: "#7c8cff", intellect: "#3cf59a", classical: "#e6efe9",
};

const STATUS_TEXT: Record<string, string> = {
  completed: "DONE", running: "LIVE", planned: "QUEUED", skipped: "SKIPPED", "not run": "NOT RUN",
  queued: "QUEUED", failed: "FAULT", cancelled: "HALTED",
};

/** Animated execution track. Nodes ignite only on their recorded events; skipped steps carry their reason. */
export function ProcessTimeline({ execution, events, reducedMotion }: {
  execution: Execution | null; events: ExecEvent[]; reducedMotion: boolean;
}) {
  const steps = execution?.plan?.steps ?? [];
  if (!execution || !steps.length) {
    return (
      <div className="flex h-24 items-center justify-center font-mono text-[11px] tracking-[0.18em] text-muted">
        AWAITING EXECUTION PLAN
      </div>
    );
  }
  const statuses = steps.map((s) => liveStatus(s, events, execution.status));
  const activeIdx = statuses.findIndex((s) => s === "running");
  return (
    <div className="overflow-x-auto pb-1">
      <ol className="flex min-w-max items-start gap-0 px-1 pt-2" aria-label="Execution process">
        {steps.map((s, i) => {
          const st = statuses[i];
          const color = st === "failed" ? "#ff5f6d" : ENGINE_COLOR[s.engine] ?? "#c9d3ce";
          const lit = st === "completed";
          const live = st === "running";
          const off = st === "skipped" || st === "not run";
          const nextLive = i < steps.length - 1 && (statuses[i + 1] === "running" || (lit && statuses[i + 1] === "completed"));
          return (
            <li key={s.key} className="flex items-start">
              <div tabIndex={0} title={s.reason || s.title}
                aria-label={`${s.title}: ${st}${s.reason ? ` — ${s.reason}` : ""}`}
                className={cx("group relative flex w-[118px] flex-col items-center text-center outline-none", off && "opacity-45")}>
                <div className="relative h-12 w-12">
                  {live && !reducedMotion && (
                    <motion.span className="absolute inset-0 rotate-45 border" style={{ borderColor: color }}
                      animate={{ scale: [1, 1.6], opacity: [0.9, 0] }} transition={{ duration: 1.2, repeat: Infinity }} />
                  )}
                  <span className="absolute inset-[7px] rotate-45 border bg-black/80 transition-all"
                    style={{ borderColor: lit || live ? color : "rgba(140,255,200,0.2)",
                      boxShadow: lit || live ? `0 0 14px -2px ${color}, inset 0 0 10px -4px ${color}` : undefined }} />
                  <span className="absolute inset-0 flex items-center justify-center font-mono text-[11px]"
                    style={{ color: lit || live ? color : "rgba(140,255,200,0.4)" }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                </div>
                <div className="mt-1.5 line-clamp-2 px-1 text-[11px] leading-tight text-dim group-focus-visible:text-text">{s.title}</div>
                <div className="mt-0.5 font-mono text-[9.5px] tracking-[0.16em]" style={{ color: live ? color : lit ? color : "var(--muted)" }}>
                  {STATUS_TEXT[st] ?? st.toUpperCase()}
                </div>
                {s.reason && (
                  <div role="tooltip" className="pointer-events-none absolute top-full z-20 mt-1 hidden w-52 rounded-[3px] border border-green/25 bg-black/95 p-2 text-left text-[11px] text-dim group-hover:block group-focus-visible:block">
                    {s.reason}
                  </div>
                )}
              </div>
              {i < steps.length - 1 && (
                <div aria-hidden className="relative mt-6 h-px w-10 overflow-hidden bg-green/15">
                  {(lit || nextLive) && <div className="absolute inset-0" style={{ background: color, opacity: 0.55 }} />}
                  {i === activeIdx - 1 && !reducedMotion && (
                    <motion.div className="absolute inset-y-[-1px] w-4 rounded-full"
                      style={{ background: `linear-gradient(90deg, transparent, ${color}, #fff)` }}
                      animate={{ x: [-16, 40] }} transition={{ duration: 0.8, repeat: Infinity, ease: "linear" }} />
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
