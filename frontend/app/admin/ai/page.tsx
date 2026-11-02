"use client";

import { useState } from "react";
import { Checks, HealthBadge, parseJson, useAction } from "@/components/admin/common";
import {
  Badge, Button, Empty, ErrorNote, Field, Input, Modal, Notice, PageHeader, Panel, Select, Spinner, Table, Td, Textarea,
  Toggle, fmtNum, fmtTime, useAsync,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Model = {
  id: string; provider_id: string; model_id: string; display_name: string; capabilities: string[]; modalities: string[];
  context_window: number; max_output_tokens: number; input_cost_per_mtok: number; output_cost_per_mtok: number;
  quality_rank: number; latency_class: string; is_active: boolean;
};
type Provider = {
  id: string; name: string; kind: string; base_url: string; auth_scheme: string; is_active: boolean; timeout_s: number;
  rate_limit_rpm: number; config: Record<string, unknown>; health_status: string; last_latency_ms: number | null;
  last_checked_at: string | null; last_error: string; credential: { configured: boolean; hint: string };
  is_test_provider: boolean; models: Model[];
};
type Meta = { kinds: string[]; auth_schemes: string[]; capabilities: { code: string; description: string }[] };
type Policy = { id: string; name: string; description: string; is_default: boolean; rules: Record<string, unknown> };

export default function AIManagement() {
  const { can } = useAuth();
  const write = can("ai.write");
  const providers = useAsync(() => api.get<Provider[]>("/ai/providers"));
  const meta = useAsync(() => api.get<Meta>("/ai/meta"));
  const [adding, setAdding] = useState(false);
  return (
    <div className="space-y-6">
      <PageHeader title="AI Management" subtitle="Providers, models, credentials, routing, usage and logs. A provider is only used when it is active, has a credential (unless it needs none), and passes routing."
        actions={write && <Button variant="primary" onClick={() => setAdding(true)}>Add provider</Button>} />
      <ErrorNote error={providers.error || meta.error} />
      {providers.loading && !providers.data ? <Spinner /> : (
        <div className="space-y-4">
          {providers.data?.map((p) => <ProviderCard key={p.id} p={p} meta={meta.data} write={write} reload={providers.reload} />)}
          {providers.data?.length === 0 && <Empty>No providers configured.</Empty>}
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        <Policies write={write} />
        <RoutePreview capabilities={meta.data?.capabilities ?? []} />
      </div>
      <Usage />
      <Logs />
      {adding && meta.data && <ProviderModal meta={meta.data} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); providers.reload(); }} />}
    </div>
  );
}

