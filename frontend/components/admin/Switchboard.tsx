"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { cx } from "@/components/ui";
import { api } from "@/lib/api";

type Switches = {
  ai: boolean; intellect: boolean; quantum: boolean; swarm: boolean; guardrail_audit: boolean;
  layers: Record<string, boolean>; swarm_config: { agents: number; rounds: number };
};
type Layer = { code: string; name: string; question: string; protected_rules: string[] };

const COLORS = { ai: "#45d9f5", intellect: "#3cf59a", quantum: "#7c8cff", swarm: "#f5c542" };

function Power({ on, color, label, sub, disabled, onToggle, busy }: {
  on: boolean; color: string; label: string; sub?: string; disabled?: boolean; onToggle: () => void; busy?: boolean;
}) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={`${label} ${on ? "on" : "off"}`} disabled={disabled}
      onClick={onToggle}
      className={cx("group flex items-center gap-2.5 rounded-[3px] border px-2.5 py-1.5 transition-all disabled:cursor-not-allowed",
        on ? "bg-black/60" : "border-line bg-black/30 opacity-80")}
      style={on ? { borderColor: `${color}88`, boxShadow: `0 0 16px -6px ${color}, inset 0 0 12px -8px ${color}` } : undefined}>
      <span className="relative h-5 w-9 rounded-full border transition-colors"
        style={{ borderColor: on ? color : "rgba(140,255,200,0.2)", background: on ? `${color}33` : "transparent" }}>
        <motion.span className="absolute top-[2px] h-3.5 w-3.5 rounded-full"
          animate={{ left: on ? 18 : 2, backgroundColor: on ? color : "#4b5651" }} transition={{ type: "spring", stiffness: 500, damping: 30 }}
          style={on ? { boxShadow: `0 0 8px ${color}` } : undefined} />
      </span>
      <span className="text-left leading-tight">
        <span className="block font-mono text-[10.5px] tracking-[0.2em]" style={{ color: on ? color : "#64716b" }}>{label}</span>
        <span className="block font-mono text-[9px] tracking-[0.15em] text-muted">{busy ? "SYNCING…" : sub ?? (on ? "ONLINE" : "OFFLINE")}</span>
      </span>
    </button>
  );
}

