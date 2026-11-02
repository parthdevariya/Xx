"use client";

import { useState } from "react";
import { HealthBadge, parseJson, useAction } from "@/components/admin/common";
import {
  Badge, Button, Empty, ErrorNote, ExecBadge, Field, Input, JsonView, KV, Modal, Notice, PageHeader, Panel, Select, Spinner,
  Table, Td, Textarea, Toggle, fmtNum, fmtTime, useAsync,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { MODE_LABELS, type QuantumDecision } from "@/lib/types";

type Backend = {
  id: string; backend_key: string; name: string; modality: string; is_hardware: boolean; max_qubits: number;
  supported_formulations: string[]; max_shots: number; default_shots: number; pricing: Record<string, number>;
  two_qubit_error: number | null; queue_depth: number | null; status: string; status_detail: string; is_active: boolean;
};
type QProvider = {
  id: string; name: string; vendor: string; endpoint: string; is_active: boolean; sdk_available: boolean; health_status: string;
  health_detail: string; last_checked_at: string | null; max_execution_s: number; max_cost_per_job_usd: number;
  config: Record<string, unknown>; credential: { configured: boolean; hint: string; env: string | null }; backends: Backend[];
};
type Algorithm = {
  id: string; key: string; name: string; description: string; problem_compatibility: string[]; known_limitations: string[];
  benchmark_methodology: string; execution_config: Record<string, unknown>; resource_requirements: Record<string, unknown>;
  backend_requirements: Record<string, unknown>; benefit_evidence: Record<string, unknown>[]; is_active: boolean;
};
type Job = {
  id: string; execution_id: string | null; backend_key: string; algorithm: string; execution_class: string; status: string;
  qubits: number; circuit_depth: number; shots: number; submitted_at: string; wall_time_s: number; cost_usd: number; error: string;
};

export default function QuantumManagement() {
  const { can } = useAuth();
  const write = can("quantum.write");
  const provs = useAsync(() => api.get<QProvider[]>("/quantum/providers"));
  const act = useAction();
  return (
    <div className="space-y-6">
      <PageHeader title="Quantum Management"
        subtitle="Providers and backends mirror their real availability. A backend runs only when its provider is active, its SDK is installed and credentials work. Simulators and hardware are always labelled separately."
        actions={write && <>
          <Button loading={act.busy === "sync"} onClick={async () => { await act.run("sync", () => api.post("/quantum/sync")); provs.reload(); }}>Sync registry</Button>
          <Button loading={act.busy === "live"} onClick={async () => { await act.run("live", () => api.post("/quantum/sync?live=true")); provs.reload(); }} title="Queries credentialed providers for live device status">Refresh live status</Button>
        </>} />
      <ErrorNote error={provs.error || act.error} />
      {provs.loading && !provs.data ? <Spinner /> : provs.data?.map((p) => <ProviderPanel key={p.id} p={p} write={write} reload={provs.reload} />)}
      <SelectionTester />
      <Algorithms write={write} />
      <Jobs />
    </div>
  );
}

function ProviderPanel({ p, write, reload }: { p: QProvider; write: boolean; reload: () => void }) {
  const act = useAction();
  const [cred, setCred] = useState(false);
  const [edit, setEdit] = useState(false);
  return (
    <Panel title={<span className="flex flex-wrap items-center gap-2 normal-case tracking-normal"><span className="font-display text-sm text-text">{p.name}</span><Badge>{p.vendor}</Badge><HealthBadge status={p.health_status} />{!p.sdk_available && <Badge tone="amber">SDK not installed</Badge>}</span>}
      actions={<Toggle checked={p.is_active} disabled={!write} label={p.is_active ? "Active" : "Inactive"} onChange={async (v) => { await act.run("a", () => api.patch(`/quantum/providers/${p.id}`, { is_active: v })); reload(); }} />}
      className="mb-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
        {p.vendor !== "local" && <span><span className="text-muted">Credential </span>{p.credential.configured ? <span className="font-mono">{p.credential.hint}</span> : <span className="text-amber">not set</span>}{p.credential.env && <span className="text-xs text-muted"> → {p.credential.env}</span>}</span>}
        <span><span className="text-muted">Max execution </span>{p.max_execution_s}s</span>
        <span><span className="text-muted">Max cost/job </span>${p.max_cost_per_job_usd}</span>
        <span className="text-xs text-muted">checked {fmtTime(p.last_checked_at)}</span>
        {write && <span className="ml-auto flex gap-2">
          {p.vendor !== "local" && <Button size="sm" onClick={() => setCred(true)}>{p.credential.configured ? "Replace credential" : "Set credential"}</Button>}
          {p.credential.configured && <Button size="sm" variant="danger" onClick={async () => { if (window.confirm("Remove credential?")) { await act.run("r", () => api.del(`/quantum/providers/${p.id}/credential`)); reload(); } }}>Remove</Button>}
          <Button size="sm" onClick={() => setEdit(true)}>Limits</Button>
        </span>}
      </div>
      {p.health_detail && <p className="mb-2 text-xs text-muted">{p.health_detail}</p>}
      <ErrorNote error={act.error} className="mb-2" />
      {p.backends.length === 0 ? <Empty>No backends reported.</Empty> : (
        <Table head={["Backend", "Type", "Qubits", "Formulations", "Status", "Noise (2q)", "Pricing", "Default shots", "Active"]}>
          {p.backends.map((b) => (
            <tr key={b.id}>
              <Td><div className="font-mono text-xs">{b.backend_key}</div><div className="text-xs text-muted">{b.name}</div></Td>
              <Td><ExecBadge cls={b.is_hardware ? "hardware" : b.modality === "classical" ? "classical" : b.modality} /></Td>
              <Td mono>{b.max_qubits.toLocaleString()}</Td>
              <Td className="text-xs text-muted">{b.supported_formulations.join(", ")}</Td>
              <Td><div className="flex items-center gap-1.5"><HealthBadge status={b.status} /></div>{b.status_detail && <div className="mt-1 max-w-[260px] text-xs text-muted">{b.status_detail}</div>}</Td>
              <Td mono>{b.two_qubit_error ?? "—"}</Td>
              <Td className="font-mono text-[11px] text-muted">{Object.entries(b.pricing).filter(([, v]) => v).map(([k, v]) => `${k} ${v}`).join(" · ") || "free"}</Td>
              <Td><Input type="number" className="!h-7 w-24 text-xs" defaultValue={b.default_shots} disabled={!write}
                onBlur={async (e) => { const v = Number(e.target.value); if (v !== b.default_shots) { await act.run("s", () => api.patch(`/quantum/backends/${b.id}`, { default_shots: v })); reload(); } }} /></Td>
              <Td><Toggle checked={b.is_active} disabled={!write} label={`${b.backend_key} active`} onChange={async (v) => { await act.run("b", () => api.patch(`/quantum/backends/${b.id}`, { is_active: v })); reload(); }} /></Td>
            </tr>
          ))}
        </Table>
      )}
      {cred && <CredModal p={p} onClose={() => setCred(false)} onSaved={() => { setCred(false); reload(); }} />}
      {edit && <LimitsModal p={p} onClose={() => setEdit(false)} onSaved={() => { setEdit(false); reload(); }} />}
    </Panel>
  );
}

function CredModal({ p, onClose, onSaved }: { p: QProvider; onClose: () => void; onSaved: () => void }) {
  const act = useAction();
  const [secret, setSecret] = useState("");
  const [rows, setRows] = useState<{ k: string; v: string }[]>([{ k: "", v: "" }]);
  return (
    <Modal open onClose={onClose} title={`Credential — ${p.name}`}>
      <div className="space-y-3">
        <Notice>The secret is encrypted and exposed to the {p.vendor} SDK only during a job{p.credential.env ? <>, as <span className="font-mono">{p.credential.env}</span></> : null}. It is never displayed again.</Notice>
        <Field label="Secret"><Input type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} /></Field>
        <div>
          <span className="x-label mb-1.5 block">Additional environment values</span>
          <p className="mb-2 text-xs text-muted">e.g. AWS_ACCESS_KEY_ID, AWS_DEFAULT_REGION; AZURE_QUANTUM_SUBSCRIPTION_ID, AZURE_QUANTUM_RESOURCE_GROUP, AZURE_QUANTUM_WORKSPACE_NAME; GOOGLE_QUANTUM_PROCESSOR_ID; IBM_QUANTUM_INSTANCE.</p>
          {rows.map((r, i) => (
            <div key={i} className="mb-2 flex gap-2">
              <Input placeholder="NAME" value={r.k} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, k: e.target.value } : x))} />
              <Input placeholder="value" type="password" value={r.v} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, v: e.target.value } : x))} />
            </div>
          ))}
          <Button size="sm" variant="ghost" onClick={() => setRows([...rows, { k: "", v: "" }])}>+ value</Button>
        </div>
        <ErrorNote error={act.error} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!secret} loading={act.busy === "s"} onClick={() => act.run("s", async () => {
            const extra = Object.fromEntries(rows.filter((r) => r.k.trim()).map((r) => [r.k.trim(), r.v]));
            await api.put(`/quantum/providers/${p.id}/credential`, { secret, extra }); onSaved();
          })}>Save</Button></div>
      </div>
    </Modal>
  );
}

