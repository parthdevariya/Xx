"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type Run, RunViewer } from "@/components/admin/intellect";
import { ErrorNote, PageHeader, Panel, Spinner, fmtTime, useAsync } from "@/components/ui";
import { api } from "@/lib/api";

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const run = useAsync(() => api.get<Run>(`/intellect/runs/${id}`), [id]);
  return (
    <div className="space-y-4">
      <Link href="/admin/intellect/logs" className="text-sm text-cyan hover:underline">← Execution Logs</Link>
      <PageHeader title="Intellect run" subtitle={run.data ? `Started ${fmtTime(run.data.started_at)} · finished ${fmtTime(run.data.finished_at)}` : undefined} />
      <ErrorNote error={run.error} />
      {run.loading && !run.data ? <Spinner /> : run.data && <Panel title="Trace"><RunViewer run={run.data} /></Panel>}
    </div>
  );
}