/** Master Control engine switchboard: one row, always visible on every admin page. */
export function Switchboard() {
  const [sw, setSw] = useState<Switches | null>(null);
  const [layers, setLayers] = useState<Layer[]>([]);
  const [canEdit, setCanEdit] = useState(false);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const panel = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    api.get<{ switches: Switches; can_edit: boolean; layers: Layer[] }>("/engine-switches")
      .then((r) => { setSw(r.switches); setCanEdit(r.can_edit); setLayers(r.layers); })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!panel.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  async function save(key: string, change: Partial<Switches>) {
    if (!sw || !canEdit) return;
    const prev = sw;
    setSw({ ...sw, ...change, layers: { ...sw.layers, ...(change.layers ?? {}) }, swarm_config: { ...sw.swarm_config, ...(change.swarm_config ?? {}) } });
    setBusy(key);
    setError(null);
    try {
      setSw(await api.put<Switches>("/admin/engine-switches", change));
    } catch (e) {
      setSw(prev);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  if (!sw) return <div className="px-4 py-2 font-mono text-[10px] tracking-[0.2em] text-muted">{error ? `SWITCHBOARD — ${error}` : "SWITCHBOARD — CONNECTING…"}</div>;
  const layerOn = (c: string) => sw.layers[c] !== false;
  const layersOff = layers.filter((l) => !layerOn(l.code)).length;

  return (
    <div className="relative flex flex-wrap items-center gap-2 border-t border-green/10 px-4 py-2" ref={panel}>
      <span className="mr-1 font-mono text-[10px] tracking-[0.22em] text-green/70">● ENGINE SWITCHBOARD</span>
      <Power on={sw.ai} color={COLORS.ai} label="AI" disabled={!canEdit} busy={busy === "ai"} onToggle={() => save("ai", { ai: !sw.ai })} />
      <div className="flex items-stretch">
        <Power on={sw.intellect} color={COLORS.intellect} label="INTELLECT" disabled={!canEdit} busy={busy === "intellect"}
          sub={sw.intellect ? `${layers.length - layersOff}/${layers.length} LAYERS${sw.swarm ? " · SWARM" : ""}` : "OFFLINE"}
          onToggle={() => save("intellect", { intellect: !sw.intellect })} />
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Intellect sub-sections"
          className="-ml-px rounded-r-[3px] border border-green/30 px-2 font-mono text-[10px] text-green/80 hover:bg-green/10">{open ? "▲" : "▼"}</button>
      </div>
      <Power on={sw.quantum} color={COLORS.quantum} label="QUANTUM" disabled={!canEdit} busy={busy === "quantum"} onToggle={() => save("quantum", { quantum: !sw.quantum })} />
      <Power on={sw.swarm} color={COLORS.swarm} label="SWARM" sub={sw.swarm ? `${sw.swarm_config.agents} AGENTS · ${sw.swarm_config.rounds} RNDS` : "OFFLINE"}
        disabled={!canEdit || !sw.intellect} busy={busy === "swarm"} onToggle={() => save("swarm", { swarm: !sw.swarm })} />
      {!canEdit && <span className="font-mono text-[9.5px] tracking-[0.15em] text-muted">READ-ONLY · needs policies.write</span>}
      {error && <span className="text-xs text-red">{error}</span>}

      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
            className="x-panel absolute left-4 right-4 top-full z-40 mt-1 max-w-4xl p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <span className="font-mono text-[10.5px] tracking-[0.22em] text-green">INTELLECT {"//"} SUB-SECTIONS</span>
              <span className="text-[11px] text-muted">Protected guardrails keep running even when their layer is off.</span>
            </div>
            <div className="mb-3 grid gap-2 sm:grid-cols-2">
              <div className="rounded-[3px] border p-2.5" style={{ borderColor: `${COLORS.swarm}55` }}>
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="font-mono text-[11px] tracking-[0.18em]" style={{ color: COLORS.swarm }}>SWARM INTELLIGENCE</div>
                    <div className="text-[11px] text-muted">Graph → personas → dual-platform simulation → ReportAgent → chat</div>
                  </div>
                  <Power on={sw.swarm} color={COLORS.swarm} label="SWARM" disabled={!canEdit || !sw.intellect} onToggle={() => save("swarm", { swarm: !sw.swarm })} />
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-dim">
                  <label className="flex items-center gap-1.5">Agents
                    <input type="number" min={4} max={40} disabled={!canEdit} value={sw.swarm_config.agents}
                      onChange={(e) => setSw({ ...sw, swarm_config: { ...sw.swarm_config, agents: Number(e.target.value) } })}
                      onBlur={(e) => save("cfg", { swarm_config: { ...sw.swarm_config, agents: Number(e.target.value) } })}
                      className="w-14 rounded-[2px] border border-line bg-black/50 px-1.5 py-0.5 font-mono text-text" /></label>
                  <label className="flex items-center gap-1.5">Rounds
                    <input type="number" min={1} max={10} disabled={!canEdit} value={sw.swarm_config.rounds}
                      onChange={(e) => setSw({ ...sw, swarm_config: { ...sw.swarm_config, rounds: Number(e.target.value) } })}
                      onBlur={(e) => save("cfg", { swarm_config: { ...sw.swarm_config, rounds: Number(e.target.value) } })}
                      className="w-14 rounded-[2px] border border-line bg-black/50 px-1.5 py-0.5 font-mono text-text" /></label>
                  <span className="text-muted">≈ {4 + 2 * sw.swarm_config.rounds} model calls per run</span>
                </div>
              </div>
              <div className="flex items-center justify-between gap-2 rounded-[3px] border border-line p-2.5">
                <div>
                  <div className="font-mono text-[11px] tracking-[0.18em] text-green">GUARDRAIL AUDIT</div>
                  <div className="text-[11px] text-muted">Post-sequence check of the final reply against the 10 protected rules. Switching it off does not disable the rules.</div>
                </div>
                <Power on={sw.guardrail_audit} color={COLORS.intellect} label="AUDIT" disabled={!canEdit} onToggle={() => save("audit", { guardrail_audit: !sw.guardrail_audit })} />
              </div>
            </div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="x-label">X Layers — {layers.length - layersOff} of {layers.length} on</span>
              {canEdit && <span className="flex gap-2 text-[11px]">
                <button className="text-dim hover:text-green" onClick={() => save("layers", { layers: Object.fromEntries(layers.map((l) => [l.code, true])) })}>All on</button>
              </span>}
            </div>
            <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-5">
              {layers.map((l) => {
                const on = layerOn(l.code);
                return (
                  <button key={l.code} type="button" role="switch" aria-checked={on} disabled={!canEdit}
                    onClick={() => save(`layer-${l.code}`, { layers: { [l.code]: !on } })} title={l.question}
                    className={cx("rounded-[3px] border p-2 text-left transition-all disabled:cursor-not-allowed",
                      on ? "border-green/45 bg-green/[0.06] shadow-[0_0_12px_-6px_rgba(60,245,154,0.9)]" : "border-line bg-black/30 opacity-70")}>
                    <div className="flex items-center justify-between">
                      <span className={cx("font-mono text-sm", on ? "text-green" : "text-muted")}>{l.code}</span>
                      <span className={cx("h-2 w-2 rounded-full", on ? "bg-green shadow-[0_0_6px_rgba(60,245,154,0.9)]" : "bg-muted")} />
                    </div>
                    <div className="truncate text-[11px] text-dim">{l.name}</div>
                    {l.protected_rules.length > 0 && <div className="mt-0.5 truncate font-mono text-[9px] text-amber/80" title={l.protected_rules.join(", ")}>🔒 {l.protected_rules.join(" ")}</div>}
                  </button>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
