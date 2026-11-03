"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAction } from "@/components/admin/common";
import { Badge, Button, ErrorNote, Field, Input, Notice, PageHeader, Panel, Spinner, Toggle, cx, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ModeInfo } from "@/lib/types";

type Orch = { default_mode: string; max_cost_usd: number; allow_hardware: boolean; executions_per_user_per_day: number; available_modes: string[] };
type Policy = { id: string; name: string; description: string; is_default: boolean; rules: Record<string, unknown> };

const ENGINE_TONE: Record<string, "cyan" | "blue" | "green" | "neutral"> = { ai: "cyan", quantum: "blue", intellect: "green", classical: "neutral" };
const NEEDS_LABEL: Record<string, string> = { ai: "needs an AI provider", solver: "needs a solver formulation", "solver|ai": "solver or AI" };

const PRESETS: { label: string; pick: (m: ModeInfo[]) => string[] }[] = [
  { label: "All modes", pick: (m) => m.map((x) => x.key) },
  { label: "Intellect showcase", pick: () => ["ai_only", "ai_intellect", "intellect_vs_ai", "classical_intellect", "benchmark"] },
  { label: "Reasoning only", pick: (m) => m.filter((x) => !x.needs.includes("solver")).map((x) => x.key) },
  { label: "Computation only (no AI)", pick: () => ["classical", "quantum", "classical_quantum"] },
];

export default function PoliciesPage() {
  const { can } = useAuth();
  const write = can("policies.write");
  const orch = useAsync(() => api.get<Orch>("/admin/settings/orchestration"));
  const modes = useAsync(() => api.get<ModeInfo[]>("/modes"));
  const routing = useAsync(() => can("ai.read") ? api.get<Policy[]>("/ai/routing-policies") : Promise.resolve([] as Policy[]));
  const act = useAction();
  const [f, setF] = useState<Orch | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (orch.data) setF(orch.data); }, [orch.data]);
  const def = routing.data?.find((p) => p.is_default);

  function toggle(key: string, on: boolean) {
    if (!f || !write) return;
    const next = on ? [...f.available_modes, key] : f.available_modes.filter((m) => m !== key);
    setF({ ...f, available_modes: (modes.data ?? []).map((m) => m.key).filter((k) => next.includes(k)) });
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Orchestration Policies" subtitle="Platform-wide control of which execution modes exist, the default, spend and quotas. Scenario policies can narrow these further." />
      <ErrorNote error={orch.error || modes.error} />
      {!f || !modes.data ? <Spinner /> : (
        <>
          <Panel title={`Execution modes — ${f.available_modes.length} of ${modes.data.length} enabled`}
            actions={write && <div className="flex flex-wrap gap-1.5">{PRESETS.map((p) => (
              <Button key={p.label} size="sm" variant="ghost" onClick={() => setF({ ...f, available_modes: p.pick(modes.data!) })}>{p.label}</Button>
            ))}</div>}>
            <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
              {modes.data.map((m) => {
                const on = f.available_modes.includes(m.key);
                const isDefault = f.default_mode === m.key;
                return (
                  <div key={m.key} className={cx("relative rounded-[3px] border p-3 transition-colors",
                    on ? "border-green/40 bg-green/[0.04]" : "border-line bg-black/30 opacity-70")}>
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-display text-[15px] font-medium text-text">{m.label}</div>
                        <div className="font-mono text-[10.5px] text-muted">{m.key}</div>
                      </div>
                      <Toggle checked={on} disabled={!write || (isDefault && on)} onChange={(v) => toggle(m.key, v)}
                        label={`Enable ${m.label}`} title={isDefault ? "The default mode must stay enabled" : undefined} />
                    </div>
                    <p className="mt-2 text-[12.5px] leading-snug text-dim">{m.description}</p>
                    <div className="mt-2.5 flex flex-wrap items-center gap-1">
                      {m.engines.map((e) => <Badge key={e} tone={ENGINE_TONE[e] ?? "neutral"}>{e}</Badge>)}
                      {m.needs.map((n) => <span key={n} className="ml-1 text-[11px] text-muted">· {NEEDS_LABEL[n] ?? n}</span>)}
                    </div>
                    <div className="mt-2.5">
                      {isDefault ? <Badge tone="green">★ Default mode</Badge> : (
                        <button disabled={!write || !on} onClick={() => setF({ ...f, default_mode: m.key })}
                          className="text-[11.5px] text-dim hover:text-green disabled:cursor-not-allowed disabled:opacity-40">Make default</button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>

          <Panel title="Spend, hardware and quotas">
            <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
              <Field label="Max cost per execution (USD)" hint="Caps any request. 0 allows only free routes (local simulators, classical solvers)."><Input disabled={!write} type="number" min={0} step="0.01" value={f.max_cost_usd} onChange={(e) => setF({ ...f, max_cost_usd: Number(e.target.value) })} /></Field>
              <Field label="Executions per user per day" hint="Administrators are exempt."><Input disabled={!write} type="number" min={1} value={f.executions_per_user_per_day} onChange={(e) => setF({ ...f, executions_per_user_per_day: Number(e.target.value) })} /></Field>
              <div className="flex items-end"><Toggle disabled={!write} checked={f.allow_hardware} onChange={(v) => setF({ ...f, allow_hardware: v })} label="Allow quantum hardware execution" /></div>
            </div>
            <p className="mt-3 text-xs text-muted">Execution timeout is set per deployment (X_EXECUTION_TIMEOUT_S); quantum job limits are set per provider in Quantum Management.</p>
          </Panel>

          <ErrorNote error={act.error} />
          {saved && <Notice tone="ok">Saved.</Notice>}
          {write && <Button variant="primary" loading={act.busy === "s"} onClick={async () => {
            setSaved(false);
            if (!f.available_modes.length) { act.setError(new Error("Enable at least one mode.")); return; }
            if (!f.available_modes.includes(f.default_mode)) { act.setError(new Error("The default mode must be enabled.")); return; }
            const r = await act.run("s", () => api.put<Orch>("/admin/settings/orchestration", f));
            if (r) { setF(r); setSaved(true); }
          }}>Save orchestration policy</Button>}
        </>
      )}
      <Panel title="AI model selection (default routing policy)" actions={<Link href="/admin/ai" className="text-sm text-cyan hover:underline">Edit in AI Management →</Link>}>
        <ErrorNote error={routing.error} />
        {def ? (
          <div className="text-sm">
            <div className="flex items-center gap-2"><span className="font-medium">{def.name}</span><Badge tone="green">default</Badge></div>
            <p className="mt-1 text-dim">{def.description}</p>
            <pre className="mt-2 overflow-x-auto font-mono text-xs text-muted">{JSON.stringify(def.rules, null, 2)}</pre>
          </div>
        ) : <p className="text-sm text-muted">{can("ai.read") ? "No default routing policy." : "You need ai.read to view routing policies."}</p>}
      </Panel>
      <Panel title="Quantum selection policy">
        <p className="text-sm text-dim">The selection engine evaluates 15 factors per problem and returns one of six decisions. It recommends quantum only when cited benefit evidence is on record for the algorithm, problem class and size. Configure evidence and test decisions in <Link href="/admin/quantum" className="text-cyan hover:underline">Quantum Management</Link>.</p>
      </Panel>
    </div>
  );
}
