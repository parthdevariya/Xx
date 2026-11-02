"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Checks, useAction } from "@/components/admin/common";
import { Badge, Button, ErrorNote, Field, Input, Notice, PageHeader, Panel, Select, Spinner, Toggle, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { MODE_LABELS } from "@/lib/types";

type Orch = { default_mode: string; max_cost_usd: number; allow_hardware: boolean; executions_per_user_per_day: number; available_modes: string[] };
type Policy = { id: string; name: string; description: string; is_default: boolean; rules: Record<string, unknown> };

export default function PoliciesPage() {
  const { can } = useAuth();
  const write = can("policies.write");
  const orch = useAsync(() => api.get<Orch>("/admin/settings/orchestration"));
  const routing = useAsync(() => can("ai.read") ? api.get<Policy[]>("/ai/routing-policies") : Promise.resolve([] as Policy[]));
  const act = useAction();
  const [f, setF] = useState<Orch | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (orch.data) setF(orch.data); }, [orch.data]);
  const def = routing.data?.find((p) => p.is_default);
  return (
    <div className="space-y-4">
      <PageHeader title="Orchestration Policies" subtitle="Platform-wide limits applied to every execution. Scenario policies can narrow these further." />
      <ErrorNote error={orch.error} />
      {!f ? <Spinner /> : (
        <Panel title="Execution policy">
          <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
            <Field label="Default execution mode"><Select disabled={!write} value={f.default_mode} onChange={(e) => setF({ ...f, default_mode: e.target.value })} options={f.available_modes.map((m) => ({ value: m, label: MODE_LABELS[m] ?? m }))} /></Field>
            <Field label="Max cost per execution (USD)" hint="Caps any request. 0 allows only free routes (local simulators, classical solvers)."><Input disabled={!write} type="number" min={0} step="0.01" value={f.max_cost_usd} onChange={(e) => setF({ ...f, max_cost_usd: Number(e.target.value) })} /></Field>
            <Field label="Executions per user per day" hint="Administrators are exempt."><Input disabled={!write} type="number" min={1} value={f.executions_per_user_per_day} onChange={(e) => setF({ ...f, executions_per_user_per_day: Number(e.target.value) })} /></Field>
            <div className="flex items-end"><Toggle disabled={!write} checked={f.allow_hardware} onChange={(v) => setF({ ...f, allow_hardware: v })} label="Allow quantum hardware execution" /></div>
            <div className="sm:col-span-2"><span className="x-label mb-1.5 block">Available modes</span>
              <Checks options={Object.entries(MODE_LABELS).map(([k, l]) => ({ value: k, label: l }))} value={f.available_modes} onChange={(v) => write && setF({ ...f, available_modes: v })} /></div>
          </div>
          <ErrorNote error={act.error} className="mt-3" />
          {saved && <Notice tone="ok" className="mt-3">Saved.</Notice>}
          {write && <Button className="mt-4" variant="primary" loading={act.busy === "s"} onClick={async () => {
            setSaved(false);
            if (!f.available_modes.includes(f.default_mode)) { act.setError(new Error("The default mode must be one of the available modes.")); return; }
            const r = await act.run("s", () => api.put<Orch>("/admin/settings/orchestration", f));
            if (r) { setF(r); setSaved(true); }
          }}>Save policy</Button>}
          <p className="mt-3 text-xs text-muted">Execution timeout and retry limits are set per deployment (X_EXECUTION_TIMEOUT_S); quantum job limits are set per provider in Quantum Management.</p>
        </Panel>
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
