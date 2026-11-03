"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ContentClass, ExecClass } from "@/lib/types";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

// ------------------------------------------------------------------ layout

export function Panel({ title, actions, children, className, bodyClass, label }: {
  title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string;
  bodyClass?: string; label?: string;
}) {
  return (
    <section className={cx("x-panel flex min-w-0 flex-col", className)} aria-label={label ?? (typeof title === "string" ? title : undefined)}>
      {(title || actions) && (
        <header className="x-hud-head flex items-center justify-between gap-3 border-b border-green/15 px-4 py-2.5">
          <h2 className="x-label flex items-center gap-2 !text-green/90">
            <span aria-hidden className="inline-block h-1.5 w-1.5 rotate-45 bg-green shadow-[0_0_6px_var(--green)]" />
            {title}
          </h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={cx("min-w-0 flex-1 p-4", bodyClass)}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-text">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-dim">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ controls

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger" | "subtle";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({ variant = "subtle", size = "md", loading, className, children, disabled, ...rest }: BtnProps) {
  const base = "inline-flex items-center justify-center gap-2 rounded-[3px] font-medium tracking-wide transition-all disabled:cursor-not-allowed disabled:opacity-40";
  const sizes = { sm: "h-7 px-2.5 text-xs", md: "h-9 px-3.5 text-sm" };
  const variants = {
    primary: "bg-green text-black uppercase font-mono text-[12.5px] tracking-[0.14em] hover:bg-[#6dffb8] shadow-[0_0_24px_-4px_rgba(60,245,154,0.7)] hover:shadow-[0_0_32px_-2px_rgba(60,245,154,0.85)]",
    subtle: "border border-green/20 bg-black/40 text-text hover:border-green/55 hover:text-white hover:shadow-[0_0_14px_-6px_rgba(60,245,154,0.8)]",
    ghost: "text-dim hover:bg-white/5 hover:text-text",
    danger: "border border-red/40 bg-red/10 text-red hover:bg-red/20",
  };
  return (
    <button className={cx(base, sizes[size], variants[variant], className)} disabled={disabled || loading} {...rest}>
      {loading && <Spinner small />}
      {children}
    </button>
  );
}

export function Field({ label, hint, error, children, className }: {
  label: string; hint?: React.ReactNode; error?: string | null; children: React.ReactNode; className?: string;
}) {
  return (
    <label className={cx("block", className)}>
      <span className="x-label mb-1.5 block">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-muted">{hint}</span>}
      {error && <span className="mt-1 block text-xs text-red">{error}</span>}
    </label>
  );
}

const inputCls = "w-full rounded-[3px] border border-green/15 bg-black/50 px-3 py-2 text-sm text-text placeholder:text-muted focus:border-green/60 focus:shadow-[0_0_12px_-4px_rgba(60,245,154,0.6)] focus:outline-none";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputCls, "h-9", props.className)} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(inputCls, "min-h-24 resize-y leading-relaxed", props.className)} />;
}

export function Select({ options, ...props }: React.SelectHTMLAttributes<HTMLSelectElement> & {
  options: { value: string; label: string; disabled?: boolean }[];
}) {
  return (
    <select {...props} className={cx(inputCls, "h-9", props.className)}>
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>
      ))}
    </select>
  );
}

