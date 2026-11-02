import { api } from "@/lib/api";

export type LabJob = { status: string; error: string; result: Record<string, unknown> | null };

/** Poll a lab/regression background job until it finishes (or the time limit passes). */
export async function pollJob(jobId: string, onTick?: (j: LabJob) => void, limitMs = 20 * 60 * 1000): Promise<LabJob> {
  const start = Date.now();
  for (;;) {
    const j = await api.get<LabJob>(`/intellect/lab/jobs/${jobId}`);
    onTick?.(j);
    if (["done", "failed", "cancelled"].includes(j.status)) return j;
    if (Date.now() - start > limitMs) throw new Error("Timed out waiting for the job; it may still be running. Check Execution Logs.");
    await new Promise((r) => setTimeout(r, 1500));
  }
}
