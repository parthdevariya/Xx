"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { Page, useAction } from "@/components/admin/common";
import { IntellectShell, type VersionFull } from "@/components/admin/intellect";
import { Badge, Button, Empty, ErrorNote, JsonView, Notice, Panel, Table, Td, fmtTime, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type ImportReport = {
  error?: string; notes?: string[]; extracted_layers?: number; extracted_rules?: number;
  duplicates?: { rule: string; similar_to: string; similarity: number }[];
  layer_mappings?: { rule: string; layer: string; mapping: string }[];
  conflicts?: { rule: string; type: string; detail: string }[];
  suggested_tests?: { name: string; prompt: string; expected: Record<string, unknown> }[];
  source_rule_changes_detected?: string[]; problems?: string[]; added_to_draft?: string[]; skipped?: string[];
  draft_version?: string; activation?: string;
};
type ImportRec = { id: string; filename: string; format: string; status: string; report: ImportReport; draft_version_id: string | null; created_at: string };

function ReportView({ rec }: { rec: { status: string; report: ImportReport; draft_version_id: string | null } }) {
  const r = rec.report;
  if (rec.status === "failed") return <ErrorNote error={r.error ?? "Import failed."} />;
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap gap-2">
        <Badge tone="green">{r.extracted_rules ?? 0} rules extracted</Badge><Badge>{r.extracted_layers ?? 0} layers</Badge>
        <Badge tone="cyan">{r.added_to_draft?.length ?? 0} added to draft</Badge><Badge>{r.skipped?.length ?? 0} skipped</Badge>
        <Badge tone="amber">{r.duplicates?.length ?? 0} possible duplicates</Badge><Badge tone="red">{r.conflicts?.length ?? 0} conflicts</Badge>
      </div>
      {r.activation && <Notice>{r.activation}</Notice>}
      {rec.draft_version_id && <p>Draft version <span className="font-mono">{r.draft_version}</span> — <Link className="text-cyan hover:underline" href={`/admin/intellect/rules?v=${rec.draft_version_id}`}>review and edit rules</Link> · <Link className="text-cyan hover:underline" href={`/admin/intellect/versions?v=${rec.draft_version_id}`}>validate / submit</Link></p>}
      {!!r.notes?.length && <ul className="list-disc pl-5 text-dim">{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      {!!r.source_rule_changes_detected?.length && <Notice tone="warn">Wording differs from these existing source rules: {r.source_rule_changes_detected.join(", ")}. Source rules are not changed by imports.</Notice>}
      {!!r.conflicts?.length && <div><div className="x-label mb-1">Conflicts</div><ul className="space-y-1">{r.conflicts.map((c, i) => <li key={i}><span className="font-mono">{c.rule}</span> <Badge tone="red">{c.type}</Badge> <span className="text-dim">{c.detail}</span></li>)}</ul></div>}
      {!!r.duplicates?.length && <div><div className="x-label mb-1">Possible duplicates</div>
        <Table head={["Imported", "Similar to", "Similarity"]}>{r.duplicates.slice(0, 200).map((d, i) => <tr key={i}><Td mono>{d.rule}</Td><Td mono>{d.similar_to}</Td><Td mono>{d.similarity}</Td></tr>)}</Table></div>}
      {!!r.layer_mappings?.length && <div><div className="x-label mb-1">Layer mappings</div>
        <Table head={["Rule", "Layer", "Mapping"]}>{r.layer_mappings.slice(0, 200).map((m, i) => <tr key={i}><Td mono>{m.rule}</Td><Td mono>{m.layer}</Td><Td className="text-xs">{m.mapping}</Td></tr>)}</Table></div>}
      {!!r.problems?.length && <div><div className="x-label mb-1">Problems to resolve at review</div><ul className="list-disc pl-5 text-amber">{r.problems.map((p, i) => <li key={i}>{p}</li>)}</ul></div>}
      {!!r.suggested_tests?.length && <div><div className="x-label mb-1">Suggested test cases</div><JsonView value={r.suggested_tests} maxHeight={240} /></div>}
    </div>
  );
}

function Builder({ version }: { version: VersionFull }) {
  const { can } = useAuth();
  const act = useAction();
  const file = useRef<HTMLInputElement>(null);
  const [last, setLast] = useState<{ status: string; report: ImportReport; draft_version_id: string | null } | null>(null);
  const imports = useAsync(() => api.get<ImportRec[]>("/intellect/imports"));
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="space-y-4">
      <Panel title={`Import into ${version.framework.name}`}>
        <p className="mb-3 text-sm text-dim">Upload a framework document (PDF, DOCX, TXT, JSON or CSV, up to 10 MB). X extracts layers and rules with their wording preserved, detects duplicates and conflicts, proposes layer mappings and test cases, and saves everything to a new draft. Nothing imported becomes active until an administrator reviews and publishes it. Files are parsed as data and never executed.</p>
        <p className="mb-3 text-xs text-muted">CSV columns: rule_id, text, layer, applies_when, not_when, priority, provenance. JSON: {"{"}&quot;layers&quot;: [...], &quot;rules&quot;: [...]{"}"}.</p>
        {can("intellect.write") ? (
          <div className="flex flex-wrap items-center gap-2">
            <input ref={file} type="file" accept=".pdf,.docx,.txt,.json,.csv" className="text-sm text-dim file:mr-3 file:rounded file:border file:border-line-strong file:bg-raised file:px-3 file:py-1.5 file:text-text" />
            <Button variant="primary" loading={act.busy === "up"} onClick={() => act.run("up", async () => {
              const f = file.current?.files?.[0];
              if (!f) throw new Error("Choose a file first.");
              const form = new FormData();
              form.append("file", f);
              setLast(await api.form<{ status: string; report: ImportReport; draft_version_id: string | null }>(`/intellect/frameworks/${version.framework.id}/imports`, form));
              imports.reload();
            })}>Import</Button>
          </div>
        ) : <Notice tone="warn">Your role cannot import frameworks.</Notice>}
        <ErrorNote error={act.error} className="mt-3" />
        {last && <div className="mt-4"><ReportView rec={last} /></div>}
      </Panel>
      <Panel title="Builder">
        <p className="text-sm text-dim">To build without a document: create a draft in the <Link className="text-cyan hover:underline" href="/admin/intellect">Framework Library</Link>, add custom layers and rules in <Link className="text-cyan hover:underline" href={`/admin/intellect/rules?v=${version.id}`}>Layers & Rules</Link>, order custom stages in <Link className="text-cyan hover:underline" href={`/admin/intellect/pipeline?v=${version.id}`}>Execution Pipeline</Link>, test in the Laboratory, then submit and publish in Versions.</p>
      </Panel>
      <Panel title="Previous imports">
        <ErrorNote error={imports.error} />
        {imports.data && (imports.data.length === 0 ? <Empty>No imports yet.</Empty> : (
          <Table head={["When", "File", "Format", "Status", "Rules", ""]}>
            {imports.data.map((i) => (
              <tr key={i.id}>
                <Td className="text-xs">{fmtTime(i.created_at)}</Td><Td className="break-all">{i.filename}</Td><Td mono>{i.format}</Td>
                <Td><Badge tone={i.status === "draft" ? "amber" : i.status === "failed" ? "red" : "green"}>{i.status}</Badge></Td>
                <Td mono>{i.report.extracted_rules ?? "—"}</Td>
                <Td><Button size="sm" variant="ghost" onClick={() => setOpen(open === i.id ? null : i.id)}>{open === i.id ? "Hide" : "Report"}</Button></Td>
              </tr>
            ))}
          </Table>
        ))}
        {open && imports.data && (() => { const rec = imports.data.find((x) => x.id === open); return rec ? <div className="mt-4"><ReportView rec={rec} /></div> : null; })()}
      </Panel>
    </div>
  );
}

export default function BuilderPage() {
  return (
    <Page>
      <IntellectShell title="Import & Framework Builder" subtitle="Extend X with new frameworks, layers and rules. Custom additions never override protected guardrails or the source hierarchy.">
        {({ version }) => <Builder version={version} />}
      </IntellectShell>
    </Page>
  );
}