function LimitsModal({ p, onClose, onSaved }: { p: QProvider; onClose: () => void; onSaved: () => void }) {
  const act = useAction();
  const [f, setF] = useState({ endpoint: p.endpoint, max_execution_s: p.max_execution_s, max_cost_per_job_usd: p.max_cost_per_job_usd, config: JSON.stringify(p.config, null, 2) });
  return (
    <Modal open onClose={onClose} title={`Limits — ${p.name}`}>
      <div className="space-y-3">
        <Field label="Endpoint"><Input value={f.endpoint} onChange={(e) => setF({ ...f, endpoint: e.target.value })} /></Field>
        <Field label="Max execution time (s)"><Input type="number" value={f.max_execution_s} onChange={(e) => setF({ ...f, max_execution_s: Number(e.target.value) })} /></Field>
        <Field label="Max cost per job (USD)"><Input type="number" step="0.01" value={f.max_cost_per_job_usd} onChange={(e) => setF({ ...f, max_cost_per_job_usd: Number(e.target.value) })} /></Field>
        <Field label="Config (JSON)"><Textarea className="font-mono text-xs" value={f.config} onChange={(e) => setF({ ...f, config: e.target.value })} /></Field>
        <ErrorNote error={act.error} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={act.busy === "s"} onClick={() => act.run("s", async () => {
            await api.patch(`/quantum/providers/${p.id}`, { endpoint: f.endpoint, max_execution_s: f.max_execution_s, max_cost_per_job_usd: f.max_cost_per_job_usd, config: parseJson(f.config, "Config") }); onSaved();
          })}>Save</Button></div>
      </div>
    </Modal>
  );
}

