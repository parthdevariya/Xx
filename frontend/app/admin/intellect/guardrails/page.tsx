"use client";

import Link from "next/link";
import { Page } from "@/components/admin/common";
import { IntellectShell, type VersionFull } from "@/components/admin/intellect";
import { Badge, Empty, Notice, Panel } from "@/components/ui";

function Guardrails({ version }: { version: VersionFull }) {
  const kinds = Object.fromEntries(version.guardrails.map((g) => [g.rule_code, g]));
  const rules = version.rules.filter((r) => r.is_protected);
  const note = version.meta?.hard_limit_note as string | undefined;
  return (
    <div className="space-y-4">
      <Notice tone="ok">
        These rules cannot be disabled, edited, deleted, re-prioritised or outranked by any role, layer switch, custom rule, custom layer or setting.
        Protection is enforced by database constraints and triggers, by the service layer, and by the pipeline, which runs them even when their layer is switched off.
      </Notice>
      {note && <p className="text-sm text-dim">{note}</p>}
      {rules.length === 0 ? <Empty>This version has no protected rules.</Empty> : (
        <div className="grid gap-3 lg:grid-cols-2">
          {rules.map((r) => {
            const g = kinds[r.rule_code];
            return (
              <Panel key={r.id} title={<span className="flex items-center gap-2 normal-case tracking-normal"><span>🔒</span><Link href={`/admin/intellect/rules/${r.id}`} className="font-mono text-sm text-cyan hover:underline">{r.rule_code}</Link><span className="text-sm text-text">{r.layer_name}</span></span>}
                actions={<Badge tone={g?.kind === "hard_limit" ? "red" : "green"}>{g?.kind === "hard_limit" ? "hard limit" : "always on"}</Badge>}>
                <p className="text-sm leading-relaxed">{r.text}</p>
                <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                  <div><div className="x-label mb-0.5">Applies when</div><p className="text-dim">{r.applies_when}</p></div>
                  <div><div className="x-label mb-0.5">Not when</div><p className="text-dim">{r.not_when}</p></div>
                </div>
                {g && <p className="mt-3 text-xs text-muted">Basis: {g.source_basis}</p>}
              </Panel>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function GuardrailsPage() {
  return (
    <Page>
      <IntellectShell title="Guardrails" subtitle="Protected, read-only view of the always-on rules.">
        {({ version }) => <Guardrails version={version} />}
      </IntellectShell>
    </Page>
  );
}
