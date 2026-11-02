"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Core } from "@/components/command/Core";
import { InitSequence } from "@/components/command/InitSequence";
import { Insights, PlanView } from "@/components/command/Insights";
import { LiveConsole } from "@/components/command/LiveConsole";
import { ProblemConsole } from "@/components/command/ProblemConsole";
import { Results } from "@/components/command/Results";
import { ScenarioLibrary } from "@/components/command/ScenarioLibrary";
import { engineStates, useExecution } from "@/components/command/useExecution";
import { RequireAuth } from "@/components/RequireAuth";
import { Badge, Button, ErrorNote, Notice, Panel, StatusDot, Toggle, cx, fmtTime } from "@/components/ui";
import { Wordmark } from "@/components/XMark";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { usePref, useReducedMotion } from "@/lib/prefs";
import type { Execution, Scenario, SystemStatus } from "@/lib/types";

function EnginePills({ status }: { status: SystemStatus | null }) {
  if (!status) return <span className="text-xs text-muted">checking engines…</span>;
  const q = status.quantum.providers.filter((p) => p.status === "healthy" && p.active).map((p) => p.vendor);
  const pills: [string, string, string][] = [
    ["AI", status.ai.status === "ready" ? "ready" : "unconfigured",
      status.ai.status === "ready" ? status.ai.configured_providers.join(", ") : status.ai.test_provider_active ? "test provider only" : "not configured"],
    ["Quantum", q.length ? "ready" : "unavailable", q.length ? q.join(", ") : "none"],
    ["Intellect", status.intellect.status, status.intellect.version ? `${status.intellect.version} · ${status.intellect.rules} rules` : "missing"],
  ];
  return (
    <div className="hidden items-center gap-4 md:flex">
      {pills.map(([n, s, d]) => (
        <span key={n} className="flex items-center gap-1.5 text-xs" title={d}>
          <StatusDot status={s} /><span className="text-dim">{n}</span><span className="text-muted">{d}</span>
        </span>
      ))}
    </div>
  );
}