function ProviderCard({ p, meta, write, reload }: { p: Provider; meta: Meta | null; write: boolean; reload: () => void }) {
  const act = useAction();
  const [editing, setEditing] = useState(false);
  const [cred, setCred] = useState(false);
  const [model, setModel] = useState<Model | "new" | null>(null);
  const [discovered, setDiscovered] = useState<{ available: string[]; not_registered: string[] } | null>(null);
  const [health, setHealth] = useState<{ status: string; latency_ms: number | null; detail: string } | null>(null);

  async function toggleActive(v: boolean) {
    if (v && p.is_test_provider && !window.confirm("Activate the deterministic TEST provider? It returns fixed placeholder output, not real model reasoning. Results it produces are labelled 'test' everywhere, but it will be used for live requests while active.")) return;
    await act.run("active", () => api.patch(`/ai/providers/${p.id}`, { is_active: v }));
    reload();
  }

  return (
    <Panel title={<span className="flex items-center gap-2 normal-case tracking-normal"><span className="font-display text-sm text-text">{p.name}</span><Badge>{p.kind}</Badge>{p.is_test_provider && <Badge tone="red">Test provider — not a real model</Badge>}</span>}
      actions={<>
        <Toggle checked={p.is_active} onChange={toggleActive} label={p.is_active ? "Active" : "Inactive"} disabled={!write || act.busy === "active"} />
      </>}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2"><HealthBadge status={p.health_status} />
            {p.last_latency_ms != null && <span className="font-mono text-xs text-muted">{Math.round(p.last_latency_ms)} ms</span>}
            <span className="text-xs text-muted">checked {fmtTime(p.last_checked_at)}</span></div>
          <div><span className="text-muted">Endpoint </span><span className="font-mono text-xs break-all">{p.base_url || "(SDK default)"}</span></div>
          <div><span className="text-muted">Auth </span><span className="font-mono text-xs">{p.auth_scheme}</span></div>
          <div><span className="text-muted">Timeout </span>{p.timeout_s}s · <span className="text-muted">Rate limit </span>{p.rate_limit_rpm}/min</div>
          <div><span className="text-muted">Credential </span>{p.credential.configured ? <span className="font-mono">{p.credential.hint}</span> : <span className="text-amber">not set</span>}</div>
          {Object.keys(p.config || {}).length > 0 && <div className="font-mono text-xs text-muted break-all">{JSON.stringify(p.config)}</div>}
          {p.last_error && <div className="rounded border border-red/20 bg-red/5 p-2 text-xs text-red break-words">{p.last_error}</div>}
          {health && <Notice tone={health.status === "healthy" ? "ok" : "warn"}>Health: {health.status}{health.latency_ms ? ` · ${Math.round(health.latency_ms)} ms` : ""}{health.detail ? ` — ${health.detail}` : ""}</Notice>}
          <ErrorNote error={act.error} />
          {write && (
            <div className="flex flex-wrap gap-2 pt-1">
              <Button size="sm" loading={act.busy === "health"} onClick={async () => { const r = await act.run("health", () => api.post<typeof health>(`/ai/providers/${p.id}/health`)); if (r) setHealth(r); reload(); }}>Check health</Button>
              <Button size="sm" onClick={() => setCred(true)}>{p.credential.configured ? "Replace credential" : "Set credential"}</Button>
              {p.credential.configured && <Button size="sm" variant="danger" onClick={async () => { if (window.confirm("Remove the stored credential?")) { await act.run("rmcred", () => api.del(`/ai/providers/${p.id}/credential`)); reload(); } }}>Remove credential</Button>}
              <Button size="sm" onClick={() => setEditing(true)}>Edit</Button>
              {!p.is_test_provider && <Button size="sm" loading={act.busy === "disc"} onClick={async () => { const r = await act.run("disc", () => api.post<typeof discovered>(`/ai/providers/${p.id}/discover-models`)); if (r) setDiscovered(r); }}>Discover models</Button>}
              <Button size="sm" variant="danger" onClick={async () => { if (window.confirm(`Delete provider ${p.name} and its models?`)) { await act.run("del", () => api.del(`/ai/providers/${p.id}`)); reload(); } }}>Delete</Button>
            </div>
          )}
          {discovered && (
            <div className="rounded border border-line p-2 text-xs">
              <div className="text-muted">{discovered.available.length} models at the endpoint; not registered:</div>
              <div className="mt-1 flex flex-wrap gap-1">{discovered.not_registered.length ? discovered.not_registered.map((m) => <span key={m} className="font-mono text-dim">{m}</span>) : <span className="text-muted">none</span>}</div>
            </div>
          )}
        </div>
        <div className="min-w-0">
          <div className="mb-2 flex items-center justify-between"><span className="x-label">Models</span>{write && <Button size="sm" onClick={() => setModel("new")}>Add model</Button>}</div>
          {p.models.length === 0 ? <Empty>No models registered.</Empty> : (
            <Table head={["Model", "Context", "Cost in/out $/Mtok", "Quality", "Latency", "Capabilities", "Active", ""]}>
              {p.models.map((m) => (
                <tr key={m.id}>
                  <Td><div className="font-mono text-xs">{m.model_id}</div><div className="text-xs text-muted">{m.display_name}</div></Td>
                  <Td mono>{m.context_window.toLocaleString()}</Td>
                  <Td mono>{m.input_cost_per_mtok} / {m.output_cost_per_mtok}</Td>
                  <Td mono>{m.quality_rank}</Td>
                  <Td>{m.latency_class}</Td>
                  <Td className="max-w-[220px] text-xs text-muted">{m.capabilities.join(", ") || "—"}</Td>
                  <Td>{m.is_active ? <Badge tone="green">on</Badge> : <Badge>off</Badge>}</Td>
                  <Td>{write && <Button size="sm" variant="ghost" onClick={() => setModel(m)}>Edit</Button>}</Td>
                </tr>
              ))}
            </Table>
          )}
        </div>
      </div>
      {editing && meta && <ProviderModal meta={meta} provider={p} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); reload(); }} />}
      {cred && <CredentialModal p={p} onClose={() => setCred(false)} onSaved={() => { setCred(false); reload(); }} />}
      {model && <ModelModal providerId={p.id} model={model === "new" ? null : model} caps={meta?.capabilities ?? []} onClose={() => setModel(null)} onSaved={() => { setModel(null); reload(); }} />}
    </Panel>
  );
}

