"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
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

export type SelectOption = { value: string; label: string; disabled?: boolean; description?: string; tag?: string };

/** Matrix-styled listbox with the same API as a native <select> (onChange receives { target: { value } }). */
export function Select({ options, value, onChange, disabled, className, id, "aria-label": ariaLabel, placeholder, menuWidth }: {
  options: SelectOption[];
  value?: string | number | readonly string[];
  onChange?: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  disabled?: boolean; className?: string; id?: string; "aria-label"?: string; placeholder?: string; menuWidth?: number;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number; width: number; maxH: number; up: boolean } | null>(null);
  const typed = useRef({ s: "", t: 0 });
  const listId = useRef(`xsel-${Math.random().toString(36).slice(2, 9)}`).current;
  const current = options.find((o) => o.value === String(value ?? ""));

  const choose = (o: SelectOption | undefined) => {
    if (!o || o.disabled) return;
    onChange?.({ target: { value: o.value }, currentTarget: { value: o.value } } as unknown as React.ChangeEvent<HTMLSelectElement>);
    setOpen(false);
  };
  const move = (from: number, dir: 1 | -1) => {
    for (let i = 1; i <= options.length; i++) {
      const k = (from + dir * i + options.length) % options.length;
      if (!options[k].disabled) return k;
    }
    return from;
  };

  useEffect(() => {
    if (!open) return;
    setActive(Math.max(0, options.findIndex((o) => o.value === String(value ?? ""))));
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!root.current?.contains(t) && !list.current?.contains(t)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open, options, value]);

  // The menu renders in a portal (panels create stacking contexts), positioned against the button.
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const r = btn.current?.getBoundingClientRect();
      if (!r) return;
      const width = Math.min(Math.max(r.width, menuWidth ?? 220), window.innerWidth - 16);
      const left = Math.min(Math.max(8, r.left), window.innerWidth - width - 8);
      const below = window.innerHeight - r.bottom - 12, above = r.top - 12;
      const up = below < 240 && above > below;
      setPos({ left, width, up, top: up ? r.top - 4 : r.bottom + 4, maxH: Math.min(360, up ? above : below) });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open, menuWidth]);

  useEffect(() => {
    if (open) list.current?.querySelector<HTMLElement>(`[data-idx="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  function onKey(e: React.KeyboardEvent) {
    if (disabled) return;
    if (!open && ["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); setOpen(true); return; }
    if (!open) return;
    if (e.key === "Escape") { e.stopPropagation(); setOpen(false); return; }
    if (e.key === "Tab") { setOpen(false); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => move(a, 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => move(a, -1)); }
    else if (e.key === "Home") { e.preventDefault(); setActive(move(-1, 1)); }
    else if (e.key === "End") { e.preventDefault(); setActive(move(options.length, -1)); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(options[active]); }
    else if (e.key.length === 1) {
      const now = Date.now();
      typed.current = { s: (now - typed.current.t < 600 ? typed.current.s : "") + e.key.toLowerCase(), t: now };
      const k = options.findIndex((o) => !o.disabled && o.label.toLowerCase().startsWith(typed.current.s));
      if (k >= 0) setActive(k);
    }
  }

  return (
    <div ref={root} className={cx("relative", className?.includes("w-") ? "" : "w-full")}>
      <button ref={btn} type="button" id={id} disabled={disabled} onClick={() => setOpen((o) => !o)} onKeyDown={onKey}
        role="combobox" aria-haspopup="listbox" aria-expanded={open} aria-controls={listId} aria-label={ariaLabel}
        aria-activedescendant={open ? `${listId}-${active}` : undefined}
        className={cx(inputCls, "group flex h-9 items-center justify-between gap-2 text-left disabled:cursor-not-allowed disabled:opacity-50",
          open && "border-green/70 shadow-[0_0_16px_-4px_rgba(60,245,154,0.7)]", className)}>
        <span className="flex min-w-0 items-center gap-2">
          <span aria-hidden className={cx("h-1.5 w-1.5 shrink-0 rotate-45", current ? "bg-green shadow-[0_0_6px_rgba(60,245,154,0.9)]" : "bg-muted")} />
          <span className={cx("truncate", !current && "text-muted")}>{current?.label ?? placeholder ?? "Select…"}</span>
        </span>
        <span aria-hidden className={cx("font-mono text-[10px] text-green/70 transition-transform", open && "rotate-180")}>▼</span>
      </button>
      {open && pos && createPortal(
        <ul ref={list} id={listId} role="listbox" aria-label={ariaLabel} className="fixed z-[70] overflow-y-auto"
          style={{ left: pos.left, width: pos.width, maxHeight: pos.maxH,
            ...(pos.up ? { bottom: window.innerHeight - pos.top } : { top: pos.top }), background: "rgba(3,8,6,0.96)", border: "1px solid rgba(60,245,154,0.4)", borderRadius: 3, padding: 4,
            boxShadow: "0 0 30px -8px rgba(60,245,154,0.7), 0 20px 40px -10px rgba(0,0,0,0.9)", backdropFilter: "blur(8px)" }}>
          <li aria-hidden className="mb-1 flex items-center justify-between border-b border-green/15 px-2 pb-1 pt-0.5 font-mono text-[9px] tracking-[0.25em] text-green/50">
            <span>SELECT {"//"} {options.filter((o) => !o.disabled).length} AVAILABLE</span><span>↑↓ ⏎</span>
          </li>
          {options.map((o, i) => {
            const selected = o.value === String(value ?? "");
            return (
              <li key={o.value} id={`${listId}-${i}`} data-idx={i} role="option" aria-selected={selected} aria-disabled={o.disabled}
                onMouseEnter={() => !o.disabled && setActive(i)} onMouseDown={(e) => { e.preventDefault(); choose(o); }}
                className={cx("relative flex cursor-pointer items-start gap-2 rounded-[2px] px-2 py-1.5 text-sm transition-colors",
                  o.disabled ? "cursor-not-allowed opacity-35" : i === active ? "bg-green/[0.12] text-white" : "text-dim",
                  selected && "text-green")}>
                <span aria-hidden className={cx("mt-[3px] w-3 shrink-0 font-mono text-[10px]", i === active && !o.disabled ? "text-green" : "text-transparent")}>▸</span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className={cx("truncate", i === active && !o.disabled && "x-phosphor")}>{o.label}</span>
                    {o.tag && <span className="shrink-0 rounded-[2px] border border-cyan/40 px-1 font-mono text-[9px] tracking-wider text-cyan">{o.tag}</span>}
                  </span>
                  {o.description && <span className="mt-0.5 block text-[11px] leading-snug text-muted">{o.description}</span>}
                  {o.disabled && <span className="mt-0.5 block font-mono text-[9.5px] tracking-wider text-muted">UNAVAILABLE</span>}
                </span>
                {selected && <span aria-hidden className="mt-[3px] font-mono text-[10px] text-green">◆</span>}
                {i === active && !o.disabled && <span aria-hidden className="absolute inset-y-1 left-0 w-[2px] bg-green shadow-[0_0_8px_rgba(60,245,154,0.9)]" />}
              </li>
            );
          })}
        </ul>,
        document.body,
      )}
    </div>
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