function History({ onOpen, refreshKey }: { onOpen: (id: string) => void; refreshKey: number }) {
  const [items, setItems] = useState<Execution[]>([]);
  useEffect(() => {
    api.get<Execution[]>("/executions?limit=8").then(setItems).catch(() => setItems([]));
  }, [refreshKey]);
  if (!items.length) return <p className="text-xs text-muted">No executions yet.</p>;
  return (
    <ul className="space-y-1">
      {items.map((e) => (
        <li key={e.id}>
          <button onClick={() => onOpen(e.id)} className="grid w-full grid-cols-[10px_1fr_auto] items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-white/5">
            <StatusDot status={e.status} />
            <span className="truncate text-dim">{e.problem_summary || e.mode_label}</span>
            <span className="text-muted">{fmtTime(e.created_at)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function CommandCentre() {
  const { user, can, logout } = useAuth();
  const [skipIntro, setSkipIntro] = usePref("skipIntro", false);
  const [reducedMotion, setReducedMotion] = useReducedMotion();
  const [introDone, setIntroDone] = useState(false);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [demo, setDemo] = useState(false);
  const [execId, setExecId] = useState<string | null>(null);
  const [cached, setCached] = useState<Execution | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [historyKey, setHistoryKey] = useState(0);
  const [prefsOpen, setPrefsOpen] = useState(false);
  const live = useExecution(cached ? null : execId);
  const execution = cached ?? live.execution;

  useEffect(() => {
    api.get<Scenario[]>("/scenarios").then(setScenarios).catch(setError);
    if (skipIntro) api.get<SystemStatus>("/system/status").then(setStatus).catch(() => setStatus(null));
  }, [skipIntro]);

  useEffect(() => {
    if (execution && ["completed", "failed", "cancelled"].includes(execution.status)) setHistoryKey((k) => k + 1);
  }, [execution?.status, execution]);

  const available = useMemo(() => ({
    ai: status?.ai.status === "ready" || !!status?.ai.test_provider_active,
    quantum: status?.quantum.status === "ready",
    intellect: status?.intellect.status === "ready",
  }), [status]);
  const states = engineStates(execution, cached ? [] : live.events, available);
  const running = !!execution && ["queued", "running"].includes(execution.status);

  const open = useCallback((id: string) => {
    setCached(null);
    setExecId(id);
  }, []);

  async function runPlan() {
    if (!execution) return;
    try {
      await api.post(`/executions/${execution.id}/run`);
      live.reload();
    } catch (e) {
      setError(e);
    }
  }

  async function demoRun(s: Scenario) {
    setError(null);
    try {
      const ex = await api.post<Execution>(`/demo/${s.slug}/run`, { mode: s.default_mode });
      open(ex.id);
    } catch (e) {
      setError(e);
    }
  }

  async function demoCached(s: Scenario) {
    setError(null);
    try {
      setCached(await api.get<Execution>(`/demo/${s.slug}/cached?mode=${s.default_mode}`));
      setExecId(null);
    } catch (e) {
      setError(e);
    }
  }

  const showIntro = !skipIntro && !introDone;

  return (
    <div className="x-grid x-vignette min-h-dvh">
      {showIntro && <InitSequence reducedMotion={reducedMotion} onDone={(s) => { setStatus(s); setIntroDone(true); }} />}
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-line bg-bg/85 px-4 backdrop-blur">
        <div className="flex items-center gap-5">
          <Wordmark />
          <EnginePills status={status} />
        </div>
        <div className="flex items-center gap-3 text-sm">
          <Toggle checked={demo} onChange={setDemo} label="Demo mode" />
          {can("dashboard.read") && <Link href="/admin" className="text-dim hover:text-green">Admin</Link>}
          <div className="relative">
            <button onClick={() => setPrefsOpen(!prefsOpen)} className="text-muted hover:text-text" aria-expanded={prefsOpen} aria-label="Preferences">⚙</button>
            {prefsOpen && (
              <div className="x-panel absolute right-0 top-8 z-40 w-64 space-y-3 p-3">
                <Toggle checked={reducedMotion} onChange={setReducedMotion} label="Reduce motion" />
                <Toggle checked={skipIntro} onChange={setSkipIntro} label="Skip intro on load" />
                <button className="text-xs text-dim hover:text-text" onClick={() => { setIntroDone(false); setSkipIntro(false); setPrefsOpen(false); }}>Replay initialisation</button>
                <div className="border-t border-line pt-2 text-xs text-muted">{user?.email} · {user?.role_name}</div>
                <button onClick={logout} className="text-xs text-dim hover:text-text">Sign out</button>
              </div>
            )}
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto max-w-[1680px] space-y-4 p-4">
        {demo && (
          <Notice className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="font-medium text-text">Demo Mode</span>
            <span>Curated scenarios. Every result is labelled:</span>
            <Badge tone="green">Live</Badge><Badge tone="blue">Cached</Badge><Badge tone="cyan">Quantum simulation</Badge>
            <Badge tone="blue">Quantum hardware</Badge><Badge>Classical</Badge><Badge tone="red">Test provider</Badge>
            <span>Core animation shows real engine states only.</span>
          </Notice>
        )}
        <ErrorNote error={error ?? live.error} />

        <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)_340px]">
          <div className="space-y-4">
            <Panel title="Problem console">
              <ProblemConsole scenario={scenario} onClearScenario={() => setScenario(null)} canWrite={can("executions.run")}
                onSubmitted={(ex) => { open(ex.id); setHistoryKey((k) => k + 1); }} />
            </Panel>
            <Panel title={demo ? "Demonstration scenarios" : "Scenario library"} bodyClass="max-h-[640px] overflow-y-auto">
              <ScenarioLibrary scenarios={scenarios} selected={scenario?.slug ?? null} demoOnly={demo}
                onSelect={(s) => setScenario(s)} />
              {demo && scenario && (
                <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
                  <Button size="sm" variant="primary" onClick={() => demoRun(scenario)} disabled={!can("executions.run")}>Run live</Button>
                  <Button size="sm" onClick={() => demoCached(scenario)}>Show last result (cached)</Button>
                </div>
              )}
            </Panel>
          </div>

          <div className="space-y-4">
            <Panel title="X computational core" actions={execution ? <Badge>{execution.mode_label}</Badge> : null}>
              <div className="grid items-center gap-4 lg:grid-cols-[minmax(0,340px)_1fr]">
                <Core states={states} running={running} reducedMotion={reducedMotion} />
                <div className="min-w-0">
                  {execution?.plan ? <PlanView execution={execution} events={cached ? [] : live.events} onRun={runPlan} />
                    : <p className="text-sm text-muted">Choose a scenario or describe a problem. X classifies it, plans which engines apply — and says when quantum computation does not — then runs the plan and records every step.</p>}
                </div>
              </div>
            </Panel>
            <Panel title="Live execution console" className="h-[340px]" bodyClass="flex min-h-0 flex-col">
              <LiveConsole events={cached ? [] : live.events} transport={live.transport} status={execution?.status} />
            </Panel>
          </div>

          <div className="space-y-4">
            <Panel title="Computational insights"><Insights execution={execution} /></Panel>
            <Panel title="Recent executions"><History onOpen={open} refreshKey={historyKey} /></Panel>
          </div>
        </div>

        <Panel title="Results workspace" className={cx(!execution && "opacity-90")}>
          <Results execution={execution} />
        </Panel>
      </main>
    </div>
  );
}

export default function Page() {
  return (
    <RequireAuth>
      <CommandCentre />
    </RequireAuth>
  );
}
