"use client";

import { Bars, HealthBadge, Stat } from "@/components/admin/common";
import { Empty, ErrorNote, KV, PageHeader, Panel, Spinner, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { MODE_LABELS } from "@/lib/types";

type Dash = {
  users: { total: number; active: number };
  executions: { total: number; by_status: Record<string, number>; by_mode: Record<string, number>; successful: number; failed: number; daily_30d: { date: string; count: number }[] };
  ai: { calls: number; input_tokens: number; output_tokens: number; errors: number };
  quantum: { jobs: number; by_execution_class: Record<string, number>; failed: number };
  scenarios: { published: number; draft: number };
  frameworks: { frameworks: number; versions: number; rules: number };
  providers: { ai: { name: string; active: boolean; health: string }[]; quantum: { name: string; active: boolean; health: string }[] };
  costs: { ai_usd_estimated: number; quantum_usd: number };
  jobs: { queued: number; running: number; failed: number };
};

function Breakdown({ data, labels }: { data: Record<string, number>; labels?: Record<string, string> }) {
  const entries = Object.entries(data);
  if (!entries.length) return <p className="text-sm text-muted">None yet.</p>;
  const total = entries.reduce((s, [, v]) => s + v, 0);
  return (
    <ul className="space-y-1.5">
      {entries.map(([k, v]) => (
        <li key={k} className="text-sm">
          <div className="flex justify-between"><span className="text-dim">{labels?.[k] ?? k.replace(/_/g, " ")}</span><span className="font-mono">{v}</span></div>
          <div className="mt-0.5 h-1 rounded bg-white/5"><div className="h-1 rounded bg-green/60" style={{ width: `${(v / total) * 100}%` }} /></div>
        </li>
      ))}
    </ul>
  );
}

export default function Dashboard() {
  const { data, error, loading } = useAsync(() => api.get<Dash>("/admin/dashboard"));
  return (
    <div>
      <PageHeader title="Dashboard" subtitle="Live counts from the platform database. No figures here are estimated or illustrative except costs marked as estimates." />
      <ErrorNote error={error} />
      {loading && !data ? <Spinner /> : data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Users" value={data.users.total} sub={`${data.users.active} active`} />
            <Stat label="Executions" value={data.executions.total} sub={`${data.executions.successful} completed · ${data.executions.failed} failed`} />
            <Stat label="AI calls" value={data.ai.calls.toLocaleString()} sub={`${(data.ai.input_tokens + data.ai.output_tokens).toLocaleString()} tokens · ${data.ai.errors} errors`} tone="text-ai" />
            <Stat label="Quantum jobs" value={data.quantum.jobs} sub={`${data.quantum.failed} failed`} tone="text-quantum" />
            <Stat label="Scenarios" value={data.scenarios.published} sub={`${data.scenarios.draft} drafts`} />
            <Stat label="Framework versions" value={data.frameworks.versions} sub={`${data.frameworks.frameworks} frameworks · ${data.frameworks.rules} rule records`} tone="text-intellect" />
            <Stat label="AI cost (estimated)" value={`$${data.costs.ai_usd_estimated.toFixed(4)}`} sub="from token usage × configured prices" />
            <Stat label="Quantum cost" value={`$${data.costs.quantum_usd.toFixed(4)}`} sub={`queue: ${data.jobs.queued} queued · ${data.jobs.running} running · ${data.jobs.failed} failed`} />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Panel title="Executions · last 30 days" className="lg:col-span-2">
              {data.executions.daily_30d.length ? (
                <>
                  <Bars data={data.executions.daily_30d.map((d) => ({ label: d.date, value: d.count }))} />
                  <div className="mt-1 flex justify-between font-mono text-[11px] text-muted">
                    <span>{data.executions.daily_30d[0].date}</span><span>{data.executions.daily_30d[data.executions.daily_30d.length - 1].date}</span>
                  </div>
                </>
              ) : <Empty>No executions in the last 30 days.</Empty>}
            </Panel>
            <Panel title="By status"><Breakdown data={data.executions.by_status} /></Panel>
            <Panel title="By mode"><Breakdown data={data.executions.by_mode} labels={MODE_LABELS} /></Panel>
            <Panel title="Quantum jobs by execution class"><Breakdown data={data.quantum.by_execution_class} /></Panel>
            <Panel title="Provider health">
              <div className="space-y-3">
                {(["ai", "quantum"] as const).map((k) => (
                  <div key={k}>
                    <div className="x-label mb-1">{k}</div>
                    <KV items={data.providers[k].map((p) => [p.name, <span key={p.name} className="inline-flex flex-wrap items-center gap-2"><HealthBadge status={p.health} />{!p.active && <span className="text-xs text-muted">inactive</span>}</span>])} />
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
