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
          <div className="mb-2 flex items-center gap-2 font-mono text-[10px] tracking-[0.2em] text-green/55">
            <span aria-hidden className="h-px w-4 bg-green/40" />{cat.toUpperCase()}<span aria-hidden className="h-px flex-1 bg-green/10" />
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
            {items.map((s) => (
              <button key={s.slug} onClick={() => onSelect(s)} aria-pressed={selected === s.slug}
                className={cx("group relative rounded-[3px] border p-3 text-left transition-all",
                  selected === s.slug
                    ? "border-green/60 bg-green/[0.07] shadow-[0_0_22px_-8px_rgba(60,245,154,0.8),inset_0_0_18px_-10px_rgba(60,245,154,0.6)]"
                    : "border-green/10 bg-black/40 hover:border-green/35 hover:shadow-[0_0_16px_-8px_rgba(60,245,154,0.7)]")}>
                <span aria-hidden className={cx("absolute left-0 top-0 h-2.5 w-2.5 border-l border-t transition-colors",
                  selected === s.slug ? "border-green" : "border-green/30 group-hover:border-green/70")} />
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