const DECISION_TONE: Record<string, "green" | "cyan" | "blue" | "amber" | "neutral" | "red"> = {
  quantum_recommended: "green", quantum_experimental: "blue", quantum_simulation_recommended: "cyan",
  classical_preferred: "neutral", quantum_not_applicable: "neutral", insufficient_information: "amber",
};

function DecisionView({ d }: { d: QuantumDecision }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2"><Badge tone={DECISION_TONE[d.decision] ?? "neutral"}>{d.decision.replace(/_/g, " ")}</Badge>
        {d.route && <><ExecBadge cls={d.route.execution_class} /><span className="font-mono text-xs text-muted">{d.route.algorithm} on {d.route.backend}</span></>}</div>
      <p className="text-sm text-dim">{d.explanation}</p>
      <KV items={Object.entries(d.factors).map(([k, v]) => [k.replace(/_/g, " "), v === null ? <span className="text-muted">not evaluated</span> : String(v)])} />
    </div>
  );
}

function SelectionTester() {
  const templates = useAsync(() => api.get<{ name: string; description: string; sense: string }[]>("/quantum/templates"));
  const act = useAction();
  const [template, setTemplate] = useState("number_partition");
  const [data, setData] = useState('{"numbers": [42, 37, 28, 25, 19, 17, 14, 11, 8, 5]}');
  const [mode, setMode] = useState("benchmark");
  const [hw, setHw] = useState(false);
  const [cost, setCost] = useState(0);
  const [res, setRes] = useState<QuantumDecision | null>(null);
  return (
    <Panel title="Quantum selection engine — tester">
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          <Field label="Template"><Select value={template} onChange={(e) => setTemplate(e.target.value)}
            options={[{ value: "", label: "(none — not a solver problem)" }, ...(templates.data ?? []).map((t) => ({ value: t.name, label: `${t.name} — ${t.description}` }))]} /></Field>
          <Field label="Problem data (JSON)"><Textarea className="min-h-32 font-mono text-xs" value={data} onChange={(e) => setData(e.target.value)} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Mode"><Select value={mode} onChange={(e) => setMode(e.target.value)} options={Object.entries(MODE_LABELS).map(([v, l]) => ({ value: v, label: l }))} /></Field>
            <Field label="Max cost (USD)"><Input type="number" step="0.01" value={cost} onChange={(e) => setCost(Number(e.target.value))} /></Field>
          </div>
          <Toggle checked={hw} onChange={setHw} label="Allow quantum hardware" />
          <Button variant="primary" loading={act.busy === "e"} onClick={async () => {
            const r = await act.run("e", () => api.post<QuantumDecision>("/quantum/evaluate", { template: template || null, data: parseJson(data, "Data"), mode, allow_hardware: hw, max_cost_usd: cost }));
            if (r) setRes(r);
          }}>Evaluate</Button>
          <ErrorNote error={act.error || templates.error} />
        </div>
        <div>{res ? <DecisionView d={res} /> : <Empty>Run an evaluation to see the decision and all 15 factors.</Empty>}</div>
      </div>
    </Panel>
  );
}

