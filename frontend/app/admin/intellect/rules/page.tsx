"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Page, useAction } from "@/components/admin/common";
import { IntellectShell, type Layer, type Rule, type VersionFull } from "@/components/admin/intellect";
import { Badge, Button, cx, Empty, ErrorNote, Field, Input, Modal, Panel, Select, Table, Td, Textarea, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function readOnlyReason(r: Rule, status: string) {
  if (r.is_protected) return "Protected guardrail — cannot be changed, disabled or overridden.";
  if (r.origin === "source") return "Original source rule — wording, conditions, priority and status preserved.";
  if (status !== "draft") return "Version is not a draft.";
  return "";
}

function RulesView({ version, reload }: { version: VersionFull; reload: () => void }) {
  const { can } = useAuth();
  const write = can("intellect.write") && version.status === "draft";
  const [layer, setLayer] = useState("");
  const [q, setQ] = useState("");
  const [protOnly, setProtOnly] = useState(false);
  const [addLayer, setAddLayer] = useState(false);
  const [ruleModal, setRuleModal] = useState<Rule | "new" | null>(null);
  const act = useAction();

  const rules = useMemo(() => version.rules.filter((r) =>
    (!layer || r.layer === layer) && (!protOnly || r.is_protected) &&
    (!q || r.rule_code.toLowerCase().includes(q.toLowerCase()) || r.text.toLowerCase().includes(q.toLowerCase()))), [version.rules, layer, q, protOnly]);

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {version.layers.map((l) => (
          <button key={l.id} onClick={() => setLayer(layer === l.code ? "" : l.code)} aria-pressed={layer === l.code}
            className={cx("x-panel p-3 text-left transition-colors", layer === l.code && "border-green/50")}>
            <div className="flex items-center gap-2"><span className="font-mono text-sm text-intellect">{l.code}</span>
              {l.origin !== "source" && <Badge tone="amber">{l.origin}</Badge>}<span className="ml-auto font-mono text-xs text-muted">tier {l.tier}</span></div>
            <div className="mt-1 text-sm font-medium">{l.name}</div>
            <div className="mt-1 text-xs italic text-dim">{l.question}</div>
            <div className="mt-2 flex gap-3 font-mono text-[11px] text-muted"><span>{l.rule_count} rules</span>{l.protected_count > 0 && <span className="text-green">🔒 {l.protected_count}</span>}{l.declared_rule_count != null && l.declared_rule_count !== l.rule_count && <span className="text-red">declared {l.declared_rule_count}</span>}</div>
          </button>
        ))}
      </div>
      {layer && (() => { const l = version.layers.find((x) => x.code === layer) as Layer; return (
        <Panel title={`${l.code} — ${l.name}`}>
          <p className="text-sm text-dim">{l.description}</p>
          <p className="mt-2 text-xs text-muted">Conflict tier basis: {l.tier_basis}{l.source_page ? ` · source page ${l.source_page}` : ""}</p>
        </Panel>); })()}
      <Panel title={`Rules (${rules.length} of ${version.rules.length})`}
        actions={write && <><Button size="sm" onClick={() => setAddLayer(true)}>Add custom layer</Button><Button size="sm" variant="primary" onClick={() => setRuleModal("new")}>Add custom rule</Button></>}>
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <Field label="Layer" className="w-44"><Select value={layer} onChange={(e) => setLayer(e.target.value)} options={[{ value: "", label: "All layers" }, ...version.layers.map((l) => ({ value: l.code, label: `${l.code} — ${l.name}` }))]} /></Field>
          <Field label="Search" className="min-w-48 flex-1"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ID or text" /></Field>
          <Toggle checked={protOnly} onChange={setProtOnly} label="Protected only" />
        </div>
        <ErrorNote error={act.error} className="mb-2" />
        {rules.length === 0 ? <Empty>No rules match.</Empty> : (
          <Table head={["ID", "P", "Prov.", "Rule", "Applies when", "Not when", "Status", ""]}>
            {rules.map((r) => {
              const reason = readOnlyReason(r, version.status);
              return (
                <tr key={r.id} className={cx(!r.is_active && "opacity-60")}>
                  <Td className="whitespace-nowrap"><Link href={`/admin/intellect/rules/${r.id}`} className="font-mono text-cyan hover:underline">{r.rule_code}</Link>{r.is_protected && <span title="Protected guardrail" className="ml-1">🔒</span>}</Td>
                  <Td mono>P{r.priority}</Td>
                  <Td mono className="text-muted">{r.provenance}</Td>
                  <Td className="min-w-[280px] max-w-[420px] text-[13px] leading-snug">{r.text}{r.source_marker && <div className="mt-1"><Badge tone="green">{r.source_marker}</Badge></div>}</Td>
                  <Td className="min-w-[180px] max-w-[260px] text-xs text-dim">{r.applies_when}</Td>
                  <Td className="min-w-[180px] max-w-[260px] text-xs text-dim">{r.not_when}</Td>
                  <Td className="whitespace-nowrap"><Badge tone={r.origin === "source" ? "neutral" : "amber"}>{r.origin}</Badge> {r.is_active ? <Badge tone="green">active</Badge> : <Badge>inactive</Badge>}</Td>
                  <Td className="whitespace-nowrap">
                    {r.editable && write ? (
                      <div className="flex gap-1">
                        <Button size="sm" variant="ghost" onClick={() => setRuleModal(r)}>Edit</Button>
                        <Button size="sm" variant="ghost" onClick={async () => { await act.run("t", () => api.patch(`/intellect/rules/${r.id}`, { is_active: !r.is_active })); reload(); }}>{r.is_active ? "Deactivate" : "Activate"}</Button>
                        <Button size="sm" variant="ghost" className="text-red" onClick={async () => { if (window.confirm(`Delete ${r.rule_code}?`)) { await act.run("d", () => api.del(`/intellect/rules/${r.id}`)); reload(); } }}>Delete</Button>
                      </div>
                    ) : <span className="text-xs text-muted" title={reason}>read-only</span>}
                  </Td>
                </tr>
              );
            })}
          </Table>
        )}
      </Panel>
      {addLayer && <AddLayer version={version} onClose={() => setAddLayer(false)} onDone={() => { setAddLayer(false); reload(); }} />}
      {ruleModal && <RuleModal version={version} rule={ruleModal === "new" ? null : ruleModal} defaultLayer={layer} onClose={() => setRuleModal(null)} onDone={() => { setRuleModal(null); reload(); }} />}
    </div>
  );
}

