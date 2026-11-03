"use client";

import { useState } from "react";
import { Checks, parseJson, useAction } from "@/components/admin/common";
import {
  Badge, Button, Empty, ErrorNote, Field, Input, Modal, Notice, PageHeader, Select, Spinner, Table, Td, Textarea, Toggle, fmtTime, useAsync,
} from "@/components/ui";
import { api } from "@/lib/api";
import { MODE_LABELS, type Scenario } from "@/lib/types";

type Category = { slug: string; name: string; description: string; notice: string };
type ManagedCategory = Category & { id: string; position: number; scenario_count: number };
type Draft = Partial<Scenario> & {
  suggested_policy?: { allowed_modes: string[]; default_mode: string };
  _generated_by: string; _test_provider: boolean; _warnings: string[];
};
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
  const [showCats, setShowCats] = useState(false);
  const [showGen, setShowGen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  return (
    <div>
      <PageHeader title="Scenario Management" subtitle="Scenarios are database records. Creating or editing one needs no code change; every edit creates a new version."
        actions={<>
          <Button onClick={() => setShowCats(true)}>Categories</Button>
          <Button onClick={() => setShowGen(true)}>✦ Generate with AI</Button>
          <Button variant="primary" onClick={() => setEdit("new")}>New scenario</Button>
        </>} />
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
      {showCats && <CategoriesModal onClose={() => { setShowCats(false); cats.reload(); list.reload(); }} />}
      {showGen && cats.data && <GenerateModal cats={cats.data} onClose={() => setShowGen(false)} onDraft={(d) => { setShowGen(false); setDraft(d); }} />}
      {draft && cats.data && <ScenarioForm s={null} draft={draft} cats={cats.data} templates={templates.data ?? []} act={act} onClose={() => setDraft(null)} onDone={() => { setDraft(null); list.reload(); }} />}
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

function ScenarioForm({ s: existing, draft, cats, templates, act, onClose, onDone }: {
  s: Scenario | null; draft?: Draft; cats: Category[]; templates: { name: string; description: string }[]; act: ReturnType<typeof useAction>; onClose: () => void; onDone: () => void;
}) {
  const s = existing ?? (draft as unknown as Scenario | undefined) ?? null;
  const isNew = !existing;
  const [f, setF] = useState({
    rubric: JSON.stringify(s?.benchmark_config?.rubric ?? [], null, 2),
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
        benchmark_config: { ...(s?.benchmark_config ?? {}), rubric: parseJson(f.rubric, "Rubric") },
      };
      if (!isNew) await api.put(`/scenarios/${existing!.id}`, body);
      else {
        const created = await api.post<Scenario>("/scenarios", body);
        if (draft?.suggested_policy) {
          await api.put(`/scenarios/${created.id}/policy`, { ...draft.suggested_policy, max_cost_usd: 0, allow_quantum_hardware: false, demo_enabled: true });
        }
      }
      onDone();
    });
  }
  return (
    <Modal open wide onClose={onClose} title={!isNew ? `Edit ${s!.name} (saves v${(s!.version_no ?? 0) + 1})` : draft ? "Review generated scenario (saves as draft)" : "New scenario (draft)"}>
      {draft && (
        <div className="mb-3 space-y-2">
          <Notice tone={draft._test_provider ? "warn" : "info"}>Generated by {draft._generated_by}{draft._test_provider ? " — TEST PROVIDER placeholder, not real model output" : ""}. Review every field; nothing is saved until you press Save, and it saves as a draft.</Notice>
          {draft._warnings.length > 0 && <Notice tone="warn">{draft._warnings.join(" · ")}</Notice>}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name"><Input value={f.name} onChange={set("name")} /></Field>
        <Field label="Slug"><Input value={f.slug} onChange={set("slug")} disabled={!isNew} /></Field>
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
        <Field label="Evaluation rubric (JSON array) — used by Intellect vs AI and Benchmark" className="sm:col-span-2"
          hint={'Each: {"id","criterion","why","related_rules":["RL-03"],"check":{"type":"judge"|"max_questions"|"must_not_contain","value":…}}. Fixed before any run; the judge never sees which system wrote an answer.'}>
          <Textarea className="min-h-40 font-mono text-xs" value={f.rubric} onChange={set("rubric")} /></Field>
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


function CategoriesModal({ onClose }: { onClose: () => void }) {
  const act = useAction();
  const list = useAsync(() => api.get<ManagedCategory[]>("/scenario-categories/manage"));
  const blank = { id: "", slug: "", name: "", description: "", notice: "", position: 0 };
  const [f, setF] = useState(blank);
  async function save() {
    const body = { slug: f.slug, name: f.name, description: f.description, notice: f.notice, position: Number(f.position) || 0 };
    const ok = await act.run("s", () => f.id ? api.put(`/scenario-categories/${f.id}`, body) : api.post("/scenario-categories", body));
    if (ok) { setF(blank); list.reload(); }
  }
  return (
    <Modal open wide onClose={onClose} title="Scenario categories">
      <ErrorNote error={list.error || act.error} className="mb-3" />
      {list.loading && !list.data ? <Spinner /> : (
        <Table head={["Category", "Slug", "Scenarios", "Notice", ""]}>
          {(list.data ?? []).map((c) => (
            <tr key={c.id}>
              <Td><div className="font-medium">{c.name}</div><div className="text-xs text-muted">{c.description}</div></Td>
              <Td mono>{c.slug}</Td>
              <Td mono>{c.scenario_count}</Td>
              <Td className="max-w-[200px] text-xs text-amber">{c.notice}</Td>
              <Td className="whitespace-nowrap">
                <Button size="sm" variant="ghost" onClick={() => setF({ id: c.id, slug: c.slug, name: c.name, description: c.description, notice: c.notice, position: c.position })}>Edit</Button>
                <Button size="sm" variant="ghost" className="text-red" disabled={c.scenario_count > 0} title={c.scenario_count ? "Move its scenarios first" : undefined}
                  onClick={async () => { if (window.confirm(`Delete category ${c.name}?`)) { await act.run("d", () => api.del(`/scenario-categories/${c.id}`)); list.reload(); } }}>Delete</Button>
              </Td>
            </tr>
          ))}
        </Table>
      )}
      <div className="mt-4 rounded-[3px] border border-line p-3">
        <div className="x-label mb-2">{f.id ? "Edit category" : "Add category"}</div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value, slug: f.id ? f.slug : e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") })} /></Field>
          <Field label="Slug"><Input value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value })} /></Field>
          <Field label="Description" className="sm:col-span-2"><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <Field label="Mandatory notice (shown on every scenario in this category)" className="sm:col-span-2"><Input value={f.notice} onChange={(e) => setF({ ...f, notice: e.target.value })} /></Field>
          <Field label="Display order"><Input type="number" value={f.position} onChange={(e) => setF({ ...f, position: Number(e.target.value) })} /></Field>
        </div>
        <div className="mt-3 flex justify-end gap-2">
          {f.id && <Button variant="ghost" onClick={() => setF(blank)}>Cancel edit</Button>}
          <Button variant="primary" loading={act.busy === "s"} disabled={!f.name || !f.slug} onClick={save}>{f.id ? "Save category" : "Add category"}</Button>
        </div>
      </div>
    </Modal>
  );
}

function GenerateModal({ cats, onClose, onDraft }: { cats: Category[]; onClose: () => void; onDraft: (d: Draft) => void }) {
  const act = useAction();
  const models = useAsync(() => api.get<{ id: string; label: string; is_test: boolean }[]>("/scenarios/generator/models"));
  const [f, setF] = useState({ brief: "", category: cats.find((c) => c.slug === "intellect-proof")?.slug ?? cats[0]?.slug ?? "", kind: "reasoning", model_id: "" });
  return (
    <Modal open wide onClose={onClose} title="Generate a scenario with AI">
      <div className="space-y-3">
        <p className="text-sm text-dim">Describe the situation you want to test. The model drafts a realistic scenario with traps a plain AI answer tends to fall into, plus a rubric grounded in real X Layers rule IDs. You review it and save it as a draft.</p>
        {models.data && models.data.length === 0 && <Notice tone="warn">No AI model is configured. Add an Anthropic or OpenAI key in AI Management first.</Notice>}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Model"><Select value={f.model_id} onChange={(e) => setF({ ...f, model_id: e.target.value })}
            options={[{ value: "", label: "Best available (routing policy)" }, ...(models.data ?? []).map((m) => ({ value: m.id, label: m.label + (m.is_test ? " (test)" : "") }))]} /></Field>
          <Field label="Category"><Select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} options={cats.map((c) => ({ value: c.slug, label: c.name }))} /></Field>
          <Field label="Type"><Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}
            options={[{ value: "reasoning", label: "Reasoning trap (Intellect vs AI)" }, { value: "computation", label: "Computation + judgment (solver + Intellect)" }]} /></Field>
        </div>
        <Field label="Brief" hint="e.g. 'A hospital administrator wants to cut night staff to hit a budget; the optimiser says it is cheapest, but patient-safety signals are buried in the details.'">
          <Textarea rows={5} value={f.brief} onChange={(e) => setF({ ...f, brief: e.target.value })} maxLength={4000} />
        </Field>
        <ErrorNote error={act.error || models.error} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={act.busy === "g"} disabled={f.brief.trim().length < 10} onClick={async () => {
            const d = await act.run("g", () => api.post<Draft>("/scenarios/generate", { ...f, model_id: f.model_id || null }));
            if (d) onDraft(d);
          }}>Generate draft</Button>
        </div>
      </div>
    </Modal>
  );
}