function Algorithms({ write }: { write: boolean }) {
  const algos = useAsync(() => api.get<Algorithm[]>("/quantum/algorithms"));
  const [edit, setEdit] = useState<Algorithm | null>(null);
  return (
    <Panel title="Algorithm library">
      <Notice className="mb-3">Without admin-entered, cited benefit evidence for a problem class and size, the selection engine never returns <span className="font-mono">quantum_recommended</span>.</Notice>
      <ErrorNote error={algos.error} />
      <div className="grid gap-3 lg:grid-cols-2">
        {algos.data?.map((a) => (
          <div key={a.id} className="rounded-md border border-line p-3 text-sm">
            <div className="flex items-center gap-2"><span className="font-medium">{a.name}</span><Badge>{a.key}</Badge>{!a.is_active && <Badge tone="amber">inactive</Badge>}
              {write && <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setEdit(a)}>Edit</Button>}</div>
            <p className="mt-1 text-dim">{a.description}</p>
            <div className="mt-2 text-xs text-muted">Compatible: {a.problem_compatibility.join(", ")}</div>
            <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-amber/90">{a.known_limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
            <div className="mt-2 text-xs text-muted">Benchmark: {a.benchmark_methodology}</div>
            <div className="mt-2 text-xs">Benefit evidence: {a.benefit_evidence.length ? <span className="text-green">{a.benefit_evidence.length} entr{a.benefit_evidence.length > 1 ? "ies" : "y"}</span> : <span className="text-muted">none on record</span>}</div>
          </div>
        ))}
      </div>
      {edit && <AlgoModal a={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); algos.reload(); }} />}
    </Panel>
  );
}

