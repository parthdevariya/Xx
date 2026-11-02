"use client";

import Link from "next/link";
import { useState } from "react";
import { Page, useAction } from "@/components/admin/common";
import { type Framework, VersionStatus } from "@/components/admin/intellect";
import { Badge, Button, Empty, ErrorNote, Field, Input, Modal, PageHeader, Panel, Select, Spinner, Table, Td, Textarea, fmtTime, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function Library() {
  const { can } = useAuth();
  const write = can("intellect.write");
  const fws = useAsync(() => api.get<Framework[]>("/intellect/frameworks"));
  const [creating, setCreating] = useState(false);
  const [draftFrom, setDraftFrom] = useState<{ id: string; label: string } | null>(null);
  return (
    <div>
      <PageHeader title="Framework Library"
        subtitle="The Intellect Engine runs frameworks stored as data. X Layers v0.3B is imported verbatim from the source PDF: 10 layers, 93 rules, 13 execution stages, 10 protected guardrails."
        actions={write && <Button variant="primary" onClick={() => setCreating(true)}>New framework</Button>} />
      <ErrorNote error={fws.error} />
      {fws.loading && !fws.data ? <Spinner /> : (
        <div className="space-y-4">
          {fws.data?.map((f) => (
            <Panel key={f.id} title={<span className="flex items-center gap-2 normal-case tracking-normal"><span className="font-display text-sm text-text">{f.name}</span><Badge>{f.slug}</Badge>{f.source_pack && <Badge tone="green" title="Publication requires the source rules intact">source: {f.source_pack}</Badge>}</span>}>
              <p className="mb-3 text-sm text-dim">{f.description}</p>
              <Table head={["Version", "Status", "Layers", "Rules", "Protected", "Created", "Published", ""]}>
                {[...f.versions].reverse().map((v) => (
                  <tr key={v.id}>
                    <Td mono>{v.label}{f.active_version?.id === v.id && <Badge tone="green" className="ml-2">active</Badge>}</Td>
                    <Td><VersionStatus v={v} /></Td>
                    <Td mono>{v.counts.layers}</Td><Td mono>{v.counts.rules}</Td><Td mono>{v.counts.protected}</Td>
                    <Td className="text-xs">{fmtTime(v.created_at)}</Td><Td className="text-xs">{fmtTime(v.published_at)}</Td>
                    <Td className="whitespace-nowrap">
                      <Link className="mr-3 text-sm text-cyan hover:underline" href={`/admin/intellect/rules?v=${v.id}`}>Open</Link>
                      <Link className="mr-3 text-sm text-cyan hover:underline" href={`/admin/intellect/versions?v=${v.id}`}>Manage</Link>
                      {write && <Button size="sm" variant="ghost" onClick={() => setDraftFrom({ id: v.id, label: v.label })}>Create draft</Button>}
                    </Td>
                  </tr>
                ))}
              </Table>
            </Panel>
          ))}
          {fws.data?.length === 0 && <Empty>No frameworks.</Empty>}
        </div>
      )}
      {creating && fws.data && <CreateFramework frameworks={fws.data} onClose={() => setCreating(false)} onDone={() => { setCreating(false); fws.reload(); }} />}
      {draftFrom && <CreateDraft from={draftFrom} onClose={() => setDraftFrom(null)} onDone={() => { setDraftFrom(null); fws.reload(); }} />}
    </div>
  );
}

function CreateFramework({ frameworks, onClose, onDone }: { frameworks: Framework[]; onClose: () => void; onDone: () => void }) {
  const act = useAction();
  const [f, setF] = useState({ name: "", slug: "", description: "", from: "" });
  const opts = [{ value: "", label: "Blank framework (no layers)" }, ...frameworks.flatMap((fw) => fw.versions.map((v) => ({ value: v.id, label: `Duplicate ${fw.name} ${v.label}` })))];
  return (
    <Modal open onClose={onClose} title="New framework">
      <div className="space-y-3">
        <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value, slug: f.slug || e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") })} /></Field>
        <Field label="Slug"><Input value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value })} /></Field>
        <Field label="Description"><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="Starting point" hint="Duplicates of a source-derived framework keep source integrity checks and protected guardrails."><Select value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} options={opts} /></Field>
        <ErrorNote error={act.error} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={act.busy === "c"} onClick={() => act.run("c", async () => {
            await api.post("/intellect/frameworks", { name: f.name, slug: f.slug, description: f.description, duplicate_from_version_id: f.from || null }); onDone();
          })}>Create</Button></div>
      </div>
    </Modal>
  );
}

function CreateDraft({ from, onClose, onDone }: { from: { id: string; label: string }; onClose: () => void; onDone: () => void }) {
  const act = useAction();
  const [label, setLabel] = useState(`${from.label}-draft`);
  const [notes, setNotes] = useState("");
  return (
    <Modal open onClose={onClose} title={`Create draft from ${from.label}`}>
      <div className="space-y-3">
        <Field label="Draft label"><Input value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
        <Field label="Notes"><Textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        <ErrorNote error={act.error} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={act.busy === "d"} onClick={() => act.run("d", async () => { await api.post(`/intellect/versions/${from.id}/drafts`, { label, notes }); onDone(); })}>Create draft</Button></div>
      </div>
    </Modal>
  );
}

export default function FrameworkLibraryPage() {
  return <Page><Library /></Page>;
}
