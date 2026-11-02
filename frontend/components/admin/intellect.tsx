"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, cx, Empty, ErrorNote, JsonView, Select, Spinner, StatusDot } from "@/components/ui";
import { api } from "@/lib/api";

// ------------------------------------------------------------------ types

export type VersionSummary = {
  id: string; label: string; status: string; parent_version_id: string | null; created_at: string;
  published_at: string | null; notes: string; counts: { layers: number; rules: number; protected: number };
  validation: Record<string, unknown>;
};
export type Framework = {
  id: string; slug: string; name: string; description: string; source_pack: string;
  active_version: VersionSummary | null; versions: VersionSummary[];
};
export type Rule = {
  id: string; rule_code: string; layer: string; layer_name: string; text: string; applies_when: string; not_when: string;
  priority: number; provenance: string; source_marker: string | null; is_protected: boolean; is_active: boolean;
  origin: string; position: number; source_page: number | null; source_sha256: string; revision: number; editable: boolean;
};
export type Layer = {
  id: string; code: string; name: string; question: string; description: string; tier: number; tier_basis: string;
  origin: string; enabled_by_default: boolean; position: number; declared_rule_count: number | null; rule_count: number;
  protected_count: number; source_page: number | null;
};
export type Stage = { position: number; layer: string; mode: string; source_label: string; bound_to: number | null; origin?: string };
export type HierarchyItem = { rank: number; label: string; layers: string[]; raw: string };
export type VersionFull = VersionSummary & {
  framework: { id: string; name: string; slug: string; source_pack: string; is_active_version: boolean };
  pipeline: Stage[]; hierarchy: HierarchyItem[]; hierarchy_note: string; meta: Record<string, unknown>;
  layers: Layer[]; rules: Rule[];
  guardrails: { rule_code: string; kind: string; source_basis: string }[];
  evidence_legend: { code: string; meaning: string }[];
};
export type RuleState = { rule: string; state: string; reason: string };
export type RunStage = {
  position: number; layer: string; mode: string; status: string; rule_states: RuleState[]; output: string;
  data: Record<string, unknown>; model: string; latency_ms: number;
};
export type Run = {
  id: string; started_at: string; finished_at: string | null; version: string | null; version_id: string; origin: string;
  status: string; assessment_mode: string; prompt: string; execution_id: string | null;
  layer_switches: Record<string, unknown>; summary: Record<string, unknown>; error: string;
  final_output?: string; stages?: RunStage[];
  conflicts?: { stage: number; rules: string[]; layers: string[]; description: string; hierarchy_step: string; winner: string; decision: string; detected_by: string }[];
};

// ------------------------------------------------------------------ version selection (?v=)

