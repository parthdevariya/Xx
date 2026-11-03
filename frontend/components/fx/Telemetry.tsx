"use client";

import { useEffect, useState } from "react";
import { cx } from "@/components/ui";
import { api } from "@/lib/api";

type Dash = {
  executions: { total: number; successful: number; failed: number; by_status: Record<string, number> };
  ai: { calls: number; errors: number };
  quantum: { jobs: number; failed: number };
  jobs: { queued: number; running: number; failed: number };
  providers: { ai: { health: string; active: boolean }[]; quantum: { health: string; active: boolean }[] };
};

function Cell({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "green" | "cyan" | "blue" | "amber" | "red" }) {
  const tones = { green: "text-green", cyan: "text-cyan", blue: "text-blue", amber: "text-amber", red: "text-red" };
  return (
    <div className="flex min-w-[92px] flex-col border-r border-green/10 px-3 py-1.5 last:border-r-0">
      <span className="font-mono text-[9px] tracking-[0.18em] text-green/45">{label}</span>
      <span className={cx("font-mono text-[15px] leading-tight tabular-nums", tone ? tones[tone] : "text-text")}>{value}</span>
    </div>
  );
}

export function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <span className="font-mono text-[12px] tabular-nums tracking-[0.12em] text-green/80" aria-label="System clock">
      {now ? now.toLocaleTimeString(undefined, { hour12: false }) : "--:--:--"}
      <span className="ml-1.5 text-[9.5px] text-green/40">{now ? Intl.DateTimeFormat().resolvedOptions().timeZone : ""}</span>
    </span>
  );
}

/** Live platform telemetry from /api/admin/dashboard, refreshed every 15 s. Shows "—" when unavailable. */
export function TelemetryStrip() {
  const [d, setD] = useState<Dash | null>(null);
  const [ok, setOk] = useState(true);
  useEffect(() => {
    let alive = true;
    const load = () => api.get<Dash>("/admin/dashboard")
      .then((x) => { if (alive) { setD(x); setOk(true); } })
      .catch(() => { if (alive) setOk(false); });
    load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  const v = (x: number | undefined) => (ok && d && x !== undefined ? x.toLocaleString() : "—");
  const health = (list: { health: string; active: boolean }[] | undefined) => {
    if (!ok || !list) return "—";
    const active = list.filter((p) => p.active);
    return `${active.filter((p) => p.health === "healthy").length}/${active.length}`;
  };
  return (
    <div className="flex overflow-x-auto border-b border-green/10 bg-black/60" role="status" aria-label="Platform telemetry">
      <div className="flex items-center gap-1.5 border-r border-green/10 px-3">
        <span className={cx("h-1.5 w-1.5 rounded-full", ok ? "bg-green x-pulse" : "bg-red")} />
        <span className="font-mono text-[9.5px] tracking-[0.2em] text-green/60">{ok ? "TELEMETRY" : "NO SIGNAL"}</span>
      </div>
      <Cell label="EXECUTIONS" value={v(d?.executions.total)} />
      <Cell label="COMPLETED" value={v(d?.executions.successful)} tone="green" />
      <Cell label="FAILED" value={v(d?.executions.failed)} tone={d && d.executions.failed > 0 ? "red" : undefined} />
      <Cell label="RUNNING" value={v(d?.jobs.running)} tone="cyan" />
      <Cell label="QUEUED" value={v(d?.jobs.queued)} />
      <Cell label="AI CALLS" value={v(d?.ai.calls)} tone="cyan" />
      <Cell label="QUANTUM JOBS" value={v(d?.quantum.jobs)} tone="blue" />
      <Cell label="AI HEALTHY" value={health(d?.providers.ai)} />
      <Cell label="QPU/SIM HEALTHY" value={health(d?.providers.quantum)} />
    </div>
  );
}
