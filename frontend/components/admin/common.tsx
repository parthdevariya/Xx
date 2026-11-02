"use client";

import { Suspense, useCallback, useState } from "react";
import { Badge, cx, Spinner } from "@/components/ui";

export function Page({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<Spinner />}>{children}</Suspense>;
}

/** Wraps an async action with busy + error state. */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(key);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e);
      return undefined;
    } finally {
      setBusy(null);
    }
  }, []);
  return { busy, error, setError, run };
}

export function Stat({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className="x-panel p-4">
      <div className="x-label">{label}</div>
      <div className={cx("mt-1 font-display text-2xl font-semibold", tone)}>{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function HealthBadge({ status }: { status: string }) {
  const tone = status === "healthy" || status === "online" ? "green" : status === "down" || status === "failed" ? "red"
    : status === "unconfigured" || status === "unknown" ? "amber" : "neutral";
  return <Badge tone={tone}>{status}</Badge>;
}

export function parseJson<T = unknown>(text: string, label: string): T {
  try {
    return JSON.parse(text) as T;
  } catch (e) {
    throw new Error(`${label} is not valid JSON: ${(e as Error).message}`);
  }
}

export function Checks({ options, value, onChange }: { options: { value: string; label: string }[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = value.includes(o.value);
        return (
          <button type="button" key={o.value} aria-pressed={on}
            onClick={() => onChange(on ? value.filter((x) => x !== o.value) : [...value, o.value])}
            className={cx("rounded border px-2 py-1 font-mono text-[11px]", on ? "border-green/50 bg-green/10 text-green" : "border-line-strong text-muted hover:text-dim")}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Bars({ data, height = 120 }: { data: { label: string; value: number }[]; height?: number }) {
  if (!data.length) return null;
  const max = Math.max(...data.map((d) => d.value), 1);
  const slots = Math.max(data.length, 30); // fixed 30-day scale, most recent on the right
  const w = 100 / slots;
  const offset = slots - data.length;
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="h-32 w-full" role="img"
      aria-label={`Executions per day: ${data.map((d) => `${d.label} ${d.value}`).join(", ")}`}>
      {data.map((d, i) => {
        const h = (d.value / max) * (height - 10);
        return (
          <g key={d.label}>
            <rect x={(i + offset) * w + w * 0.15} y={height - h} width={w * 0.7} height={h} fill="var(--green)" opacity={0.75}>
              <title>{`${d.label}: ${d.value}`}</title>
            </rect>
          </g>
        );
      })}
    </svg>
  );
}