export function Toggle({ checked, onChange, label, disabled, title }: {
  checked: boolean; onChange: (v: boolean) => void; label?: string; disabled?: boolean; title?: string;
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} title={title}
      onClick={() => !disabled && onChange(!checked)}
      className={cx("inline-flex items-center gap-2 text-sm disabled:cursor-not-allowed", disabled && "opacity-60")}>
      <span className={cx("relative h-5 w-9 rounded-full border transition-colors",
        checked ? "border-green/60 bg-green/25" : "border-line-strong bg-bg-2")}>
        <span className={cx("absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all",
          checked ? "left-[18px] bg-green" : "left-0.5 bg-muted")} />
      </span>
      {label && <span className="text-dim">{label}</span>}
    </button>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { value: T; label: React.ReactNode }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 border-b border-line">
      {tabs.map((t) => (
        <button key={t.value} role="tab" aria-selected={value === t.value} onClick={() => onChange(t.value)}
          className={cx("-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
            value === t.value ? "border-green text-green [text-shadow:0_0_8px_rgba(60,245,154,0.5)]" : "border-transparent text-muted hover:text-dim")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 pt-[8vh] backdrop-blur-sm"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
        className={cx("x-panel w-full outline-none", wide ? "max-w-4xl" : "max-w-lg")}>
        <header className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="font-display text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="text-muted hover:text-text" aria-label="Close">✕</button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ feedback

export function Spinner({ small }: { small?: boolean }) {
  return <span role="status" aria-label="Loading" className={cx("inline-block animate-spin rounded-full border-2 border-green/30 border-t-green", small ? "h-3.5 w-3.5" : "h-5 w-5")} />;
}

export function ErrorNote({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div role="alert" className={cx("rounded-md border border-red/30 bg-red/10 px-3 py-2 text-sm text-red", className)}>{msg}</div>;
}

export function Notice({ children, tone = "info", className }: { children: React.ReactNode; tone?: "info" | "warn" | "ok"; className?: string }) {
  const tones = { info: "border-cyan/25 bg-cyan/5 text-dim", warn: "border-amber/30 bg-amber/10 text-amber", ok: "border-green/30 bg-green/10 text-green" };
  return <div className={cx("rounded-md border px-3 py-2 text-sm", tones[tone], className)}>{children}</div>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center text-sm text-muted">{children}</div>;
}

export function Badge({ children, tone = "neutral", className, title }: {
  children: React.ReactNode; tone?: "neutral" | "green" | "cyan" | "blue" | "amber" | "red"; className?: string; title?: string;
}) {
  const tones = {
    neutral: "border-line-strong text-dim",
    green: "border-green/40 text-green bg-green/5",
    cyan: "border-cyan/40 text-cyan bg-cyan/5",
    blue: "border-blue/40 text-blue bg-blue/5",
    amber: "border-amber/40 text-amber bg-amber/10",
    red: "border-red/40 text-red bg-red/10",
  };
  return <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[10.5px] uppercase tracking-wider", tones[tone], className)}>{children}</span>;
}

export function StatusDot({ status }: { status: string }) {
  const map: Record<string, string> = {
    healthy: "bg-green", ready: "bg-green", online: "bg-green", completed: "bg-green", published: "bg-green", pass: "bg-green",
    running: "bg-cyan animate-pulse", processing: "bg-cyan animate-pulse", queued: "bg-cyan", pending: "bg-amber animate-pulse",
    unknown: "bg-muted", unconfigured: "bg-amber", unavailable: "bg-muted", draft: "bg-amber", in_review: "bg-cyan",
    down: "bg-red", failed: "bg-red", fail: "bg-red", error: "bg-red", cancelled: "bg-muted", archived: "bg-muted",
  };
  return <span aria-hidden className={cx("inline-block h-2 w-2 shrink-0 rounded-full", map[status] ?? "bg-muted")} />;
}

const CONTENT_LABEL: Record<ContentClass, [string, "green" | "cyan" | "amber" | "blue" | "red" | "neutral", string]> = {
  computed: ["Computed", "green", "Produced by a solver or deterministic calculation and verified."],
  model_generated: ["Model-generated", "cyan", "Written by an AI model. Treat as reasoning, not as verified computation."],
  assumption: ["Assumption", "amber", "An assumption made to proceed; check it."],
  estimate: ["Estimate", "amber", "An estimate, not a measured value."],
  cached: ["Cached", "blue", "A stored result of an earlier run, not computed now."],
  test: ["Test provider", "red", "Produced by the deterministic test provider. Not a real model."],
};

export function ContentBadge({ cls }: { cls: ContentClass }) {
  const [label, tone, title] = CONTENT_LABEL[cls] ?? [cls, "neutral", ""];
  return <Badge tone={tone} title={title}>{label}</Badge>;
}

const EXEC_LABEL: Record<string, [string, "green" | "cyan" | "amber" | "blue" | "red" | "neutral"]> = {
  hardware: ["Quantum hardware", "blue"],
  cloud_simulator: ["Cloud simulator", "cyan"],
  local_simulator: ["Local quantum simulator", "cyan"],
  classical: ["Classical", "neutral"],
  cached: ["Cached", "blue"],
  test: ["Test", "red"],
};

export function ExecBadge({ cls }: { cls: ExecClass | string }) {
  if (!cls) return null;
  const [label, tone] = EXEC_LABEL[cls] ?? [cls, "neutral"];
  return <Badge tone={tone}>{label}</Badge>;
}

export function Mono({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cx("font-mono text-[12.5px]", className)}>{children}</span>;
}

export function JsonView({ value, maxHeight = 360 }: { value: unknown; maxHeight?: number }) {
  return (
    <pre style={{ maxHeight }} className="overflow-auto rounded-md border border-line bg-bg-2 p-3 font-mono text-[12px] leading-relaxed text-dim">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function KV({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words text-text">{v ?? <span className="text-muted">—</span>}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Table({ head, children, className }: { head: React.ReactNode[]; children: React.ReactNode; className?: string }) {
  return (
    <div className={cx("overflow-x-auto rounded-md border border-line", className)}>
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="bg-white/[0.02]">
          <tr>{head.map((h, i) => <th key={i} className="x-label whitespace-nowrap px-3 py-2 font-normal">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export function Td({ children, className, mono }: { children?: React.ReactNode; className?: string; mono?: boolean }) {
  return <td className={cx("px-3 py-2 align-top", mono && "font-mono text-[12.5px]", className)}>{children}</td>;
}

// ------------------------------------------------------------------ data hook

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fnRef.current());
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading, reload, setData };
}

export function fmtTime(s?: string | null) {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") || s.includes("+") ? s : s + "Z");
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function fmtNum(v: unknown, digits = 4) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toPrecision(digits);
  return String(v);
}
