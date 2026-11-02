"use client";

import { useState } from "react";
import { Checks, parseJson, useAction } from "@/components/admin/common";
import {
  Badge, Button, Empty, ErrorNote, Field, Input, Modal, Notice, PageHeader, Select, Spinner, Table, Td, Textarea, Toggle, fmtTime, useAsync,
} from "@/components/ui";
import { api } from "@/lib/api";
import { MODE_LABELS, type Scenario } from "@/lib/types";

type Category = { slug: string; name: string; description: string; notice: string };
const FIELD_TYPES = ["number", "text", "textarea", "matrix", "list_number", "list_text", "json"];
const ENGINES = ["ai", "intellect", "classical", "quantum"];

export default function ScenarioAdmin() {
  const list = useAsync(() => api.get<Scenario[]>("/scenarios?all=true"));
  const cats = useAsync(() => api.get<Category[]>("/scenario-categories"));
  const templates = useAsync(() => api.get<{ name: string; description: string }[]>("/quantum/templates").catch(() => []));
  const act = useAction();
  const [edit, setEdit] = useState<Scenario | "new" | null>(null);
  const [policy, setPolicy] = useState<Scenario | null>(null);
  const [versions, setVersions] = useState<{ s: Scenario; rows: { id: string; version_no: number; name: string; created_at: string }[] } | null>(null);
  return (
    <div>
      <PageHeader title="Scenario Management" subtitle="Scenarios are database records. Creating or editing one needs no code change; every edit creates a new version."
        actions={<Button variant="primary" onClick={() => setEdit("new")}>New scenario</Button>} />
      <ErrorNote error={list.error || act.error} className="mb-3" />
      {list.loading && !list.data ? <Spinner /> : list.data && (list.data.length === 0 ? <Empty>No scenarios.</Empty> : (
        <Table head={["Scenario", "Category", "Status", "Solver", "Quantum", "Modes", "Version", ""]}>
          {list.data.map((s) => (
            <tr key={s.id}>
              <Td><div className="font-medium">{s.name}{s.is_demo && <Badge tone="cyan" className="ml-2">demo</Badge>}</div><div className="font-mono text-xs text-muted">{s.slug}</div></Td>
              <Td className="text-xs">{s.category.name}</Td>
              <Td><Badge tone={s.status === "published" ? "green" : s.status === "draft" ? "amber" : "neutral"}>{s.status}</Badge></Td>
              <Td mono>{s.solver_template || "—"}</Td>
              <Td className="text-xs">{s.quantum_eligibility}</Td>
              <Td className="max-w-[220px] text-xs text-dim">{s.modes.map((m) => MODE_LABELS[m] ?? m).join(", ")}</Td>
              <Td mono>v{s.version_no}</Td>
              <Td className="whitespace-nowrap">
                <Button size="sm" variant="ghost" onClick={() => setEdit(s)}>Edit</Button>
                <Button size="sm" variant="ghost" onClick={() => setPolicy(s)}>Policy</Button>
                <Button size="sm" variant="ghost" onClick={async () => { const rows = await act.run("v", () => api.get<{ id: string; version_no: number; name: string; created_at: string }[]>(`/scenarios/${s.id}/versions`)); if (rows) setVersions({ s, rows }); }}>Versions</Button>
                {s.status !== "published" && <Button size="sm" variant="ghost" className="text-green" onClick={async () => { await act.run("p", () => api.post(`/scenarios/${s.id}/status`, { status: "published" })); list.reload(); }}>Publish</Button>}
                {s.status === "published" && <Button size="sm" variant="ghost" onClick={async () => { await act.run("d", () => api.post(`/scenarios/${s.id}/status`, { status: "draft" })); list.reload(); }}>Unpublish</Button>}
                {s.status !== "retired" && <Button size="sm" variant="ghost" className="text-red" onClick={async () => { if (window.confirm(`Retire ${s.name}?`)) { await act.run("r", () => api.post(`/scenarios/${s.id}/status`, { status: "retired" })); list.reload(); } }}>Retire</Button>}
              </Td>
            </tr>
          ))}
        </Table>
      ))}
      {edit && cats.data && <ScenarioModal scenario={edit === "new" ? null : edit} cats={cats.data} templates={templates.data ?? []} onClose={() => setEdit(null)} onDone={() => { setEdit(null); list.reload(); }} />}
      {policy && <PolicyModal s={policy} onClose={() => setPolicy(null)} onDone={() => { setPolicy(null); list.reload(); }} />}
      {versions && (
        <Modal open onClose={() => setVersions(null)} title={`Versions — ${versions.s.name}`}>
          <ul className="space-y-1 text-sm">{versions.rows.map((v) => <li key={v.id} className="flex justify-between"><span className="font-mono">v{v.version_no} · {v.name}</span><span className="text-xs text-muted">{fmtTime(v.created_at)}</span></li>)}</ul>
        </Modal>
      )}
    </div>
  );
}