function AlgoModal({ a, onClose, onSaved }: { a: Algorithm; onClose: () => void; onSaved: () => void }) {
  const act = useAction();
  const [desc, setDesc] = useState(a.description);
  const [lims, setLims] = useState(a.known_limitations.join("\n"));
  const [cfg, setCfg] = useState(JSON.stringify(a.execution_config, null, 2));
  const [ev, setEv] = useState(JSON.stringify(a.benefit_evidence, null, 2));
  const [active, setActive] = useState(a.is_active);
  return (
    <Modal open wide onClose={onClose} title={`Edit ${a.name}`}>
      <div className="space-y-3">
        <Field label="Description"><Textarea value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
        <Field label="Known limitations (one per line)"><Textarea value={lims} onChange={(e) => setLims(e.target.value)} /></Field>
        <Field label="Execution config (JSON)"><Textarea className="font-mono text-xs" value={cfg} onChange={(e) => setCfg(e.target.value)} /></Field>
        <Field label="Benefit evidence (JSON array)" hint='Each entry: {"problem": "tsp" or "*", "citation": "…", "min_vars": 0, "max_vars": 50}. Problem and citation are required.'>
          <Textarea className="min-h-32 font-mono text-xs" value={ev} onChange={(e) => setEv(e.target.value)} /></Field>
        <Toggle checked={active} onChange={setActive} label="Active" />
        <ErrorNote error={act.error} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={act.busy === "s"} onClick={() => act.run("s", async () => {
            const evidence = parseJson<unknown>(ev, "Evidence");
            if (!Array.isArray(evidence)) throw new Error("Evidence must be a JSON array.");
            await api.patch(`/quantum/algorithms/${a.id}`, { description: desc, known_limitations: lims.split("\n").map((s) => s.trim()).filter(Boolean), execution_config: parseJson(cfg, "Config"), benefit_evidence: evidence, is_active: active });
            onSaved();
          })}>Save</Button></div>
      </div>
    </Modal>
  );
}

function Jobs() {
  const jobs = useAsync(() => api.get<Job[]>("/quantum/jobs?limit=100"));
  const [logs, setLogs] = useState<{ id: string; rows: { at: string; level: string; message: string }[] } | null>(null);
  const act = useAction();
  return (
    <Panel title="Quantum jobs" actions={<Button size="sm" variant="ghost" onClick={jobs.reload}>Refresh</Button>}>
      <ErrorNote error={jobs.error || act.error} />
      {jobs.data && (jobs.data.length === 0 ? <Empty>No quantum jobs yet.</Empty> : (
        <Table head={["Submitted", "Backend", "Class", "Algorithm", "Status", "Qubits", "Depth", "Shots", "Time", "Cost", ""]}>
          {jobs.data.map((j) => (
            <tr key={j.id}>
              <Td className="whitespace-nowrap text-xs">{fmtTime(j.submitted_at)}</Td>
              <Td mono>{j.backend_key}</Td>
              <Td><ExecBadge cls={j.execution_class} /></Td>
              <Td mono>{j.algorithm}</Td>
              <Td><Badge tone={j.status === "completed" ? "green" : j.status === "failed" ? "red" : "cyan"}>{j.status}</Badge>{j.error && <div className="mt-1 max-w-[240px] text-xs text-red">{j.error}</div>}</Td>
              <Td mono>{j.qubits}</Td><Td mono>{j.circuit_depth}</Td><Td mono>{j.shots}</Td>
              <Td mono>{fmtNum(j.wall_time_s, 3)}s</Td><Td mono>${fmtNum(j.cost_usd)}</Td>
              <Td><Button size="sm" variant="ghost" onClick={async () => { const r = await act.run("l", () => api.get<{ at: string; level: string; message: string }[]>(`/quantum/jobs/${j.id}/logs`)); if (r) setLogs({ id: j.id, rows: r }); }}>Logs</Button></Td>
            </tr>
          ))}
        </Table>
      ))}
      {logs && (
        <Modal open wide onClose={() => setLogs(null)} title={`Job ${logs.id.slice(0, 10)} logs`}>
          {logs.rows.length ? <ul className="space-y-1 font-mono text-xs">{logs.rows.map((r, i) => <li key={i} className={r.level === "error" ? "text-red" : "text-dim"}>{fmtTime(r.at)} [{r.level}] {r.message}</li>)}</ul> : <Empty>No log lines.</Empty>}
          <JsonView value={jobs.data?.find((j) => j.id === logs.id)} maxHeight={200} />
        </Modal>
      )}
    </Panel>
  );
}
