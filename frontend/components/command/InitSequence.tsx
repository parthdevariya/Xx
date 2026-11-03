"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { GlitchText } from "@/components/fx/GlitchText";
import { MatrixRain } from "@/components/fx/MatrixRain";
import { XMark } from "@/components/XMark";
import { api } from "@/lib/api";
import type { SystemStatus } from "@/lib/types";

type Line = { label: string; state: "pending" | "ok" | "warn" | "off"; detail: string };

/** Initialisation sequence driven by the real /api/system/status. Never blocks entry; Skip is always available. */
export function InitSequence({ onDone, reducedMotion }: { onDone: (s: SystemStatus | null) => void; reducedMotion: boolean }) {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [shown, setShown] = useState(0);

  useEffect(() => {
    api.get<SystemStatus>("/system/status").then(setStatus).catch((e) => setFailed(e.message));
  }, []);

  const lines: Line[] = [
    { label: "System initialization", state: status || failed ? (failed ? "warn" : "ok") : "pending",
      detail: failed ? `backend unreachable: ${failed}` : status ? "database online" : "contacting backend…" },
    { label: "Connecting intelligence services", state: !status ? "pending" : status.ai.status === "ready" ? "ok" : "off",
      detail: !status ? "…" : status.ai.status === "ready" ? status.ai.configured_providers.join(", ")
        : status.ai.test_provider_active ? "no real provider · test provider active" : "no AI provider configured" },
    { label: "Initializing computational environment", state: !status ? "pending" : "ok",
      detail: !status ? "…" : "classical solvers · job queue" },
    { label: "Loading Intellect framework", state: !status ? "pending" : status.intellect.status === "ready" ? "ok" : "warn",
      detail: !status ? "…" : status.intellect.version
        ? `${status.intellect.framework} ${status.intellect.version} · ${status.intellect.layers} layers · ${status.intellect.rules} rules · ${status.intellect.protected} guardrails`
        : "no published framework" },
    { label: "Checking quantum integrations", state: !status ? "pending" : status.quantum.status === "ready" ? "ok" : "off",
      detail: !status ? "…" : status.quantum.providers.map((p) => `${p.vendor}:${p.status === "healthy" && p.active ? "ready" : p.status}`).join("  ") },
    { label: "Loading scenario library", state: !status ? "pending" : "ok",
      detail: !status ? "…" : `${status.scenarios.published} published scenarios` },
  ];

  useEffect(() => {
    if (reducedMotion) {
      setShown(lines.length + 1);
      return;
    }
    if (shown <= lines.length) {
      const t = setTimeout(() => setShown((s) => s + 1), shown === 0 ? 250 : 380);
      return () => clearTimeout(t);
    }
  }, [shown, reducedMotion, lines.length]);

  const ready = shown > lines.length && (status || failed);

  useEffect(() => {
    if (!ready) return;
    const t = setTimeout(() => onDone(status), reducedMotion ? 300 : 900);
    return () => clearTimeout(t);
  }, [ready, onDone, status, reducedMotion]);

  const glyph = { pending: "◌", ok: "●", warn: "▲", off: "○" };
  const color = { pending: "text-amber", ok: "text-green", warn: "text-amber", off: "text-muted" };

  return (
    <AnimatePresence>
      <motion.div key="init" initial={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.6 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-bg px-4" role="status" aria-live="polite">
        {!reducedMotion && <MatrixRain opacity={0.22} />}
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_20%,#050708_75%)]" />
        <div className="x-panel x-scanlines relative w-full max-w-xl p-6 sm:p-8">
          <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.8 }}
            className="mb-7 flex items-center gap-4">
            <XMark size={52} />
            <div>
              <GlitchText text="X" className="font-display text-3xl font-semibold tracking-[0.5em] x-phosphor" duration={1200} />
              <div className="x-label">
                <GlitchText text="AI · QUANTUM · INTELLECT" duration={1400} />
              </div>
            </div>
          </motion.div>
          <div className="mb-3 font-mono text-[10.5px] tracking-[0.16em] text-green/50">BOOT SEQUENCE // LIVE SYSTEM STATUS</div>
          <ol className="space-y-2.5 font-mono text-[13px]">
            {lines.slice(0, shown).map((l) => (
              <motion.li key={l.label} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                className="grid grid-cols-[18px_1fr] gap-x-2">
                <span className={color[l.state]}>{glyph[l.state]}</span>
                <motion.span className="whitespace-nowrap text-text" initial={reducedMotion ? false : { clipPath: "inset(0 100% 0 0)" }}
                  animate={{ clipPath: "inset(0 0% 0 0)" }} transition={{ duration: 0.32, ease: "linear" }}>
                  {l.label}
                </motion.span>
                <span />
                <span className="truncate text-[11.5px] text-green/45" title={l.detail}>&gt; {l.detail}</span>
              </motion.li>
            ))}
            {shown > lines.length && (
              <motion.li initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="pt-2 tracking-[0.2em] x-phosphor x-cursor">
                {failed ? "ENTERING WITH BACKEND UNAVAILABLE" : "SYSTEM READY"}
              </motion.li>
            )}
          </ol>
          <div className="mt-8 flex flex-wrap items-center justify-between gap-3 text-xs text-muted">
            <span className="font-mono text-[10.5px]">● ready ○ not configured ▲ attention ◌ checking</span>
            <button onClick={() => onDone(status)} className="rounded-[3px] border border-green/30 px-2.5 py-1 font-mono text-[11px] tracking-[0.14em] text-green/80 hover:border-green hover:text-green">
              SKIP INTRO
            </button>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
