"use client";

import { useState } from "react";
import { Page, useAction } from "@/components/admin/common";
import { IntellectShell, type Run, RunLink, RunViewer, type VersionFull } from "@/components/admin/intellect";
import { pollJob } from "@/components/admin/jobs";
import {
  Badge, Button, Empty, ErrorNote, Field, Input, Modal, Notice, Panel, Select, Spinner, Table, Tabs, Td, Textarea, Toggle, cx, useAsync,
} from "@/components/ui";
import { api } from "@/lib/api";

type Case = { id: string; name: string; prompt: string; layer_switches: Record<string, boolean>; expected: Record<string, unknown>; origin: string; last_outcome: string; last_run_id: string | null };

function Lab({ version }: { version: VersionFull }) {
  const [tab, setTab] = useState<"run" | "compare" | "cases">("run");
  return (
    <div className="space-y-4">
      <Notice>Protected guardrails remain active in every lab run, whatever switches are set. Lab runs use the configured AI providers and are queued as background jobs.</Notice>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "run", label: "Run a test" }, { value: "compare", label: "Compare runs" }, { value: "cases", label: "Test cases & regression" }]} />
      {tab === "run" && <RunTab version={version} />}
      {tab === "compare" && <CompareTab />}
      {tab === "cases" && <CasesTab version={version} />}
    </div>
  );
}

function LayerSwitches({ version, value, onChange }: { version: VersionFull; value: Record<string, boolean>; onChange: (v: Record<string, boolean>) => void }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {version.layers.map((l) => {
        const on = value[l.code] !== false;
        return (
          <div key={l.id} className="flex items-center justify-between gap-2 rounded border border-line px-2 py-1.5">
            <span className="text-sm"><span className="font-mono text-intellect">{l.code}</span> <span className="text-dim">{l.name}</span>
              {!on && l.protected_count > 0 && <span className="ml-1 text-xs text-green">({l.protected_count} protected still run)</span>}</span>
            <Toggle checked={on} label={`${l.code} ${on ? "on" : "off"}`} onChange={(v) => onChange({ ...value, [l.code]: v })} />
          </div>
        );
      })}
    </div>
  );
}

function switchesPayload(v: Record<string, boolean>) {
  return Object.fromEntries(Object.entries(v).filter(([, on]) => on === false));
}

function RunTab({ version }: { version: VersionFull }) {
  const act = useAction();
  const [prompt, setPrompt] = useState("");
  const [sw, setSw] = useState<Record<string, boolean>>({});
  const [status, setStatus] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  async function go() {
    setRun(null);
    await act.run("run", async () => {
      const { job_id } = await api.post<{ job_id: string }>("/intellect/lab/run", { version_id: version.id, prompt, layer_switches: switchesPayload(sw) });
      const j = await pollJob(job_id, (x) => setStatus(x.status));
      if (j.status !== "done") throw new Error(`Job ${j.status}: ${j.error}`);
      if (j.result?.error) throw new Error(String(j.result.error));
      setRun(await api.get<Run>(`/intellect/runs/${j.result?.run_id}`));
    });
    setStatus("");
  }
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
      <Panel title={`Test problem — ${version.label}`}>
        <div className="space-y-3">
          <Field label="Prompt"><Textarea className="min-h-32" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="e.g. My landlord kept my deposit and says it's my karma. Should I just let it go?" /></Field>
          <div><span className="x-label mb-1.5 block">Layer switches</span><LayerSwitches version={version} value={sw} onChange={setSw} /></div>
          <ErrorNote error={act.error} />
          <Button variant="primary" disabled={!prompt.trim()} loading={act.busy === "run"} onClick={go}>Run framework</Button>
          {act.busy === "run" && <p className="text-xs text-muted">Job {status || "submitted"} — 13 stages plus guardrail audit, one model call each.</p>}
        </div>
      </Panel>
      <Panel title="Result">{run ? <RunViewer run={run} /> : act.busy ? <Spinner /> : <Empty>Run a test to see activated rules, skipped rules with reasons, conflicts and intermediate outputs.</Empty>}</Panel>
    </div>
  );
}

