"use client";

import { Page, useAction } from "@/components/admin/common";
import { IntellectShell, type VersionFull } from "@/components/admin/intellect";
import { Badge, Button, cx, ErrorNote, Panel } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function PipelineView({ version, reload }: { version: VersionFull; reload: () => void }) {
  const { can } = useAuth();
  const editable = can("intellect.write") && version.status === "draft";
  const act = useAction();
  const layers = Object.fromEntries(version.layers.map((l) => [l.code, l]));
  const counts = Object.fromEntries(version.layers.map((l) => [l.code, version.rules.filter((r) => r.layer === l.code).length]));
  const seq = version.meta?.sequence_text as string | undefined;
  async function move(from: number, to: number) {
    await act.run("m", () => api.post(`/intellect/versions/${version.id}/pipeline/move`, { from_position: from, to_position: to }));
    reload();
  }
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Panel title={`Execution sequence — ${version.pipeline.length} stages`}>
        <ErrorNote error={act.error} className="mb-3" />
        <ol className="relative space-y-2 before:absolute before:bottom-4 before:left-[15px] before:top-4 before:w-px before:bg-line-strong">
          {version.pipeline.map((s, i) => {
            const custom = (s.origin ?? "source") !== "source";
            const l = layers[s.layer];
            return (
              <li key={s.position} className={cx("relative flex items-start gap-3", !!s.bound_to && "pl-6")}>
                <span className={cx("z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border font-mono text-xs",
                  custom ? "border-amber/60 bg-amber/10 text-amber" : s.layer === "EFV" ? "border-cyan/50 bg-bg text-cyan" : "border-green/50 bg-bg text-green")}>{s.position}</span>
                <div className="x-panel min-w-0 flex-1 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm text-intellect">{s.layer}</span>
                    <span className="text-sm">{l?.name}</span>
                    <Badge>{s.mode.replace("_", " ")}</Badge>
                    {s.bound_to && <Badge tone="cyan">bound to stage {s.bound_to} ({version.pipeline.find((x) => x.position === s.bound_to)?.source_label})</Badge>}
                    {custom ? <Badge tone="amber">custom</Badge> : <Badge>source</Badge>}
                    <span className="ml-auto font-mono text-[11px] text-muted">{counts[s.layer] ?? 0} rules · tier {l?.tier}</span>
                  </div>
                  <div className="mt-0.5 font-mono text-[11px] text-muted">{s.source_label}</div>
                  {editable && custom && (
                    <div className="mt-2 flex gap-2">
                      <Button size="sm" disabled={i === 0} onClick={() => move(s.position, s.position - 1)}>↑ Move up</Button>
                      <Button size="sm" disabled={i === version.pipeline.length - 1} onClick={() => move(s.position, s.position + 1)}>↓ Move down</Button>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </Panel>
      <div className="space-y-4">
        {seq && <Panel title="Source-defined order"><p className="font-mono text-sm leading-relaxed text-green">{seq}</p></Panel>}
        <Panel title="How it runs">
          <ul className="list-disc space-y-2 pl-4 text-sm text-dim">
            <li>Stages run strictly in this order, one model call each; they never run in parallel.</li>
            <li>Each stage receives the verbatim text of its layer&apos;s rules from the database, the problem, and earlier stage outputs.</li>
            <li>EFV runs inside Human Mode: it picks the delivery preset after HM reads the person, and applies it after HM speaks.</li>
            <li>Source stages keep their order. Custom stages can be inserted and moved in drafts only.</li>
            <li>Switching a layer off skips its stage, except that protected rules in that layer still run.</li>
            <li>After the last stage, a separate guardrail audit checks the final reply against the 10 protected rules.</li>
          </ul>
        </Panel>
      </div>
    </div>
  );
}

export default function PipelinePage() {
  return (
    <Page>
      <IntellectShell title="Execution Pipeline" subtitle="The stored execution sequence of the selected framework version.">
        {({ version, reload }) => <PipelineView version={version} reload={reload} />}
      </IntellectShell>
    </Page>
  );
}
