"use client";

import { Page } from "@/components/admin/common";
import { IntellectShell, RunLink, type VersionFull } from "@/components/admin/intellect";
import { Badge, Empty, ErrorNote, Panel, Table, Td, useAsync } from "@/components/ui";
import { api } from "@/lib/api";

type Conflict = { run_id: string; stage: number; rules: string[]; layers: string[]; description: string; hierarchy_step: string; winner: string; decision: string; detected_by: string };

function Conflicts({ version }: { version: VersionFull }) {
  const list = useAsync(() => api.get<Conflict[]>("/intellect/conflicts?limit=200"));
  return (
    <div className="space-y-4">
      <Panel title="Resolution hierarchy (higher wins)">
        <ol className="space-y-2">
          {version.hierarchy.map((h) => (
            <li key={h.rank} className="flex items-start gap-3 text-sm">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-green/40 font-mono text-xs text-green">{h.rank}</span>
              <div><div>{h.raw}</div>{h.layers.length > 0 && <div className="mt-0.5 flex gap-1">{h.layers.map((l) => <Badge key={l}>{l}</Badge>)}</div>}
                {h.rank === 1 && <div className="mt-0.5 text-xs text-muted">Protected guardrails ({version.guardrails.map((g) => g.rule_code).join(", ")})</div>}</div>
            </li>
          ))}
        </ol>
        {version.hierarchy_note && <p className="mt-4 border-t border-line pt-3 text-sm text-amber">{version.hierarchy_note}</p>}
        <p className="mt-2 text-xs text-muted">Within a rank, the lower P number applies first. An exact tie goes to the judgment stage (VL). Custom layers sit in ranks 2–6 only.</p>
      </Panel>
      <Panel title="Recorded conflicts (all runs)">
        <ErrorNote error={list.error} />
        {list.data && (list.data.length === 0 ? <Empty>No conflicts recorded yet. Conflicts appear when a stage reports rules pulling in different directions, or when two rules with a source-declared override both apply.</Empty> : (
          <Table head={["Rules", "Layers", "Description", "Step applied", "Winner", "Decision", "Detected", "Run"]}>
            {list.data.map((c, i) => (
              <tr key={i}>
                <Td mono className="whitespace-nowrap">{c.rules.join(" vs ")}</Td>
                <Td className="text-xs">{c.layers.join(", ")}</Td>
                <Td className="max-w-[260px] text-xs text-dim">{c.description}</Td>
                <Td className="max-w-[200px] text-xs">{c.hierarchy_step}</Td>
                <Td><Badge tone="green">{c.winner}</Badge></Td>
                <Td className="max-w-[260px] text-xs text-dim">{c.decision}</Td>
                <Td><Badge>{c.detected_by}</Badge></Td>
                <Td><RunLink id={c.run_id} /></Td>
              </tr>
            ))}
          </Table>
        ))}
      </Panel>
    </div>
  );
}

export default function ConflictsPage() {
  return (
    <Page>
      <IntellectShell title="Conflict Resolution" subtitle="Deterministic resolution under the source-defined hierarchy. HM, EFV and settings may change how something is said, never what is true, right or decided.">
        {({ version }) => <Conflicts version={version} />}
      </IntellectShell>
    </Page>
  );
}