function ProviderModal({ meta, provider, onClose, onSaved }: { meta: Meta; provider?: Provider; onClose: () => void; onSaved: () => void }) {
  const act = useAction();
  const [f, setF] = useState({
    name: provider?.name ?? "", kind: provider?.kind ?? "openai_compatible", base_url: provider?.base_url ?? "",
    auth_scheme: provider?.auth_scheme ?? "bearer", timeout_s: provider?.timeout_s ?? 60, rate_limit_rpm: provider?.rate_limit_rpm ?? 60,
    config: JSON.stringify(provider?.config ?? {}, null, 2),
  });
  async function save() {
    await act.run("save", async () => {
      const config = parseJson<Record<string, unknown>>(f.config, "Config");
      const body = { name: f.name, base_url: f.base_url, auth_scheme: f.auth_scheme, timeout_s: Number(f.timeout_s), rate_limit_rpm: Number(f.rate_limit_rpm), config };
      if (provider) await api.patch(`/ai/providers/${provider.id}`, body);
      else await api.post("/ai/providers", { ...body, kind: f.kind, is_active: false });
      onSaved();
    });
  }
  return (
    <Modal open onClose={onClose} title={provider ? `Edit ${provider.name}` : "Add AI provider"}>
      <div className="space-y-3">
        <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        {!provider && <Field label="Adapter kind" hint="openai_compatible covers OpenAI, Azure OpenAI, Gemini (OpenAI endpoint), Ollama, LM Studio, vLLM, OpenRouter, Groq.">
          <Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })} options={meta.kinds.map((k) => ({ value: k, label: k }))} /></Field>}
        <Field label="Base URL"><Input value={f.base_url} onChange={(e) => setF({ ...f, base_url: e.target.value })} placeholder="https://…/v1" /></Field>
        <Field label="Auth scheme"><Select value={f.auth_scheme} onChange={(e) => setF({ ...f, auth_scheme: e.target.value })} options={meta.auth_schemes.map((k) => ({ value: k, label: k }))} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Timeout (s)"><Input type="number" value={f.timeout_s} onChange={(e) => setF({ ...f, timeout_s: Number(e.target.value) })} /></Field>
          <Field label="Rate limit (req/min)"><Input type="number" value={f.rate_limit_rpm} onChange={(e) => setF({ ...f, rate_limit_rpm: Number(e.target.value) })} /></Field>
        </div>
        <Field label="Config (JSON)" hint='e.g. {"api_version": "2024-10-21"} for Azure, {"refusal_fallback": true} for Anthropic'><Textarea className="font-mono text-xs" value={f.config} onChange={(e) => setF({ ...f, config: e.target.value })} /></Field>
        <ErrorNote error={act.error} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={act.busy === "save"} onClick={save}>Save</Button></div>
      </div>
    </Modal>
  );
}

