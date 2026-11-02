"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import type { Rule } from "@/components/admin/intellect";
import { Badge, Empty, ErrorNote, JsonView, KV, PageHeader, Panel, Spinner, fmtTime, useAsync } from "@/components/ui";
import { api } from "@/lib/api";

type Detail = Rule & {
  source_block: string;
  dependencies: { code: string; kind: string; origin: string; context: string }[];
  referenced_by: { rule_id: string; kind: string; context: string }[];
  history: { action: string; at: string; before: Record<string, unknown>; after: Record<string, unknown>; changed_by: string | null }[];
};

export default function RuleDetail() {
  const { id } = useParams<{ id: string }>();
  const r = useAsync(() => api.get<Detail>(`/intellect/rules/${id}`), [id]);
  if (r.loading && !r.data) return <Spinner />;
  if (r.error) return <ErrorNote error={r.error} />;
  const d = r.data!;
  return (
    <div className="space-y-4">
      <Link href="/admin/intellect/rules" className="text-sm text-cyan hover:underline">← Layers & Rules</Link>
      <PageHeader title={`${d.rule_code} — ${d.layer_name}`} subtitle={
        <span className="flex flex-wrap gap-2">
          <Badge>P{d.priority}</Badge><Badge>{d.provenance}</Badge><Badge tone={d.origin === "source" ? "neutral" : "amber"}>{d.origin}</Badge>
          {d.is_protected && <Badge tone="green">🔒 protected</Badge>}{d.source_marker && <Badge tone="green">{d.source_marker}</Badge>}
          {d.is_active ? <Badge tone="green">active</Badge> : <Badge>inactive</Badge>}
        </span>} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Rule">
          <p className="text-[15px] leading-relaxed">{d.text}</p>
          <div className="mt-4 space-y-3 text-sm">
            <div><div className="x-label mb-1">Applies when</div><p className="text-dim">{d.applies_when || "—"}</p></div>
            <div><div className="x-label mb-1">Not when</div><p className="text-dim">{d.not_when || "—"}</p></div>
          </div>
        </Panel>
        <Panel title="Source">
          <KV items={[["Source page", d.source_page ?? "—"], ["SHA-256", <span key="s" className="break-all font-mono text-xs">{d.source_sha256 || "—"}</span>], ["Revision", d.revision], ["Position", d.position]]} />
          {d.source_block && <><div className="x-label mb-1 mt-4">Extracted source block</div><pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-line bg-bg-2 p-3 font-mono text-[11.5px] text-dim">{d.source_block}</pre></>}
        </Panel>
        <Panel title="Dependencies (cross-references in the rule text)">
          {d.dependencies.length === 0 ? <Empty>None.</Empty> : (
            <ul className="space-y-2 text-sm">{d.dependencies.map((x, i) => <li key={i}><span className="font-mono text-cyan">{x.code}</span> <Badge>{x.kind}</Badge> <span className="text-xs text-muted">{x.origin}</span><p className="text-xs text-dim">{x.context}</p></li>)}</ul>
          )}
          <div className="x-label mb-1 mt-4">Referenced by</div>
          {d.referenced_by.length === 0 ? <p className="text-sm text-muted">No other rule refers to this one.</p> : (
            <ul className="space-y-2 text-sm">{d.referenced_by.map((x, i) => <li key={i}><Link className="font-mono text-cyan hover:underline" href={`/admin/intellect/rules/${x.rule_id}`}>rule</Link> <Badge>{x.kind}</Badge><p className="text-xs text-dim">{x.context}</p></li>)}</ul>
          )}
        </Panel>
        <Panel title="Change history">
          {d.history.length === 0 ? <Empty>No changes recorded in this version.</Empty> : (
            <ul className="space-y-3">{d.history.map((h, i) => <li key={i} className="text-sm"><Badge>{h.action}</Badge> <span className="text-xs text-muted">{fmtTime(h.at)}</span><JsonView value={{ before: h.before, after: h.after }} maxHeight={180} /></li>)}</ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
