"use client";

import { Fragment, useState } from "react";
import { Badge, Button, Empty, ErrorNote, Field, Input, JsonView, PageHeader, Panel, Select, Spinner, Table, Td, fmtTime, useAsync } from "@/components/ui";
import { api } from "@/lib/api";

type Entry = { id: string; at: string; actor: string; category: string; action: string; target_type: string; target_id: string; outcome: string; detail: Record<string, unknown>; ip: string };
const CATEGORIES = ["auth", "security", "config", "provider", "framework", "rule", "scenario", "execution", "admin"];

export default function AuditPage() {
  const [category, setCategory] = useState("");
  const [outcome, setOutcome] = useState("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const params = new URLSearchParams({ limit: "300" });
  if (category) params.set("category", category);
  if (outcome) params.set("outcome", outcome);
  if (query) params.set("q", query);
  const logs = useAsync(() => api.get<Entry[]>(`/admin/audit?${params.toString()}`), [category, outcome, query]);
  return (
    <div>
      <PageHeader title="Audit Log" subtitle="Configuration, provider, framework, rule, scenario, execution, authentication and security events. Secrets are redacted before storage." />
      <Panel title="Filters" className="mb-4">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); setQuery(q); }}>
          <Field label="Category" className="w-40"><Select value={category} onChange={(e) => setCategory(e.target.value)} options={[{ value: "", label: "All" }, ...CATEGORIES.map((c) => ({ value: c, label: c }))]} /></Field>
          <Field label="Outcome" className="w-36"><Select value={outcome} onChange={(e) => setOutcome(e.target.value)} options={[{ value: "", label: "All" }, { value: "success", label: "success" }, { value: "denied", label: "denied" }, { value: "failed", label: "failed" }]} /></Field>
          <Field label="Search" className="min-w-48 flex-1"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="action, actor, target" /></Field>
          <Button type="submit">Search</Button>
        </form>
      </Panel>
      <ErrorNote error={logs.error} />
      {logs.loading && !logs.data ? <Spinner /> : logs.data && (logs.data.length === 0 ? <Empty>No matching events.</Empty> : (
        <Table head={["Time", "Actor", "Category", "Action", "Target", "Outcome", "IP", ""]}>
          {logs.data.map((e) => (
            <Fragment key={e.id}>
              <tr>
                <Td className="whitespace-nowrap text-xs">{fmtTime(e.at)}</Td>
                <Td className="text-xs">{e.actor || <span className="text-muted">system / anonymous</span>}</Td>
                <Td><Badge>{e.category}</Badge></Td>
                <Td mono>{e.action}</Td>
                <Td className="text-xs text-dim">{e.target_type}{e.target_id && <span className="font-mono"> {e.target_id.slice(0, 12)}</span>}</Td>
                <Td><Badge tone={e.outcome === "success" ? "green" : "red"}>{e.outcome}</Badge></Td>
                <Td mono className="text-xs">{e.ip}</Td>
                <Td><Button size="sm" variant="ghost" aria-expanded={open === e.id} onClick={() => setOpen(open === e.id ? null : e.id)}>{open === e.id ? "Hide" : "Detail"}</Button></Td>
              </tr>
              {open === e.id && <tr><td colSpan={8} className="px-3 pb-3"><JsonView value={e.detail} maxHeight={260} /></td></tr>}
            </Fragment>
          ))}
        </Table>
      ))}
    </div>
  );
}