function CredentialModal({ p, onClose, onSaved }: { p: Provider; onClose: () => void; onSaved: () => void }) {
  const act = useAction();
  const [secret, setSecret] = useState("");
  const [extra, setExtra] = useState("");
  return (
    <Modal open onClose={onClose} title={`Credential — ${p.name}`}>
      <div className="space-y-3">
        <Notice>The key is encrypted at rest and is never shown again after saving; only a masked hint is displayed.</Notice>
        <Field label="API key / secret"><Input type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} /></Field>
        <Field label="Extra (optional)" hint="Additional secret material some providers need, e.g. an organisation ID."><Input type="password" autoComplete="off" value={extra} onChange={(e) => setExtra(e.target.value)} /></Field>
        <ErrorNote error={act.error} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!secret} loading={act.busy === "s"} onClick={() => act.run("s", async () => { await api.put(`/ai/providers/${p.id}/credential`, { secret, extra }); onSaved(); })}>Save credential</Button></div>
      </div>
    </Modal>
  );
}

function ModelModal({ providerId, model, caps, onClose, onSaved }: { providerId: string; model: Model | null; caps: { code: string; description: string }[]; onClose: () => void; onSaved: () => void }) {
  const act = useAction();
  const [f, setF] = useState({
    model_id: model?.model_id ?? "", display_name: model?.display_name ?? "", capabilities: model?.capabilities ?? caps.map((c) => c.code).slice(0, 1),
    modalities: (model?.modalities ?? ["text"]).join(","), context_window: model?.context_window ?? 128000, max_output_tokens: model?.max_output_tokens ?? 4096,
    input_cost_per_mtok: model?.input_cost_per_mtok ?? 0, output_cost_per_mtok: model?.output_cost_per_mtok ?? 0,
    quality_rank: model?.quality_rank ?? 50, latency_class: model?.latency_class ?? "medium", is_active: model?.is_active ?? true,
  });
  const num = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: Number(e.target.value) });
  async function save() {
    await act.run("s", async () => {
      const body = { ...f, modalities: f.modalities.split(",").map((s) => s.trim()).filter(Boolean) };
      if (model) {
        const { model_id: _drop, ...patch } = body; // model id is immutable
        void _drop;
        await api.patch(`/ai/models/${model.id}`, patch);
      } else await api.post(`/ai/providers/${providerId}/models`, body);
      onSaved();
    });
  }
  return (
    <Modal open wide onClose={onClose} title={model ? `Edit ${model.model_id}` : "Add model"}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Model ID"><Input value={f.model_id} disabled={!!model} onChange={(e) => setF({ ...f, model_id: e.target.value })} /></Field>
        <Field label="Display name"><Input value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></Field>
        <Field label="Context window"><Input type="number" value={f.context_window} onChange={num("context_window")} /></Field>
        <Field label="Max output tokens"><Input type="number" value={f.max_output_tokens} onChange={num("max_output_tokens")} /></Field>
        <Field label="Input $ / million tokens"><Input type="number" step="0.01" value={f.input_cost_per_mtok} onChange={num("input_cost_per_mtok")} /></Field>
        <Field label="Output $ / million tokens"><Input type="number" step="0.01" value={f.output_cost_per_mtok} onChange={num("output_cost_per_mtok")} /></Field>
        <Field label="Quality rank (0–100, admin-set)"><Input type="number" min={0} max={100} value={f.quality_rank} onChange={num("quality_rank")} /></Field>
        <Field label="Latency class"><Select value={f.latency_class} onChange={(e) => setF({ ...f, latency_class: e.target.value })} options={["fast", "medium", "slow"].map((v) => ({ value: v, label: v }))} /></Field>
        <Field label="Modalities (comma separated)"><Input value={f.modalities} onChange={(e) => setF({ ...f, modalities: e.target.value })} /></Field>
        <div className="flex items-end"><Toggle checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} label="Active" /></div>
        <div className="sm:col-span-2"><span className="x-label mb-1.5 block">Capabilities</span>
          <Checks options={caps.map((c) => ({ value: c.code, label: c.code }))} value={f.capabilities} onChange={(v) => setF({ ...f, capabilities: v })} /></div>
      </div>
      <ErrorNote error={act.error} className="mt-3" />
      <div className="mt-4 flex justify-between gap-2">
        {model ? <Button variant="danger" onClick={() => act.run("d", async () => { if (window.confirm("Delete this model?")) { await api.del(`/ai/models/${model.id}`); onSaved(); } })}>Delete</Button> : <span />}
        <div className="flex gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={act.busy === "s"} onClick={save}>Save</Button></div>
      </div>
    </Modal>
  );
}

