"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, ErrorNote, Field, Input, Notice, Select, Textarea, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { MODE_LABELS, type Execution, type ModeInfo, type Scenario, type ScenarioField } from "@/lib/types";

const ALL_MODES = Object.keys(MODE_LABELS);

function toText(v: unknown, type: ScenarioField["type"]): string {
  if (v === undefined || v === null) return "";
  if (type === "list_number" || type === "list_text") return Array.isArray(v) ? v.join(", ") : String(v);
  if (type === "matrix" || type === "json") return JSON.stringify(v);
  return String(v);
}

function fromText(s: string, type: ScenarioField["type"]): { value?: unknown; error?: string } {
  const t = s.trim();
  if (!t) return { value: undefined };
  try {
    switch (type) {
      case "number": {
        const n = Number(t);
        return Number.isFinite(n) ? { value: n } : { error: "must be a number" };
      }
      case "list_number": {
        const xs = t.split(/[,\s]+/).filter(Boolean).map(Number);
        return xs.every(Number.isFinite) ? { value: xs } : { error: "comma-separated numbers" };
      }
      case "list_text":
        return { value: t.split(",").map((x) => x.trim()).filter(Boolean) };
      case "matrix":
      case "json":
        return { value: JSON.parse(t) };
      default:
        return { value: s };
    }
  } catch {
    return { error: "invalid JSON" };
  }
}