function CompareTab() {
  const runs = useAsync(() => api.get<Run[]>("/intellect/runs?limit=100"));
  const act = useAction();
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [res, setRes] = useState<{ rule_differences: { rule: string; a: string; b: string }[]; a_switches: unknown; b_switches: unknown; a_output: string; b_output: string } | null>(null);
  const opts = [{ value: "", label: "Select run…" }, ...(runs.data ?? []).map((r) => ({ value: r.id, label: `${r.id.slice(0, 8)} · ${r.origin} · ${r.version} · ${r.status} · ${r.prompt.slice(0, 50)}` }))];
  return (
    <Panel title="Compare two runs">
      <ErrorNote error={runs.error || act.error} />
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
        <Field label="Run A"><Select value={a} onChange={(e) => setA(e.target.value)} options={opts} /></Field>
        <Field label="Run B"><Select value={b} onChange={(e) => setB(e.target.value)} options={opts} /></Field>
        <div className="flex items-end"><Button disabled={!a || !b} loading={act.busy === "c"} onClick={async () => { const r = await act.run("c", () => api.post<typeof res>("/intellect/lab/compare", { run_a: a, run_b: b })); if (r) setRes(r); }}>Compare</Button></div>
      </div>
      {res && (
        <div className="mt-4 space-y-4">
          <div className="grid gap-3 md:grid-cols-2 text-xs"><div>A switches: <span className="font-mono">{JSON.stringify(res.a_switches)}</span></div><div>B switches: <span className="font-mono">{JSON.stringify(res.b_switches)}</span></div></div>
          {res.rule_differences.length === 0 ? <Notice tone="ok">Rule states are identical.</Notice> : (
            <Table head={["Rule", "Run A", "Run B"]}>{res.rule_differences.map((d) => <tr key={d.rule}><Td mono>{d.rule}</Td><Td>{d.a}</Td><Td>{d.b}</Td></tr>)}</Table>
          )}
          <div className="grid gap-3 md:grid-cols-2">
            {[res.a_output, res.b_output].map((o, i) => <div key={i}><div className="x-label mb-1">Output {i ? "B" : "A"}</div><div className="whitespace-pre-wrap rounded-md border border-line bg-bg-2 p-3 text-sm">{o || <span className="text-muted">empty</span>}</div></div>)}
          </div>
        </div>
      )}
    </Panel>
  );
}

const EXPECT_KEYS = ["must_apply", "must_not_apply", "must_contain", "must_not_contain"] as const;

function CasesTab({ version }: { version: VersionFull }) {
  const fid = version.framework.id;
  const cases = useAsync(() => api.get<Case[]>(`/intellect/frameworks/${fid}/test-cases`), [fid]);
  const act = useAction();
  const [editing, setEditing] = useState(false);
  const [running, setRunning] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [regression, setRegression] = useState<{ total: number; passed: number; version: string; results: { case: string; passed: boolean; run_id?: string; error?: string }[] } | null>(null);

  async function runCase(c: Case) {
    setRunning(c.id);
    setRun(null);
    await act.run(`case-${c.id}`, async () => {
      const { job_id } = await api.post<{ job_id: string }>("/intellect/lab/run", { version_id: version.id, prompt: c.prompt, layer_switches: c.layer_switches, test_case_id: c.id });
      const j = await pollJob(job_id);
      if (j.status !== "done") throw new Error(`Job ${j.status}: ${j.error}`);
      if (j.result?.error) throw new Error(String(j.result.error));
      setRun(await api.get<Run>(`/intellect/runs/${j.result?.run_id}`));
    });
    setRunning(null);
    cases.reload();
  }

  async function runRegression() {
    setRegression(null);
    await act.run("reg", async () => {
      const { job_id } = await api.post<{ job_id: string }>(`/intellect/frameworks/${fid}/regression`, { version_id: version.id });
      const j = await pollJob(job_id);
      if (j.status !== "done") throw new Error(`Regression job ${j.status}: ${j.error}`);
      setRegression(j.result as unknown as typeof regression);
    });
    cases.reload();
  }

  return (
    <div className="space-y-4">
      <Panel title={`Test cases — ${version.framework.name}`} actions={<>
        <Button size="sm" onClick={() => setEditing(true)}>Add case</Button>
        <Button size="sm" variant="primary" disabled={!cases.data?.length} loading={act.busy === "reg"} onClick={runRegression}>Run regression on {version.label}</Button>
      </>}>
        <ErrorNote error={cases.error || act.error} className="mb-2" />
        {cases.data && (cases.data.length === 0 ? <Empty>No test cases yet. Add cases with expected outcomes to build a regression suite.</Empty> : (
          <Table head={["Name", "Prompt", "Expectations", "Last outcome", ""]}>
            {cases.data.map((c) => (
              <tr key={c.id}>
                <Td className="font-medium">{c.name}<div className="text-xs text-muted">{c.origin}</div></Td>
                <Td className="max-w-[320px] text-xs text-dim">{c.prompt}</Td>
                <Td className="max-w-[260px] font-mono text-[11px] text-muted">{JSON.stringify(c.expected)}</Td>
                <Td><Badge tone={c.last_outcome === "pass" ? "green" : c.last_outcome === "fail" || c.last_outcome === "error" ? "red" : "neutral"}>{c.last_outcome.replace("_", " ")}</Badge>{c.last_run_id && <div className="mt-1"><RunLink id={c.last_run_id} /></div>}</Td>
                <Td className="whitespace-nowrap">
                  <Button size="sm" loading={running === c.id} disabled={!!running} onClick={() => runCase(c)}>Run</Button>
                  <Button size="sm" variant="ghost" className="text-red" onClick={async () => { if (window.confirm(`Delete case "${c.name}"?`)) { await act.run("d", () => api.del(`/intellect/test-cases/${c.id}`)); cases.reload(); } }}>Delete</Button>
                </Td>
              </tr>
            ))}
          </Table>
        ))}
      </Panel>
      {act.busy === "reg" && <Notice>Regression running… each case is a full framework run.</Notice>}
      {regression && (
        <Panel title={`Regression — ${regression.version}`}>
          <p className={cx("mb-2 text-sm", regression.passed === regression.total ? "text-green" : "text-red")}>{regression.passed} of {regression.total} passed</p>
          <ul className="space-y-1 text-sm">{regression.results.map((r, i) => <li key={i}>{r.passed ? "✓" : "✗"} {r.case} {r.run_id && <RunLink id={r.run_id} />} {r.error && <span className="text-red">— {r.error}</span>}</li>)}</ul>
        </Panel>
      )}
      {run && <Panel title="Case run"><RunViewer run={run} /></Panel>}
      {editing && <CaseModal version={version} onClose={() => setEditing(false)} onDone={() => { setEditing(false); cases.reload(); }} />}
    </div>
  );
}