function Policies({ write }: { write: boolean }) {
  const pols = useAsync(() => api.get<Policy[]>("/ai/routing-policies"));
  const act = useAction();
  const [edit, setEdit] = useState<{ name: string; description: string; is_default: boolean; rules: string } | null>(null);
  return (
    <Panel title="Routing policies" actions={write && <Button size="sm" onClick={() => setEdit({ name: "", description: "", is_default: false, rules: JSON.stringify({ weights: { quality: 0.85, cost: 0.1, latency: 0.05 }, max_cost_per_call_usd: 1.0, allow_providers: [], deny_providers: [], category_overrides: {} }, null, 2) })}>New policy</Button>}>
      <ErrorNote error={pols.error} />
      <div className="space-y-3">
        {pols.data?.map((p) => (
          <div key={p.id} className="rounded-md border border-line p-3">
            <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{p.name}</span>{p.is_default && <Badge tone="green">default</Badge>}
              {write && <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setEdit({ name: p.name, description: p.description, is_default: p.is_default, rules: JSON.stringify(p.rules, null, 2) })}>Edit</Button>}</div>
            <p className="text-xs text-muted">{p.description}</p>
            <pre className="mt-2 overflow-x-auto font-mono text-[11px] text-dim">{JSON.stringify(p.rules)}</pre>
          </div>
        ))}
        {pols.data?.length === 0 && <Empty>No policies.</Empty>}
      </div>
      {edit && (
        <Modal open onClose={() => setEdit(null)} title="Routing policy">
          <div className="space-y-3">
            <Field label="Name" hint="Saving with an existing name updates that policy."><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Description"><Input value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
            <Field label="Rules (JSON)" hint="weights {quality,cost,latency}, cost_reference_usd, max_cost_per_call_usd, allow_providers, deny_providers, category_overrides {category: {min_quality}}">
              <Textarea className="min-h-48 font-mono text-xs" value={edit.rules} onChange={(e) => setEdit({ ...edit, rules: e.target.value })} /></Field>
            <Toggle checked={edit.is_default} onChange={(v) => setEdit({ ...edit, is_default: v })} label="Default policy" />
            <ErrorNote error={act.error} />
            <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button>
              <Button variant="primary" loading={act.busy === "s"} onClick={() => act.run("s", async () => {
                await api.post("/ai/routing-policies", { name: edit.name, description: edit.description, is_default: edit.is_default, rules: parseJson(edit.rules, "Rules") });
                setEdit(null); pols.reload();
              })}>Save</Button></div>
          </div>
        </Modal>
      )}
    </Panel>
  );
}

