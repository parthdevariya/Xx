"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAction } from "@/components/admin/common";
import { SwarmTheatre, type SwarmState } from "@/components/command/SwarmTheatre";
import { useExecution } from "@/components/command/useExecution";
import { Badge, Button, ErrorNote, Field, Input, Notice, PageHeader, Panel, Select, Spinner, StatusDot, Textarea, Toggle, cx, fmtTime, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { usePref, useReducedMotion } from "@/lib/prefs";
import type { Execution } from "@/lib/types";

type Cfg = {
  agents: number; rounds: number; platforms: { feed: boolean; forum: boolean }; allowed_actions: string[];
  memory_window: number; visible_posts: number; max_entities: number; stage_models: Record<string, string | null>;
  stage_effort: Record<string, string>; max_cost_usd: number; default_variable: string; persona_guidance: string;
  memory_backend: "internal" | "zep";
};
type Integration = { name: string; required: boolean; status: string; detail: string; used_for: string; enabled?: boolean;
  base_url?: string; configured?: boolean; hint?: string; checked_at?: string | null; latency_ms?: number | null; docs?: string };
type Overview = {
  switches: { ai: boolean; intellect: boolean; swarm: boolean }; config: Cfg; actions: string[]; stages: string[];
  models: { id: string; label: string; is_test: boolean; input_cost_per_mtok: number; output_cost_per_mtok: number }[];
  estimate: { model_calls_per_run: number; plus_chat: string };
  integrations: { llm: Integration; zep: Integration }; ready: boolean;
  readiness: { item: string; ok: boolean; note?: string }[];
};

const STAGE_LABEL: Record<string, string> = { graph: "01 Graph Building", setup: "02 Environment Setup", round: "03 Simulation rounds",
  report: "04 ReportAgent", chat: "05 Deep Interaction (chat)" };
const ACTION_LABEL: Record<string, string> = { CREATE_POST: "Post", QUOTE_POST: "Quote", CREATE_COMMENT: "Comment", LIKE_POST: "Like",
  DISLIKE_POST: "Dislike", REPOST: "Repost", FOLLOW: "Follow", MUTE: "Mute", DO_NOTHING: "Do nothing" };
const GOLD = "#f5c542";

function IntegrationCard({ i, children }: { i: Integration; children?: React.ReactNode }) {
  const tone = i.status === "ready" || i.status === "healthy" ? "green" : i.status === "test_only" || i.status === "unknown" ? "amber" : "red";
  return (
    <div className="rounded-[3px] border p-3" style={{ borderColor: tone === "green" ? "rgba(60,245,154,0.4)" : "rgba(140,255,200,0.12)" }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <StatusDot status={tone === "green" ? "healthy" : tone === "amber" ? "pending" : "down"} />
          <span className="font-display text-[15px] text-text">{i.name}</span>
          <Badge tone={i.required ? "amber" : "neutral"}>{i.required ? "Required" : "Optional"}</Badge>
        </div>
        <Badge tone={tone === "green" ? "green" : tone === "amber" ? "amber" : "red"}>{i.status.replace("_", " ")}</Badge>
      </div>
      <p className="mt-1.5 text-[12.5px] text-dim">{i.detail || i.used_for}</p>
      {i.detail && <p className="mt-1 text-[11.5px] text-muted">Used for: {i.used_for}</p>}
      {children}
    </div>
  );
}

export default function SwarmAdminPage() {
  const { can } = useAuth();
  const write = can("policies.write");
  const ov = useAsync(() => api.get<Overview>("/admin/swarm"));
  const act = useAction();
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [zep, setZep] = useState({ base_url: "", api_key: "" });
  const [saved, setSaved] = useState(false);
  const [testText, setTestText] = useState("A city council proposes replacing two bus routes with an on-demand minibus service. Residents, drivers' union, disability groups and local shops react.");
  const [testVar, setTestVar] = useState("");
  const [execId, setExecId] = useState<string | null>(null);
  const live = useExecution(execId);
  const [reduced] = useReducedMotion();
  const [, setLastTest] = usePref("swarmTestOpen", false);

  useEffect(() => {
    if (ov.data) {
      setCfg(ov.data.config);
      setZep((z) => ({ ...z, base_url: ov.data!.integrations.zep.base_url ?? "" }));
    }
  }, [ov.data]);

  const apply = (o: Overview | null | undefined) => { if (o) { ov.setData(o); setCfg(o.config); } };
  const modelOpts = [{ value: "", label: "Routing policy (best available)", description: "Uses AI Management's default routing and fallback" },
    ...(ov.data?.models ?? []).map((m) => ({ value: m.id, label: m.label + (m.is_test ? " (test)" : ""),
      description: m.is_test ? "Deterministic test provider — not a real model" : `$${m.input_cost_per_mtok}/$${m.output_cost_per_mtok} per M tokens` }))];

  if (ov.loading && !ov.data) return <Spinner />;
  if (!ov.data || !cfg) return <ErrorNote error={ov.error} />;
  const o = ov.data;
  const z = o.integrations.zep;
  const set = <K extends keyof Cfg>(k: K, v: Cfg[K]) => setCfg({ ...cfg, [k]: v });
  const calls = 3 + cfg.rounds * ((cfg.platforms.feed ? 1 : 0) + (cfg.platforms.forum ? 1 : 0));
  const swarm = live.execution?.results?.find((r) => r.step === "swarm");

  return (
    <div className="space-y-4">
      <PageHeader title="Swarm Intelligence"
        subtitle="Multi-agent social simulation inside the Intellect section: graph building, persona generation, a dual-platform simulation, a ReportAgent prediction and chat with any agent. Configure it here; switch it on or off from the switchboard above."
        actions={<div className="flex items-center gap-2 font-mono text-[11px]">
          {(["ai", "intellect", "swarm"] as const).map((k) => (
            <span key={k} className={cx("rounded-[2px] border px-2 py-1 tracking-[0.15em]", o.switches[k] ? "border-green/50 text-green" : "border-line text-muted")}>
              {k.toUpperCase()} {o.switches[k] ? "ON" : "OFF"}</span>
          ))}
        </div>} />
      <ErrorNote error={act.error} />

      <div className="grid gap-4 xl:grid-cols-[1fr_1.4fr]">
        <Panel title={`Readiness — ${o.ready ? "ready to simulate" : "action needed"}`}>
          <ul className="space-y-1.5 text-sm">
            {o.readiness.map((r) => (
              <li key={r.item} className="flex items-start gap-2">
                <span className={cx("mt-0.5 font-mono text-xs", r.ok ? "text-green" : "text-amber")}>{r.ok ? "✔" : "○"}</span>
                <span className={r.ok ? "text-text" : "text-dim"}>{r.item}{r.note && <span className="ml-1 text-xs text-muted">({r.note})</span>}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11.5px] text-muted">Estimated cost driver: {calls} model calls per run ({o.estimate.plus_chat}). Swarm runs once per execution when it is on and the mode uses Intellect, or alone in the <span className="text-text">Swarm Intelligence</span> mode.</p>
        </Panel>

        <Panel title="Required API integrations">
          <div className="space-y-3">
            <IntegrationCard i={o.integrations.llm}>
              <div className="mt-2 flex flex-wrap gap-2">
                <Link href="/admin/ai" className="rounded-[3px] border border-cyan/40 px-2.5 py-1 text-xs text-cyan hover:bg-cyan/10">Configure in AI Management →</Link>
                <span className="self-center text-[11.5px] text-muted">Anthropic, OpenAI, Azure OpenAI, Gemini, Ollama, LM Studio or any OpenAI-compatible endpoint.</span>
              </div>
            </IntegrationCard>
            <IntegrationCard i={z}>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <Field label="API key" hint={z.configured ? `Saved: ${z.hint} (write-only)` : "Project API key from app.getzep.com"}>
                  <Input type="password" autoComplete="off" disabled={!write} value={zep.api_key} placeholder={z.configured ? "•••••••• (leave blank to keep)" : "z_…"}
                    onChange={(e) => setZep({ ...zep, api_key: e.target.value })} />
                </Field>
                <Field label="API base URL" hint="Zep v4 API (https only)">
                  <Input disabled={!write} value={zep.base_url} onChange={(e) => setZep({ ...zep, base_url: e.target.value })} />
                </Field>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Toggle disabled={!write || !z.configured} checked={!!z.enabled} label="Enabled"
                  onChange={async (v) => apply(await act.run("ze", () => api.put<Overview>("/admin/integrations/zep", { enabled: v })))} />
                {write && <Button size="sm" variant="primary" loading={act.busy === "zs"} onClick={async () => {
                  const r = await act.run("zs", () => api.put<Overview>("/admin/integrations/zep", { base_url: zep.base_url, ...(zep.api_key ? { api_key: zep.api_key, enabled: true } : {}) }));
                  if (r) { apply(r); setZep({ ...zep, api_key: "" }); }
                }}>Save</Button>}
                {write && <Button size="sm" loading={act.busy === "zh"} disabled={!z.configured} onClick={async () => apply(await act.run("zh", () => api.post<Overview>("/admin/integrations/zep/health")))}>Check connection</Button>}
                {write && z.configured && <Button size="sm" variant="ghost" className="text-red" onClick={async () => { if (window.confirm("Remove the Zep API key?")) apply(await act.run("zd", () => api.del<Overview>("/admin/integrations/zep/credential"))); }}>Remove key</Button>}
                <span className="text-[11px] text-muted">{z.checked_at ? `checked ${fmtTime(z.checked_at)}${z.latency_ms ? ` · ${z.latency_ms} ms` : ""}` : "never checked"}{z.detail && ` · ${z.detail}`}</span>
              </div>
              <p className="mt-2 text-[11px] text-muted">If Zep is selected as memory but fails, the run continues on internal memory and the failure is recorded on the run. <a className="text-cyan hover:underline" href={z.docs} target="_blank" rel="noreferrer">Zep docs</a></p>
            </IntegrationCard>
          </div>
        </Panel>
      </div>

      <Panel title="Simulation configuration">
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Agents" hint="4–40"><Input type="number" min={4} max={40} disabled={!write} value={cfg.agents} onChange={(e) => set("agents", Number(e.target.value))} /></Field>
              <Field label="Rounds" hint="1–10"><Input type="number" min={1} max={10} disabled={!write} value={cfg.rounds} onChange={(e) => set("rounds", Number(e.target.value))} /></Field>
              <Field label="Max entities in graph"><Input type="number" min={4} max={30} disabled={!write} value={cfg.max_entities} onChange={(e) => set("max_entities", Number(e.target.value))} /></Field>
              <Field label="Cost cap per run (USD)" hint="0 = no cap; stops between rounds"><Input type="number" min={0} step="0.1" disabled={!write} value={cfg.max_cost_usd} onChange={(e) => set("max_cost_usd", Number(e.target.value))} /></Field>
              <Field label="Agent memory window" hint="notes kept per agent"><Input type="number" min={1} max={20} disabled={!write} value={cfg.memory_window} onChange={(e) => set("memory_window", Number(e.target.value))} /></Field>
              <Field label="Visible posts per round" hint="hot + recent"><Input type="number" min={4} max={40} disabled={!write} value={cfg.visible_posts} onChange={(e) => set("visible_posts", Number(e.target.value))} /></Field>
            </div>
            <Field label="Memory backend">
              <Select disabled={!write} value={cfg.memory_backend} onChange={(e) => set("memory_backend", e.target.value as Cfg["memory_backend"])}
                options={[{ value: "internal", label: "Internal (stored with the execution)", description: "No external service" },
                  { value: "zep", label: "Zep Cloud graph memory", description: z.configured && z.enabled ? `Zep ${z.status}` : "Configure and enable Zep above first", disabled: !(z.configured && z.enabled) }]} />
            </Field>
          </div>
          <div className="space-y-3">
            <div>
              <span className="x-label mb-1.5 block">Platforms</span>
              <div className="space-y-2">
                <Toggle disabled={!write} checked={cfg.platforms.feed} onChange={(v) => set("platforms", { ...cfg.platforms, feed: v })} label="Feed — short public posts, reposts, quotes" />
                <Toggle disabled={!write} checked={cfg.platforms.forum} onChange={(v) => set("platforms", { ...cfg.platforms, forum: v })} label="Forum — threaded discussion, comments, votes" />
              </div>
            </div>
            <div>
              <span className="x-label mb-1.5 block">Allowed agent actions</span>
              <div className="flex flex-wrap gap-1.5">
                {o.actions.map((a) => {
                  const on = cfg.allowed_actions.includes(a);
                  return (
                    <button key={a} type="button" disabled={!write || a === "DO_NOTHING"} aria-pressed={on}
                      onClick={() => set("allowed_actions", on ? cfg.allowed_actions.filter((x) => x !== a) : [...cfg.allowed_actions, a])}
                      className={cx("rounded-[2px] border px-2 py-1 font-mono text-[11px] transition-colors disabled:cursor-not-allowed",
                        on ? "border-[#f5c542]/60 bg-[#f5c542]/10 text-[#f5c542]" : "border-line text-muted hover:text-dim")}>{ACTION_LABEL[a] ?? a}</button>
                  );
                })}
              </div>
              <p className="mt-1 text-[11px] text-muted">At least one writing action (post, quote or comment) is required.</p>
            </div>
          </div>
          <div className="space-y-3">
            <Field label="Default God's-eye variable" hint="Injected for every agent from the middle round onwards; a run can override it.">
              <Textarea disabled={!write} rows={3} value={cfg.default_variable} onChange={(e) => set("default_variable", e.target.value)} placeholder="e.g. A respected auditor publishes the company's real accounts." />
            </Field>
            <Field label="Persona guidance" hint="Steers persona generation (diversity, regions, professions…).">
              <Textarea disabled={!write} rows={3} value={cfg.persona_guidance} onChange={(e) => set("persona_guidance", e.target.value)} placeholder="e.g. Include rural and urban voices, at least two sceptics, and one domain expert." />
            </Field>
          </div>
        </div>

        <div className="mt-4">
          <span className="x-label mb-2 block">Model routing per stage</span>
          <div className="overflow-x-auto rounded-[3px] border border-line">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="bg-white/[0.02]"><tr>{["Stage", "Model", "Effort"].map((h) => <th key={h} className="x-label px-3 py-2 text-left font-normal">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-line">
                {o.stages.map((st) => (
                  <tr key={st}>
                    <td className="px-3 py-2 font-mono text-xs" style={{ color: GOLD }}>{STAGE_LABEL[st] ?? st}</td>
                    <td className="px-3 py-2"><Select disabled={!write} value={cfg.stage_models[st] ?? ""} menuWidth={360}
                      onChange={(e) => set("stage_models", { ...cfg.stage_models, [st]: e.target.value || null })} options={modelOpts} /></td>
                    <td className="w-40 px-3 py-2"><Select disabled={!write} value={cfg.stage_effort[st] ?? "low"}
                      onChange={(e) => set("stage_effort", { ...cfg.stage_effort, [st]: e.target.value })}
                      options={["low", "medium", "high"].map((x) => ({ value: x, label: x }))} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-[11px] text-muted">Pinned models skip routing for that stage; if a pinned model is unavailable the call fails visibly rather than silently switching.</p>
        </div>

        {saved && <Notice tone="ok" className="mt-3">Configuration saved.</Notice>}
        {write && (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button variant="primary" loading={act.busy === "cfg"} onClick={async () => {
              setSaved(false);
              const r = await act.run("cfg", () => api.put<Overview>("/admin/swarm/config", cfg));
              if (r) { apply(r); setSaved(true); }
            }}>Save configuration</Button>
            <span className="text-xs text-muted">≈ {calls} model calls per run with these settings.</span>
          </div>
        )}
      </Panel>

      <Panel title="Test simulation (Swarm Intelligence mode)">
        <div className="grid gap-3 lg:grid-cols-[1fr_1fr_auto] lg:items-end">
          <Field label="Seed situation"><Textarea rows={3} value={testText} onChange={(e) => setTestText(e.target.value)} maxLength={20000} /></Field>
          <Field label="God's-eye variable for this run (optional)"><Textarea rows={3} value={testVar} onChange={(e) => setTestVar(e.target.value)} maxLength={2000} placeholder={cfg.default_variable || "Overrides the default variable"} /></Field>
          <Button variant="primary" disabled={!can("executions.run") || !testText.trim()} loading={act.busy === "run"} onClick={async () => {
            const ex = await act.run("run", () => api.post<Execution>("/executions", { text: testText, mode: "swarm", swarm_variable: testVar }));
            if (ex) { setExecId(ex.id); setLastTest(true); }
          }}>Run simulation</Button>
        </div>
        {!o.switches.swarm && <Notice tone="warn" className="mt-3">Swarm Intelligence is switched OFF in the switchboard above, so a test run will be planned but skipped.</Notice>}
        {live.execution && (
          <div className="mt-4 space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
              <StatusDot status={live.execution.status} /> {live.execution.status}
              {live.execution.error && <span className="text-amber">{live.execution.error}</span>}
              <Link className="ml-auto text-cyan hover:underline" href="/">Open in command centre →</Link>
            </div>
            {(swarm || live.events.some((e) => e.type.startsWith("swarm."))) && (
              <SwarmTheatre swarm={(swarm?.content as SwarmState | undefined) ?? null} cls={swarm?.content_class} events={live.events}
                executionId={live.execution.id} reducedMotion={reduced} canChat={can("executions.run")} />
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}