function CaseModal({ version, onClose, onDone }: { version: VersionFull; onClose: () => void; onDone: () => void }) {
  const act = useAction();
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [sw, setSw] = useState<Record<string, boolean>>({});
  const [exp, setExp] = useState<Record<string, string>>({});
  const [maxQ, setMaxQ] = useState("");
  return (
    <Modal open wide onClose={onClose} title="Add test case">
      <div className="space-y-3">
        <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Prompt"><Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} /></Field>
        <div className="grid gap-3 sm:grid-cols-2">
          {EXPECT_KEYS.map((k) => (
            <Field key={k} label={k.replace(/_/g, " ")} hint={k.includes("apply") ? "Comma-separated rule IDs" : "Comma-separated phrases"}>
              <Input value={exp[k] ?? ""} onChange={(e) => setExp({ ...exp, [k]: e.target.value })} />
            </Field>
          ))}
          <Field label="Max questions in reply" hint="HM-20 allows at most one"><Input type="number" min={0} value={maxQ} onChange={(e) => setMaxQ(e.target.value)} /></Field>
        </div>
        <div><span className="x-label mb-1.5 block">Layer switches</span><LayerSwitches version={version} value={sw} onChange={setSw} /></div>
        <ErrorNote error={act.error} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!name || !prompt} loading={act.busy === "s"} onClick={() => act.run("s", async () => {
            const expected: Record<string, unknown> = {};
            for (const k of EXPECT_KEYS) {
              const list = (exp[k] ?? "").split(",").map((s) => s.trim()).filter(Boolean);
              if (list.length) expected[k] = k.includes("apply") ? list.map((s) => s.toUpperCase()) : list;
            }
            if (maxQ !== "") expected.max_questions = Number(maxQ);
            await api.post(`/intellect/frameworks/${version.framework.id}/test-cases`, { name, prompt, layer_switches: switchesPayload(sw), expected });
            onDone();
          })}>Save case</Button></div>
      </div>
    </Modal>
  );
}

export default function LabPage() {
  return (
    <Page>
      <IntellectShell title="Testing Laboratory" subtitle="Run any framework version (published or draft) on a test problem, inspect every stage and rule decision, compare configurations and run regressions.">
        {({ version }) => <Lab version={version} />}
      </IntellectShell>
    </Page>
  );
}