function RoutePreview({ capabilities }: { capabilities: { code: string }[] }) {
  const act = useAction();
  const [cap, setCap] = useState("text_reasoning");
  const [category, setCategory] = useState("");
  const [res, setRes] = useState<{ candidates: { provider: string; model: string; score: number; est_cost_usd: number; reason: string }[]; rejected: { model: string; reason: string }[] } | null>(null);
  return (
    <Panel title="Route preview">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Capability" className="min-w-40 flex-1"><Select value={cap} onChange={(e) => setCap(e.target.value)} options={capabilities.map((c) => ({ value: c.code, label: c.code }))} /></Field>
        <Field label="Category" className="min-w-32 flex-1"><Input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="e.g. mathematical" /></Field>
        <Button loading={act.busy === "p"} onClick={async () => { const r = await act.run("p", () => api.post<typeof res>("/ai/route-preview", { capability: cap, category })); if (r) setRes(r); }}>Preview</Button>
      </div>
      <ErrorNote error={act.error} className="mt-2" />
      {res && (
        <div className="mt-3 space-y-3 text-sm">
          <div className="x-label">Ranked candidates (fallback order)</div>
          {res.candidates.length ? <ol className="space-y-1">{res.candidates.map((c, i) => <li key={i} className="font-mono text-xs"><span className="text-green">{c.score.toFixed(3)}</span> {c.provider}/{c.model} <span className="text-muted">— {c.reason}</span></li>)}</ol>
            : <Notice tone="warn">No model can serve this request.</Notice>}
          {res.rejected.length > 0 && <><div className="x-label">Rejected</div><ul className="space-y-0.5">{res.rejected.map((r, i) => <li key={i} className="text-xs text-muted"><span className="font-mono">{r.model}</span> — {r.reason}</li>)}</ul></>}
        </div>
      )}
    </Panel>
  );
}

function Usage() {
  const u = useAsync(() => api.get<{ by_model: { model: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number; avg_latency_ms: number }[]; errors: number }>("/ai/usage"));
  return (
    <Panel title="Usage by model">
      <ErrorNote error={u.error} />
      {u.data && (u.data.by_model.length === 0 ? <Empty>No successful AI calls recorded yet. Errors: {u.data.errors}.</Empty> : (
        <Table head={["Model", "Calls", "Input tokens", "Output tokens", "Est. cost $", "Avg latency"]}>
          {u.data.by_model.map((r) => <tr key={r.model}><Td mono>{r.model}</Td><Td mono>{r.calls}</Td><Td mono>{r.input_tokens.toLocaleString()}</Td><Td mono>{r.output_tokens.toLocaleString()}</Td><Td mono>{r.cost_usd.toFixed(4)}</Td><Td mono>{Math.round(r.avg_latency_ms)} ms</Td></tr>)}
        </Table>
      ))}
    </Panel>
  );
}

function Logs() {
  const [status, setStatus] = useState("");
  const logs = useAsync(() => api.get<{ id: string; at: string; execution_id: string | null; model: string; kind: string; purpose: string; status: string; input_tokens: number; output_tokens: number; cost_usd: number; latency_ms: number; error: string }[]>(`/ai/logs?limit=100${status ? `&status=${status}` : ""}`), [status]);
  return (
    <Panel title="Recent AI calls" actions={<Select value={status} onChange={(e) => setStatus(e.target.value)} className="!h-7 !w-36 text-xs" options={[{ value: "", label: "All statuses" }, { value: "ok", label: "ok" }, { value: "fallback", label: "fallback" }, { value: "error", label: "error" }]} />}>
      <ErrorNote error={logs.error} />
      {logs.data && (logs.data.length === 0 ? <Empty>No AI calls logged.</Empty> : (
        <Table head={["Time", "Model", "Purpose", "Status", "Tokens", "Cost $", "Latency", "Error"]}>
          {logs.data.map((l) => (
            <tr key={l.id}>
              <Td className="whitespace-nowrap text-xs">{fmtTime(l.at)}</Td>
              <Td><span className="font-mono text-xs">{l.model}</span>{l.kind === "deterministic_test" && <Badge tone="red" className="ml-1">test</Badge>}</Td>
              <Td className="text-xs text-dim">{l.purpose}</Td>
              <Td><Badge tone={l.status === "ok" ? "green" : l.status === "error" ? "red" : "amber"}>{l.status}</Badge></Td>
              <Td mono>{l.input_tokens}/{l.output_tokens}</Td>
              <Td mono>{fmtNum(l.cost_usd)}</Td>
              <Td mono>{Math.round(l.latency_ms)} ms</Td>
              <Td className="max-w-[280px] text-xs text-red break-words">{l.error}</Td>
            </tr>
          ))}
        </Table>
      ))}
    </Panel>
  );
}