function AddLayer({ version, onClose, onDone }: { version: VersionFull; onClose: () => void; onDone: () => void }) {
  const act = useAction();
  const [f, setF] = useState({ code: "", name: "", question: "", description: "", tier: 4, after: String(version.pipeline.length) });
  return (
    <Modal open onClose={onClose} title="Add custom layer">
      <div className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <Field label="Code"><Input maxLength={4} value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase() })} /></Field>
          <Field label="Name" className="col-span-2"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        </div>
        <Field label="Question it answers"><Input value={f.question} onChange={(e) => setF({ ...f, question: e.target.value })} /></Field>
        <Field label="Description"><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="Conflict tier" hint="Tier 1 is reserved for protected guardrails; custom layers can never outrank them.">
          <Select value={String(f.tier)} onChange={(e) => setF({ ...f, tier: Number(e.target.value) })} options={version.hierarchy.filter((h) => h.rank >= 2).map((h) => ({ value: String(h.rank), label: `${h.rank} — ${h.raw}` })).concat(version.hierarchy.length ? [] : [2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: String(n) })))} /></Field>
        <Field label="Insert stage after"><Select value={f.after} onChange={(e) => setF({ ...f, after: e.target.value })} options={[{ value: "0", label: "(start)" }, ...version.pipeline.map((s) => ({ value: String(s.position), label: `${s.position}. ${s.source_label}` }))]} /></Field>
        <ErrorNote error={act.error} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={act.busy === "a"} onClick={() => act.run("a", async () => {
            await api.post(`/intellect/versions/${version.id}/layers`, { code: f.code, name: f.name, question: f.question, description: f.description, tier: f.tier, insert_after_position: Number(f.after) }); onDone();
          })}>Add layer</Button></div>
      </div>
    </Modal>
  );
}

function RuleModal({ version, rule, defaultLayer, onClose, onDone }: { version: VersionFull; rule: Rule | null; defaultLayer: string; onClose: () => void; onDone: () => void }) {
  const act = useAction();
  const firstLayer = version.layers.find((l) => l.code === defaultLayer) ?? version.layers.find((l) => l.origin !== "source") ?? version.layers[0];
  const [f, setF] = useState({ layer_id: firstLayer?.id ?? "", rule_code: rule?.rule_code ?? "", text: rule?.text ?? "", applies_when: rule?.applies_when ?? "", not_when: rule?.not_when ?? "", priority: rule?.priority ?? 2, provenance: rule?.provenance ?? "custom" });
  return (
    <Modal open wide onClose={onClose} title={rule ? `Edit ${rule.rule_code}` : "Add custom rule"}>
      <div className="space-y-3">
        {!rule && <p className="text-xs text-muted">New custom rules start inactive. Activate them after review.</p>}
        <div className="grid gap-3 sm:grid-cols-3">
          {!rule && <Field label="Layer"><Select value={f.layer_id} onChange={(e) => setF({ ...f, layer_id: e.target.value })} options={version.layers.map((l) => ({ value: l.id, label: `${l.code} — ${l.name}` }))} /></Field>}
          {!rule && <Field label="Rule ID" hint="e.g. SR-01"><Input value={f.rule_code} onChange={(e) => setF({ ...f, rule_code: e.target.value.toUpperCase() })} /></Field>}
          <Field label="Priority"><Select value={String(f.priority)} onChange={(e) => setF({ ...f, priority: Number(e.target.value) })} options={[1, 2, 3, 4].map((p) => ({ value: String(p), label: `P${p}` }))} /></Field>
        </div>
        <Field label="Rule"><Textarea value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} /></Field>
        <Field label="Applies when"><Textarea className="min-h-16" value={f.applies_when} onChange={(e) => setF({ ...f, applies_when: e.target.value })} /></Field>
        <Field label="Not when"><Textarea className="min-h-16" value={f.not_when} onChange={(e) => setF({ ...f, not_when: e.target.value })} /></Field>
        <Field label="Provenance label"><Input maxLength={16} value={f.provenance} onChange={(e) => setF({ ...f, provenance: e.target.value })} /></Field>
        <ErrorNote error={act.error} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={act.busy === "s"} onClick={() => act.run("s", async () => {
            if (rule) await api.patch(`/intellect/rules/${rule.id}`, { text: f.text, applies_when: f.applies_when, not_when: f.not_when, priority: f.priority, provenance: f.provenance });
            else await api.post(`/intellect/versions/${version.id}/rules`, f);
            onDone();
          })}>Save</Button></div>
      </div>
    </Modal>
  );
}

export default function RulesPage() {
  return (
    <Page>
      <IntellectShell title="Layers & Rules" subtitle="Every rule is its own database record with source ID, priority, provenance, conditions, page reference and SHA-256 of its source text.">
        {({ version, reload }) => <RulesView version={version} reload={reload} />}
      </IntellectShell>
    </Page>
  );
}