function ScenarioModal({ scenario, cats, templates, onClose, onDone }: {
  scenario: Scenario | null; cats: Category[]; templates: { name: string; description: string }[]; onClose: () => void; onDone: () => void;
}) {
  const act = useAction();
  const full = useAsync(() => scenario ? api.get<Scenario>(`/scenarios/${scenario.slug}`) : Promise.resolve(null), [scenario?.slug]);
  if (scenario && !full.data) return <Modal open onClose={onClose} title="Loading…">{full.error ? <ErrorNote error={full.error} /> : <Spinner />}</Modal>;
  return <ScenarioForm s={full.data} cats={cats} templates={templates} act={act} onClose={onClose} onDone={onDone} />;
}

function ScenarioForm({ s, cats, templates, act, onClose, onDone }: {
  s: Scenario | null; cats: Category[]; templates: { name: string; description: string }[]; act: ReturnType<typeof useAction>; onClose: () => void; onDone: () => void;
}) {
  const [f, setF] = useState({
    slug: s?.slug ?? "", category: s?.category.slug ?? cats[0]?.slug ?? "", name: s?.name ?? "", tagline: s?.tagline ?? "",
    description: s?.description ?? "", problem_statement: s?.problem_statement ?? "", context: s?.context ?? "",
    demonstrates: s?.demonstrates ?? "", solver_template: s?.solver_template ?? "", quantum_eligibility: s?.quantum_eligibility ?? "evaluate",
    engines: s?.engines ?? ["ai", "intellect"], expected_output: s?.expected_output ?? "", visualizations: (s?.visualizations ?? []).join(", "),
    is_demo: s?.is_demo ?? false,
    fields: JSON.stringify(s?.fields ?? [{ key: "decision", label: "Describe the decision", type: "textarea", required: true }], null, 2),
    defaults: JSON.stringify(s?.defaults ?? {}, null, 2),
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  async function save() {
    await act.run("s", async () => {
      const fields = parseJson<{ key?: string; type?: string }[]>(f.fields, "Input fields");
      if (!Array.isArray(fields)) throw new Error("Input fields must be a JSON array.");
      for (const fd of fields) {
        if (!fd.key || !fd.type || !FIELD_TYPES.includes(fd.type)) throw new Error(`Each field needs a key and a type in: ${FIELD_TYPES.join(", ")}`);
      }
      const body = {
        slug: f.slug, category: f.category, name: f.name, tagline: f.tagline, description: f.description, problem_statement: f.problem_statement,
        context: f.context, demonstrates: f.demonstrates, solver_template: f.solver_template, quantum_eligibility: f.quantum_eligibility,
        engines: f.engines, expected_output: f.expected_output, visualizations: f.visualizations.split(",").map((x) => x.trim()).filter(Boolean),
        is_demo: f.is_demo, fields, defaults: parseJson(f.defaults, "Defaults"),
      };
      if (s) await api.put(`/scenarios/${s.id}`, body);
      else await api.post("/scenarios", body);
      onDone();
    });
  }
  return (
    <Modal open wide onClose={onClose} title={s ? `Edit ${s.name} (saves v${(s.version_no ?? 0) + 1})` : "New scenario (draft)"}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name"><Input value={f.name} onChange={set("name")} /></Field>
        <Field label="Slug"><Input value={f.slug} onChange={set("slug")} disabled={!!s} /></Field>
        <Field label="Category"><Select value={f.category} onChange={set("category")} options={cats.map((c) => ({ value: c.slug, label: c.name }))} /></Field>
        <Field label="Tagline"><Input value={f.tagline} onChange={set("tagline")} /></Field>
        <Field label="Solver template" hint="Empty for reasoning-only scenarios"><Select value={f.solver_template} onChange={set("solver_template")} options={[{ value: "", label: "(none — AI + Intellect only)" }, ...templates.map((t) => ({ value: t.name, label: `${t.name} — ${t.description}` }))]} /></Field>
        <Field label="Quantum eligibility"><Select value={f.quantum_eligibility} onChange={set("quantum_eligibility")} options={[{ value: "evaluate", label: "evaluate (selection engine decides)" }, { value: "simulation_only", label: "simulation only" }, { value: "never", label: "never" }]} /></Field>
        <Field label="Description" className="sm:col-span-2"><Textarea value={f.description} onChange={set("description")} /></Field>
        <Field label="Problem statement"><Textarea value={f.problem_statement} onChange={set("problem_statement")} /></Field>
        <Field label="Business / scientific context"><Textarea value={f.context} onChange={set("context")} /></Field>
        <Field label="What it demonstrates"><Textarea value={f.demonstrates} onChange={set("demonstrates")} /></Field>
        <Field label="Expected output"><Textarea value={f.expected_output} onChange={set("expected_output")} /></Field>
        <div><span className="x-label mb-1.5 block">Engines involved</span><Checks options={ENGINES.map((e) => ({ value: e, label: e }))} value={f.engines} onChange={(v) => setF({ ...f, engines: v })} /></div>
        <Field label="Visualizations (comma separated)"><Input value={f.visualizations} onChange={set("visualizations")} /></Field>
        <Field label="Input fields (JSON array)" className="sm:col-span-2" hint={`Each: {"key","label","type","required","min","max","help"}; type ∈ ${FIELD_TYPES.join(", ")}. For solver scenarios the keys must match the template's data.`}>
          <Textarea className="min-h-40 font-mono text-xs" value={f.fields} onChange={set("fields")} /></Field>
        <Field label="Default values (JSON object)" className="sm:col-span-2"><Textarea className="min-h-32 font-mono text-xs" value={f.defaults} onChange={set("defaults")} /></Field>
        <Toggle checked={f.is_demo} onChange={(v) => setF({ ...f, is_demo: v })} label="Curated demo scenario" />
      </div>
      <ErrorNote error={act.error} className="mt-3" />
      <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={act.busy === "s"} onClick={save}>Save</Button></div>
    </Modal>
  );
}

function PolicyModal({ s, onClose, onDone }: { s: Scenario; onClose: () => void; onDone: () => void }) {
  const act = useAction();
  const full = useAsync(() => api.get<Scenario>(`/scenarios/${s.slug}`), [s.slug]);
  const p = full.data?.policy;
  const [f, setF] = useState<{ allowed_modes: string[]; default_mode: string; max_cost_usd: number; allow_quantum_hardware: boolean; demo_enabled: boolean } | null>(null);
  const v = f ?? (p ? { ...p } : null);
  return (
    <Modal open onClose={onClose} title={`Execution policy — ${s.name}`}>
      {!v ? (full.error ? <ErrorNote error={full.error} /> : <Spinner />) : (
        <div className="space-y-3">
          <div><span className="x-label mb-1.5 block">Allowed modes</span>
            <Checks options={Object.entries(MODE_LABELS).map(([k, l]) => ({ value: k, label: l }))} value={v.allowed_modes} onChange={(m) => setF({ ...v, allowed_modes: m })} /></div>
          <Field label="Default mode"><Select value={v.default_mode} onChange={(e) => setF({ ...v, default_mode: e.target.value })} options={v.allowed_modes.map((m) => ({ value: m, label: MODE_LABELS[m] ?? m }))} /></Field>
          <Field label="Max cost per execution (USD)" hint="0 = free routes only (simulators, classical)"><Input type="number" min={0} step="0.01" value={v.max_cost_usd} onChange={(e) => setF({ ...v, max_cost_usd: Number(e.target.value) })} /></Field>
          <Toggle checked={v.allow_quantum_hardware} onChange={(x) => setF({ ...v, allow_quantum_hardware: x })} label="Allow quantum hardware" />
          <Toggle checked={v.demo_enabled} onChange={(x) => setF({ ...v, demo_enabled: x })} label="Available in Demo Mode" />
          {s.solver_template === "" && <Notice>Reasoning-only scenario: classical and quantum modes will be skipped with a reason if enabled.</Notice>}
          <ErrorNote error={act.error} />
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="primary" loading={act.busy === "s"} onClick={() => act.run("s", async () => { await api.put(`/scenarios/${s.id}/policy`, v); onDone(); })}>Save policy</Button></div>
        </div>
      )}
    </Modal>
  );
}
