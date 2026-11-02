"use client";

import { Badge, cx, Empty } from "@/components/ui";
import { MODE_LABELS, type Scenario } from "@/lib/types";

const ENGINE_TONE: Record<string, "cyan" | "blue" | "green" | "neutral"> = {
  ai: "cyan", quantum: "blue", intellect: "green", classical: "neutral",
};

export function ScenarioLibrary({ scenarios, selected, onSelect, demoOnly }: {
  scenarios: Scenario[]; selected: string | null; onSelect: (s: Scenario) => void; demoOnly: boolean;
}) {
  const list = demoOnly ? scenarios.filter((s) => s.is_demo) : scenarios;
  if (!list.length) return <Empty>No published scenarios{demoOnly ? " marked for demonstration" : ""}.</Empty>;
  const groups = list.reduce<Record<string, Scenario[]>>((acc, s) => {
    (acc[s.category.name] ||= []).push(s);
    return acc;
  }, {});
  return (
    <div className="space-y-5">
      {Object.entries(groups).map(([cat, items]) => (
        <div key={cat}>
          <div className="x-label mb-2">{cat}</div>
          <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
            {items.map((s) => (
              <button key={s.slug} onClick={() => onSelect(s)} aria-pressed={selected === s.slug}
                className={cx("group rounded-lg border p-3 text-left transition-colors",
                  selected === s.slug ? "border-green/50 bg-green/[0.06]" : "border-line bg-white/[0.015] hover:border-line-strong")}>
                <div className="flex items-start justify-between gap-2">
                  <div className="font-display text-[14.5px] font-medium text-text">{s.name}</div>
                  {s.is_demo && <Badge tone="green">Demo</Badge>}
                </div>
                <p className="mt-1 text-[12.5px] leading-snug text-dim">{s.tagline}</p>
                <div className="mt-2.5 flex flex-wrap gap-1">
                  {s.engines.map((e) => <Badge key={e} tone={ENGINE_TONE[e] ?? "neutral"}>{e}</Badge>)}
                </div>
                <div className="mt-2 text-[11.5px] text-muted">
                  <span className="text-dim">Output:</span> {s.expected_output}
                </div>
                <div className="mt-1 text-[11px] text-muted">{s.modes.map((m) => MODE_LABELS[m] ?? m).join(" · ")}</div>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