export function useIntellectVersion() {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const vParam = params.get("v");
  const [frameworks, setFrameworks] = useState<Framework[] | null>(null);
  const [version, setVersion] = useState<VersionFull | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const loadFrameworks = useCallback(async () => {
    try {
      setFrameworks(await api.get<Framework[]>("/intellect/frameworks"));
    } catch (e) {
      setError(e);
    }
  }, []);

  useEffect(() => {
    loadFrameworks();
  }, [loadFrameworks]);

  const versionId = useMemo(() => {
    if (vParam) return vParam;
    if (!frameworks) return null;
    const fw = frameworks.find((f) => f.slug === "x-layers") ?? frameworks[0];
    return fw?.active_version?.id ?? fw?.versions[fw.versions.length - 1]?.id ?? null;
  }, [vParam, frameworks]);

  const reload = useCallback(async () => {
    if (!versionId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setVersion(await api.get<VersionFull>(`/intellect/versions/${versionId}`));
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [versionId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const select = useCallback((id: string) => {
    const q = new URLSearchParams(params.toString());
    q.set("v", id);
    router.replace(`${path}?${q.toString()}`);
  }, [params, router, path]);

  const reloadAll = useCallback(async () => {
    await loadFrameworks();
    await reload();
  }, [loadFrameworks, reload]);

  return { frameworks, version, versionId, error, loading, reload: reloadAll, select };
}

export function VersionPicker({ frameworks, versionId, onSelect }: {
  frameworks: Framework[] | null; versionId: string | null; onSelect: (id: string) => void;
}) {
  if (!frameworks) return <Spinner small />;
  const options = frameworks.flatMap((f) =>
    f.versions.map((v) => ({
      value: v.id,
      label: `${f.name} · ${v.label} · ${v.status}${f.active_version?.id === v.id ? " (active)" : ""}`,
    })));
  return (
    <div className="w-full max-w-md">
      <label className="x-label mb-1 block" htmlFor="ver-pick">Framework version</label>
      <Select id="ver-pick" value={versionId ?? ""} onChange={(e) => onSelect(e.target.value)} options={options} />
    </div>
  );
}

export function versionQuery(v: { id: string } | null) {
  return v ? `?v=${v.id}` : "";
}

export function VersionStatus({ v }: { v: { status: string; label: string } }) {
  const tone = v.status === "published" ? "green" : v.status === "draft" ? "amber" : v.status === "in_review" ? "cyan" : v.status === "rejected" ? "red" : "neutral";
  return <Badge tone={tone}>{v.status.replace("_", " ")}</Badge>;
}

export function IntellectShell({ children, title, subtitle, actions }: {
  children: (ctx: ReturnType<typeof useIntellectVersion> & { version: VersionFull }) => React.ReactNode;
  title: string; subtitle?: React.ReactNode; actions?: (v: VersionFull) => React.ReactNode;
}) {
  const ctx = useIntellectVersion();
  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1 max-w-3xl text-sm text-dim">{subtitle}</p>}
        </div>
        <div className="flex flex-wrap items-end gap-3">
          {ctx.version && actions?.(ctx.version)}
          <VersionPicker frameworks={ctx.frameworks} versionId={ctx.versionId} onSelect={ctx.select} />
        </div>
      </div>
      <ErrorNote error={ctx.error} className="mb-4" />
      {ctx.loading && !ctx.version ? <Spinner /> : ctx.version ? (
        <>
          {ctx.version.status !== "published" && (
            <div className="mb-4 flex items-center gap-2 rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-sm text-amber">
              <StatusDot status={ctx.version.status} /> You are viewing {ctx.version.label} ({ctx.version.status.replace("_", " ")}).
              {ctx.version.status === "draft" ? " Custom content can be edited here; source and protected rules stay read-only." : " It is not editable."}
            </div>
          )}
          {children({ ...ctx, version: ctx.version })}
        </>
      ) : <Empty>No framework version found.</Empty>}
    </div>
  );
}

// ------------------------------------------------------------------ run viewer

const STATE_STYLE: Record<string, string> = {
  applied: "border-green/40 bg-green/10 text-green",
  not_applicable: "border-line-strong text-dim",
  not_assessed: "border-amber/40 bg-amber/10 text-amber",
  disabled: "border-line text-muted line-through",
};

export function RuleStateChip({ s }: { s: RuleState }) {
  return (
    <span title={`${s.state.replace("_", " ")}: ${s.reason}`}
      className={cx("inline-flex rounded border px-1.5 py-0.5 font-mono text-[11px]", STATE_STYLE[s.state] ?? "border-line text-dim")}>
      {s.rule}
    </span>
  );
}

export function RunViewer({ run }: { run: Run }) {
  const [open, setOpen] = useState<number | null>(null);
  const summary = run.summary || {};
  const audit = (summary.guardrail_audit || {}) as { performed?: boolean; breaches?: { rule: string; note: string }[]; checks?: { rule: string; breached: boolean; note: string }[]; model?: string; error?: string };
  const counts = (summary.state_counts || {}) as Record<string, number>;
  const preset = summary.preset as Record<string, unknown> | null | undefined;
  const evaluation = summary.evaluation as { passed: boolean; checks: { check: string; passed: boolean; detail: string }[] } | undefined;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <StatusDot status={run.status} />
        <span className="font-mono">{run.id}</span>
        <Badge>{run.origin}</Badge>
        <Badge tone={run.assessment_mode === "model" ? "green" : run.assessment_mode === "test" ? "red" : "amber"}>
          assessment: {run.assessment_mode === "test" ? "test provider (not a real model)" : run.assessment_mode.replace("_", " ")}
        </Badge>
        {run.version && <Badge tone="cyan">{run.version}</Badge>}
        {run.execution_id && <span className="text-muted">execution {run.execution_id.slice(0, 8)}</span>}
        {Object.entries(counts).map(([k, v]) => (
          <span key={k} className={cx("rounded border px-1.5 py-0.5 font-mono text-[11px]", STATE_STYLE[k])}>{k.replace("_", " ")}: {v}</span>
        ))}
      </div>
      {run.error && <ErrorNote error={run.error} />}
      {evaluation && (
        <div className={cx("rounded-md border p-3 text-sm", evaluation.passed ? "border-green/30 bg-green/5" : "border-red/30 bg-red/5")}>
          <div className={evaluation.passed ? "text-green" : "text-red"}>Expectations {evaluation.passed ? "passed" : "failed"}</div>
          <ul className="mt-1 space-y-0.5 text-dim">
            {evaluation.checks.map((c, i) => <li key={i}>{c.passed ? "✓" : "✗"} {c.check}{c.detail ? ` — ${c.detail}` : ""}</li>)}
          </ul>
        </div>
      )}
      <div>
        <div className="x-label mb-1">Prompt</div>
        <p className="whitespace-pre-wrap text-sm text-dim">{run.prompt}</p>
      </div>
      {run.final_output !== undefined && (
        <div>
          <div className="x-label mb-1">Final output</div>
          {run.final_output ? (
            <div className="whitespace-pre-wrap rounded-md border border-line bg-bg-2 p-3 text-sm leading-relaxed">{run.final_output}</div>
          ) : <Empty>No final output (rules were not assessed or the run failed).</Empty>}
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="x-label mb-1">Delivery preset (EFV)</div>
          {preset ? <JsonView value={preset} maxHeight={160} /> : <p className="text-sm text-muted">None selected.</p>}
        </div>
        <div>
          <div className="x-label mb-1">Guardrail audit (after stage 13)</div>
          {!audit.performed ? <p className="text-sm text-muted">Not performed{audit.error ? `: ${audit.error}` : ""}.</p> : (
            <div className="text-sm">
              {audit.breaches && audit.breaches.length ? (
                <ul className="space-y-1">{audit.breaches.map((b, i) => <li key={i} className="text-red">⚠ {b.rule}: {b.note}</li>)}</ul>
              ) : <p className="text-green">No breaches flagged across {audit.checks?.length ?? 0} protected rules.</p>}
              {audit.model && <p className="mt-1 text-xs text-muted">Audited by {audit.model}</p>}
            </div>
          )}
        </div>
      </div>
      {run.layer_switches && Object.keys(run.layer_switches).length > 0 && (
        <div className="text-xs text-muted">Switches: <span className="font-mono">{JSON.stringify(run.layer_switches)}</span></div>
      )}
      <div>
        <div className="x-label mb-2">Stages</div>
        {!run.stages?.length ? <Empty>No stage records.</Empty> : (
          <ol className="space-y-2">
            {run.stages.map((s) => (
              <li key={s.position} className="rounded-md border border-line bg-bg-2">
                <button className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left" onClick={() => setOpen(open === s.position ? null : s.position)}
                  aria-expanded={open === s.position}>
                  <span className="w-6 font-mono text-xs text-muted">{s.position}</span>
                  <span className="font-mono text-sm text-intellect">{s.layer}</span>
                  <span className="text-sm text-dim">{s.mode}</span>
                  <Badge tone={s.status === "completed" ? "green" : s.status === "failed" ? "red" : s.status === "protected_only" ? "amber" : "neutral"}>{s.status.replace("_", " ")}</Badge>
                  <span className="flex flex-wrap gap-1">{s.rule_states.map((r) => <RuleStateChip key={r.rule} s={r} />)}</span>
                  {s.model && <span className="ml-auto text-xs text-muted">{s.model} · {Math.round(s.latency_ms)} ms</span>}
                </button>
                {open === s.position && (
                  <div className="space-y-3 border-t border-line px-3 py-3 text-sm">
                    {s.output && <div className="whitespace-pre-wrap text-dim">{s.output}</div>}
                    <table className="w-full text-left text-xs">
                      <tbody className="divide-y divide-line">
                        {s.rule_states.map((r) => (
                          <tr key={r.rule}><td className="py-1 pr-3 font-mono">{r.rule}</td><td className="py-1 pr-3"><RuleStateChip s={{ ...r, rule: r.state.replace("_", " ") }} /></td><td className="py-1 text-dim">{r.reason}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
      <div>
        <div className="x-label mb-2">Conflicts</div>
        {!run.conflicts?.length ? <p className="text-sm text-muted">No conflicts recorded.</p> : (
          <ul className="space-y-2">
            {run.conflicts.map((c, i) => (
              <li key={i} className="rounded-md border border-line p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono">{c.rules.join(" vs ")}</span>
                  <span className="text-muted">→</span>
                  <Badge tone="green">{c.winner} prevails</Badge>
                  <Badge>{c.detected_by}</Badge>
                  <span className="text-xs text-muted">stage {c.stage || "post"} · {c.hierarchy_step}</span>
                </div>
                <p className="mt-1 text-dim">{c.description}</p>
                <p className="mt-1 text-xs text-muted">{c.decision}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function RunLink({ id }: { id: string }) {
  return <Link className="font-mono text-cyan hover:underline" href={`/admin/intellect/runs/${id}`}>{id.slice(0, 10)}</Link>;
}
