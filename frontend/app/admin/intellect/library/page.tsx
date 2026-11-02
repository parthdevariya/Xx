"use client";

import { useRef, useState } from "react";
import { Page, useAction } from "@/components/admin/common";
import { IntellectShell, type VersionFull } from "@/components/admin/intellect";
import { Badge, Button, Empty, ErrorNote, Modal, Notice, Panel, Spinner, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Doc = { id: string; filename: string; description: string; use_for: string; has_content: boolean; executable: boolean };

function DocCard({ d, reload }: { d: Doc; reload: () => void }) {
  const { can } = useAuth();
  const act = useAction();
  const file = useRef<HTMLInputElement>(null);
  const [view, setView] = useState<string | null>(null);
  return (
    <Panel title={<span className="font-mono text-sm normal-case tracking-normal text-text">{d.filename}</span>}
      actions={<Badge tone="amber">Not executable — never loaded into the model</Badge>}>
      <p className="text-sm text-dim">{d.description}</p>
      <p className="mt-2 text-xs text-muted">{d.use_for}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {d.has_content ? <Button size="sm" loading={act.busy === "v"} onClick={async () => { const r = await act.run("v", () => api.get<{ content: string }>(`/intellect/library/${d.id}`)); if (r) setView(r.content); }}>View content</Button>
          : <span className="text-xs text-muted">Content not uploaded yet.</span>}
        {can("intellect.write") && <>
          <input ref={file} type="file" accept=".md,.txt" className="text-xs text-dim file:mr-2 file:rounded file:border file:border-line-strong file:bg-raised file:px-2 file:py-1 file:text-text" />
          <Button size="sm" loading={act.busy === "u"} onClick={() => act.run("u", async () => {
            const f = file.current?.files?.[0];
            if (!f) throw new Error("Choose a .md or .txt file.");
            const form = new FormData();
            form.append("file", f);
            await api.form(`/intellect/library/${d.id}`, form, "PUT");
            reload();
          })}>Upload</Button>
        </>}
      </div>
      <ErrorNote error={act.error} className="mt-2" />
      {view !== null && (
        <Modal open wide onClose={() => setView(null)} title={d.filename}>
          <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap font-mono text-xs text-dim">{view}</pre>
        </Modal>
      )}
    </Panel>
  );
}

function Library({ version }: { version: VersionFull }) {
  const docs = useAsync(() => api.get<Doc[]>(`/intellect/frameworks/${version.framework.id}/library`), [version.framework.id]);
  const planned = version.meta?.planned as { name?: string; note?: string } | undefined;
  return (
    <div className="space-y-4">
      <Notice>Reference material supports study, review, explanation, test development and Human Mode / EFV work. It is not part of X Core, adds no rules, and the pipeline never pastes it into prompts. The database forbids marking it executable.</Notice>
      <ErrorNote error={docs.error} />
      {docs.loading && !docs.data ? <Spinner /> : docs.data?.length ? (
        <div className="grid gap-4 lg:grid-cols-2">{docs.data.map((d) => <DocCard key={d.id} d={d} reload={docs.reload} />)}</div>
      ) : <Empty>No reference documents for this framework.</Empty>}
      {planned?.name && (
        <Panel title={`Planned: ${planned.name}`}>
          <p className="text-sm text-dim">{planned.note}</p>
          <p className="mt-1 text-xs text-muted">X does not create rules, switches or files for planned capabilities.</p>
        </Panel>
      )}
    </div>
  );
}

export default function LibraryPage() {
  return (
    <Page>
      <IntellectShell title="Knowledge & Reference Library" subtitle="The library/ folder from the source framework, kept separate from the executable rules.">
        {({ version }) => <Library version={version} />}
      </IntellectShell>
    </Page>
  );
}
