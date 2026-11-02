"use client";

import { useState } from "react";
import { type Run, RunLink } from "@/components/admin/intellect";
import { Badge, Empty, ErrorNote, PageHeader, Panel, Select, Table, Td, fmtTime, useAsync } from "@/components/ui";
import { api } from "@/lib/api";

export default function LogsPage() {
  const [origin, setOrigin] = useState("");
  const runs = useAsync(() => api.get<Run[]>(`/intellect/runs?limit=200${origin ? `&origin=${origin}` : ""}`), [origin]);
  return (
    <div>
      <PageHeader title="Intellect Execution Logs" subtitle="Every framework run — from executions, the laboratory and regression suites — with its stage-by-stage trace." />
      <Panel title="Runs" actions={<Select className="!h-7 !w-40 text-xs" value={origin} onChange={(e) => setOrigin(e.target.value)} options={[{ value: "", label: "All origins" }, { value: "execution", label: "execution" }, { value: "lab", label: "lab" }, { value: "regression", label: "regression" }]} />}>
        <ErrorNote error={runs.error} />
        {runs.data && (runs.data.length === 0 ? <Empty>No runs yet.</Empty> : (
          <Table head={["Run", "Started", "Origin", "Version", "Status", "Assessment", "Rules applied", "Prompt"]}>
            {runs.data.map((r) => {
              const applied = (r.summary?.rules_applied as string[] | undefined) ?? [];
              return (
                <tr key={r.id}>
                  <Td><RunLink id={r.id} /></Td>
                  <Td className="whitespace-nowrap text-xs">{fmtTime(r.started_at)}</Td>
                  <Td><Badge>{r.origin}</Badge></Td>
                  <Td mono>{r.version}</Td>
                  <Td><Badge tone={r.status === "completed" ? "green" : r.status === "failed" ? "red" : "amber"}>{r.status}</Badge></Td>
                  <Td><Badge tone={r.assessment_mode === "model" ? "green" : r.assessment_mode === "test" ? "red" : "amber"}>{r.assessment_mode.replace("_", " ")}</Badge></Td>
                  <Td mono>{applied.length}</Td>
                  <Td className="max-w-[360px] truncate text-xs text-dim">{r.prompt}</Td>
                </tr>
              );
            })}
          </Table>
        ))}
      </Panel>
    </div>
  );
}