export function ProblemConsole({ scenario, onClearScenario, onSubmitted, canWrite }: {
  scenario: Scenario | null; onClearScenario: () => void; onSubmitted: (e: Execution) => void; canWrite: boolean;
}) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [files, setFiles] = useState<File[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [advanced, setAdvanced] = useState(false);
  const [allowHardware, setAllowHardware] = useState(false);
  const [maxCost, setMaxCost] = useState("0");
  const [autoRun, setAutoRun] = useState(true);
  const [swarmVar, setSwarmVar] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [modeInfo, setModeInfo] = useState<Record<string, ModeInfo>>({});
  useEffect(() => {
    api.get<ModeInfo[]>("/modes").then((ms) => setModeInfo(Object.fromEntries(ms.map((m) => [m.key, m])))).catch(() => setModeInfo({}));
  }, []);

  const modes = scenario ? scenario.modes : ALL_MODES;
  const fields = useMemo(() => scenario?.fields ?? [], [scenario]);

  useEffect(() => {
    if (scenario) {
      setMode(scenario.default_mode);
      const v: Record<string, string> = {};
      for (const f of scenario.fields ?? []) v[f.key] = toText(scenario.defaults?.[f.key], f.type);
      setValues(v);
      setText("");
    } else {
      setValues({});
      setMode("hybrid");
    }
    setError(null);
  }, [scenario]);

  const parsed = useMemo(() => {
    const out: Record<string, unknown> = {};
    const errors: Record<string, string> = {};
    for (const f of fields) {
      const r = fromText(values[f.key] ?? "", f.type);
      if (r.error) errors[f.key] = r.error;
      else if (r.value !== undefined) out[f.key] = r.value;
      else if (f.required) errors[f.key] = "required";
    }
    return { out, errors };
  }, [fields, values]);

  async function submit(e: React.FormEvent, overrideMode?: string) {
    e.preventDefault();
    if (Object.keys(parsed.errors).length) {
      setError(new Error("Fix the highlighted inputs."));
      return;
    }
    setBusy(true);
    setError(null);
    const payload = {
      text, mode: overrideMode ?? mode, inputs: scenario ? parsed.out : {}, scenario_slug: scenario?.slug ?? null,
      allow_hardware: allowHardware, max_cost_usd: Number(maxCost) || 0, auto_run: autoRun, swarm_variable: swarmVar,
    };
    try {
      let ex: Execution;
      if (files.length) {
        const fd = new FormData();
        fd.append("payload", JSON.stringify(payload));
        files.forEach((f) => fd.append("files", f));
        ex = await api.form<Execution>("/executions/upload", fd);
      } else {
        ex = await api.post<Execution>("/executions", payload);
      }
      onSubmitted(ex);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3.5">
      {scenario ? (
        <div className="rounded-md border border-green/25 bg-green/[0.04] p-3">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="x-label !text-green">Scenario</div>
              <div className="font-display text-[15px] font-medium">{scenario.name}</div>
            </div>
            <button type="button" onClick={onClearScenario} className="text-xs text-muted hover:text-text">Clear</button>
          </div>
          {scenario.demonstrates && <p className="mt-1.5 text-[12.5px] text-dim"><span className="text-muted">Demonstrates:</span> {scenario.demonstrates}</p>}
          {scenario.category.notice && <Notice tone="warn" className="mt-2 !py-1.5 text-xs">{scenario.category.notice}</Notice>}
        </div>
      ) : null}

      <Field label={scenario ? "Additional context (optional)" : "Describe the problem"}>
        <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={scenario ? 2 : 5} maxLength={20000}
          placeholder={scenario ? "Anything X should know beyond the inputs…" : "e.g. Allocate five delivery vans to five regions at minimum cost — costs are in the attached CSV."} />
      </Field>

      {fields.length > 0 && (
        <div className="space-y-3">
          {fields.map((f) => (
            <Field key={f.key} label={f.label ?? f.key} hint={f.help} error={parsed.errors[f.key] && values[f.key] !== undefined ? parsed.errors[f.key] : null}>
              {f.type === "textarea" || f.type === "matrix" || f.type === "json" ? (
                <Textarea value={values[f.key] ?? ""} rows={f.type === "textarea" ? 4 : 3}
                  className={f.type !== "textarea" ? "font-mono text-xs" : ""}
                  onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
              ) : (
                <Input value={values[f.key] ?? ""} inputMode={f.type === "number" ? "decimal" : undefined}
                  className={f.type.startsWith("list") ? "font-mono text-xs" : ""}
                  onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
              )}
            </Field>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Execution mode">
          <Select value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Execution mode"
            menuWidth={420}
            options={ALL_MODES.map((m) => ({
              value: m, label: MODE_LABELS[m], disabled: !modes.includes(m), description: modeInfo[m]?.description,
              tag: modeInfo[m]?.engines.map((e) => ({ ai: "AI", intellect: "IN", classical: "CL", quantum: "QU" } as Record<string, string>)[e]).join("·"),
            }))} />
        </Field>
        <Field label="Supporting files" hint="PDF, DOCX, TXT, CSV, JSON · up to 3 · 10 MB each">
          <input ref={fileRef} type="file" multiple accept=".pdf,.docx,.txt,.csv,.json" className="sr-only" id="x-files"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 3))} />
          <label htmlFor="x-files" className="flex h-9 cursor-pointer items-center rounded-md border border-dashed border-line-strong px-3 text-sm text-dim hover:border-green/40">
            {files.length ? `${files.length} file(s) attached` : "Attach files…"}
          </label>
        </Field>
      </div>
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {files.map((f) => <Badge key={f.name}>{f.name}</Badge>)}
          <button type="button" className="text-xs text-muted hover:text-text" onClick={() => { setFiles([]); if (fileRef.current) fileRef.current.value = ""; }}>clear</button>
        </div>
      )}

      <button type="button" onClick={() => setAdvanced(!advanced)} className="text-xs text-dim hover:text-text" aria-expanded={advanced}>
        {advanced ? "▾" : "▸"} Advanced settings
      </button>
      {advanced && (
        <div className="space-y-3 rounded-md border border-line p-3">
          <Toggle checked={allowHardware} onChange={setAllowHardware} label="Allow real quantum hardware (if configured and permitted by policy)" />
          <Field label="Maximum spend for this run (USD)" hint="Capped by the orchestration policy. 0 = free routes only.">
            <Input type="number" min={0} step="0.01" value={maxCost} onChange={(e) => setMaxCost(e.target.value)} />
          </Field>
          <Field label="Swarm God's-eye variable (optional)" hint="Injected into the Swarm Intelligence simulation from the middle round, when Swarm runs.">
            <Input value={swarmVar} maxLength={2000} onChange={(e) => setSwarmVar(e.target.value)} placeholder="e.g. A respected auditor publishes the real accounts" />
          </Field>
          <Toggle checked={autoRun} onChange={setAutoRun} label="Start immediately when the plan has no cost (otherwise review the plan first)" />
        </div>
      )}

      <ErrorNote error={error} />
      <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={!canWrite}>
        {autoRun ? "Plan & run" : "Generate plan"}
      </Button>
      {scenario && modes.includes("matrix") && (
        <button type="button" disabled={!canWrite || busy} onClick={(e) => submit(e as unknown as React.FormEvent, "matrix")}
          className="group relative w-full overflow-hidden rounded-[3px] border border-cyan/50 bg-cyan/[0.06] py-2.5 font-mono text-[12px] tracking-[0.2em] text-cyan transition-colors hover:bg-cyan/[0.12] disabled:opacity-40">
          <span className="absolute inset-y-0 -left-1/3 w-1/3 bg-gradient-to-r from-transparent via-cyan/20 to-transparent transition-all duration-700 group-hover:left-full" />
          ⚡ RUN ALL 11 ENGINE COMBINATIONS
        </button>
      )}
      {!canWrite && <p className="text-xs text-muted">Your role can browse but not run executions.</p>}
    </form>
  );
}
