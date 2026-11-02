"use client";

import Link from "next/link";
import { useState } from "react";
import { Page, useAction } from "@/components/admin/common";
import { IntellectShell, type VersionFull, VersionStatus } from "@/components/admin/intellect";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Button, Empty, ErrorNote, Field, Input, JsonView, Modal, Notice, Panel, Select, Table, Td, fmtTime } from "@/components/ui";

type Report = { ok: boolean; errors: string[]; warnings: string[]; counts?: Record<string, number>; checked_at?: string };
type Diff = {
  from: string; to: string; rules_added: string[]; rules_removed: string[];
  rules_changed: { rule: string; fields: string[]; before: Record<string, unknown>; after: Record<string, unknown> }[];
  layers_added: string[]; layers_removed: string[]; layers_changed: string[]; pipeline_changed: boolean;
};

function ReportView({ r }: { r: Report }) {
  return (
    <div className="space-y-2 text-sm">
      <Notice tone={r.ok ? "ok" : "warn"}>{r.ok ? "Validation passed." : `Validation failed with ${r.errors.length} error(s).`}</Notice>
      {r.errors.length > 0 && <ul className="list-disc space-y-0.5 pl-5 text-red">{r.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}
      {r.warnings.length > 0 && <ul className="list-disc space-y-0.5 pl-5 text-amber">{r.warnings.map((e, i) => <li key={i}>{e}</li>)}</ul>}
      {r.counts && <div className="font-mono text-xs text-muted">{Object.entries(r.counts).map(([k, v]) => `${k}: ${v}`).join(" · ")}</div>}
    </div>
  );
}

function Versions({ version, ctx }: { version: VersionFull; ctx: { reload: () => Promise<void>; select: (id: string) => void; frameworks: { id: string; versions: { id: string; label: string; status: string; created_at: string; published_at: string | null; counts: { rules: number } }[]; active_version: { id: string } | null }[] | null } }) {
  const { can } = useAuth();
  const act = useAction();
  const [report, setReport] = useState<Report | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [cmp, setCmp] = useState({ a: "", b: "" });
  const [diff, setDiff] = useState<Diff | null>(null);
  const fw = ctx.frameworks?.find((f) => f.id === version.framework.id);
  const versions = fw ? [...fw.versions].reverse() : [];
  const vopts = [{ value: "", label: "Select version…" }, ...versions.map((v) => ({ value: v.id, label: `${v.label} (${v.status})` }))];

  async function publish() {
    await act.run("pub", async () => {
      try {
        setReport(await api.post<Report>(`/intellect/versions/${version.id}/publish`));
      } catch (e) {
        if (e instanceof ApiError && e.status === 409 && e.details && typeof e.details === "object" && "errors" in (e.details as object)) {
          setReport(e.details as Report);
        }
        throw e;
      }
    });
    await ctx.reload();
  }

  return (
    <div className="space-y-4">
      <Panel title={`Selected: ${version.framework.name} ${version.label}`}>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <VersionStatus v={version} />{version.framework.is_active_version && <Badge tone="green">active version</Badge>}
          <span className="text-muted">{version.counts.layers} layers · {version.counts.rules} rules · {version.counts.protected} protected</span>
          {version.notes && <span className="text-xs text-dim">— {version.notes}</span>}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button loading={act.busy === "val"} onClick={async () => { const r = await act.run("val", () => api.get<Report>(`/intellect/versions/${version.id}/validate`)); if (r) setReport(r); }}>Validate</Button>
          {version.status === "draft" && can("intellect.write") && <Button variant="primary" loading={act.busy === "sub"} onClick={async () => { const r = await act.run("sub", () => api.post<Report>(`/intellect/versions/${version.id}/submit`)); if (r) setReport(r); await ctx.reload(); }}>Submit for review</Button>}
          {version.status === "in_review" && can("intellect.publish") && <Button variant="primary" loading={act.busy === "pub"} onClick={publish}>Approve & publish</Button>}
          {["draft", "in_review"].includes(version.status) && can("intellect.publish") && <Button variant="danger" onClick={() => setRejecting(true)}>Reject</Button>}
          {["published", "archived"].includes(version.status) && !version.framework.is_active_version && can("intellect.publish") &&
            <Button loading={act.busy === "rb"} onClick={async () => { if (window.confirm(`Make ${version.label} the active version again?`)) { await act.run("rb", () => api.post(`/intellect/frameworks/${version.framework.id}/rollback`, { version_id: version.id })); await ctx.reload(); } }}>Roll back to this version</Button>}
          <Link className="inline-flex items-center text-sm text-cyan hover:underline" href={`/admin/intellect/lab?v=${version.id}`}>Test in lab →</Link>
        </div>
        <ErrorNote error={act.error} className="mt-3" />
        {report && <div className="mt-3"><ReportView r={report} /></div>}
        {!report && Object.keys(version.validation || {}).length > 0 && (
          <div className="mt-3"><div className="x-label mb-1">Last stored validation</div><JsonView value={version.validation} maxHeight={220} /></div>
        )}
      </Panel>

      <Panel title="All versions of this framework">
        {versions.length === 0 ? <Empty>No versions.</Empty> : (
          <Table head={["Label", "Status", "Rules", "Created", "Published", ""]}>
            {versions.map((v) => (
              <tr key={v.id} className={v.id === version.id ? "bg-green/5" : ""}>
                <Td mono>{v.label}{fw?.active_version?.id === v.id && <Badge tone="green" className="ml-2">active</Badge>}</Td>
                <Td><VersionStatus v={v} /></Td><Td mono>{v.counts.rules}</Td>
                <Td className="text-xs">{fmtTime(v.created_at)}</Td><Td className="text-xs">{fmtTime(v.published_at)}</Td>
                <Td><Button size="sm" variant="ghost" onClick={() => { setReport(null); ctx.select(v.id); }}>Select</Button></Td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>

      <Panel title="Compare versions">
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
          <Field label="From"><Select value={cmp.a} onChange={(e) => setCmp({ ...cmp, a: e.target.value })} options={vopts} /></Field>
          <Field label="To"><Select value={cmp.b} onChange={(e) => setCmp({ ...cmp, b: e.target.value })} options={vopts} /></Field>
          <div className="flex items-end"><Button disabled={!cmp.a || !cmp.b} loading={act.busy === "diff"} onClick={async () => { const r = await act.run("diff", () => api.get<Diff>(`/intellect/versions/${cmp.a}/diff/${cmp.b}`)); if (r) setDiff(r); }}>Compare</Button></div>
        </div>
        {diff && (
          <div className="mt-4 space-y-3 text-sm">
            <div className="flex flex-wrap gap-2">
              <Badge tone="green">+{diff.rules_added.length} rules</Badge><Badge tone="red">−{diff.rules_removed.length} rules</Badge>
              <Badge tone="amber">{diff.rules_changed.length} changed</Badge><Badge>layers +{diff.layers_added.length} / −{diff.layers_removed.length} / ~{diff.layers_changed.length}</Badge>
              <Badge tone={diff.pipeline_changed ? "amber" : "neutral"}>pipeline {diff.pipeline_changed ? "changed" : "unchanged"}</Badge>
            </div>
            {diff.rules_added.length > 0 && <div>Added: <span className="font-mono text-green">{diff.rules_added.join(", ")}</span></div>}
            {diff.rules_removed.length > 0 && <div>Removed: <span className="font-mono text-red">{diff.rules_removed.join(", ")}</span></div>}
            {diff.layers_added.length > 0 && <div>Layers added: <span className="font-mono">{diff.layers_added.join(", ")}</span></div>}
            {diff.rules_changed.map((c) => (
              <div key={c.rule} className="rounded border border-line p-2"><span className="font-mono">{c.rule}</span> <span className="text-xs text-muted">{c.fields.join(", ")}</span>
                <JsonView value={{ before: c.before, after: c.after }} maxHeight={160} /></div>
            ))}
            {!diff.rules_added.length && !diff.rules_removed.length && !diff.rules_changed.length && !diff.layers_added.length && !diff.pipeline_changed && <Notice tone="ok">No differences.</Notice>}
          </div>
        )}
      </Panel>

      {rejecting && (
        <Modal open onClose={() => setRejecting(false)} title={`Reject ${version.label}`}>
          <Field label="Reason"><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={() => setRejecting(false)}>Cancel</Button>
            <Button variant="danger" loading={act.busy === "rej"} onClick={async () => { await act.run("rej", () => api.post(`/intellect/versions/${version.id}/reject`, { reason })); setRejecting(false); await ctx.reload(); }}>Reject</Button></div>
        </Modal>
      )}
    </div>
  );
}

export default function VersionsPage() {
  return (
    <Page>
      <IntellectShell title="Version Management" subtitle="Drafts are validated, submitted for review, then approved and published. Publication of a source-derived framework is blocked unless all source rules and guardrails are intact.">
        {(ctx) => <Versions version={ctx.version} ctx={ctx} />}
      </IntellectShell>
    </Page>
  );
}
