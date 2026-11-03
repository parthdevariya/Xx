"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { cx } from "@/components/ui";
import { GlitchText } from "@/components/fx/GlitchText";
import { MatrixRain } from "@/components/fx/MatrixRain";
import { Switchboard } from "@/components/admin/Switchboard";
import { Clock, TelemetryStrip } from "@/components/fx/Telemetry";
import { Wordmark } from "@/components/XMark";
import { useAuth } from "@/lib/auth";

const NAV: { group: string; items: { href: string; label: string; perm: string }[] }[] = [
  { group: "Overview", items: [{ href: "/admin", label: "Dashboard", perm: "dashboard.read" }] },
  {
    group: "Engines",
    items: [
      { href: "/admin/ai", label: "AI Management", perm: "ai.read" },
      { href: "/admin/quantum", label: "Quantum Management", perm: "quantum.read" },
    ],
  },
  {
    group: "Intellect",
    items: [
      { href: "/admin/intellect", label: "Framework Library", perm: "intellect.read" },
      { href: "/admin/intellect/rules", label: "Layers & Rules", perm: "intellect.read" },
      { href: "/admin/intellect/pipeline", label: "Execution Pipeline", perm: "intellect.read" },
      { href: "/admin/intellect/swarm", label: "Swarm Intelligence", perm: "dashboard.read" },
      { href: "/admin/intellect/guardrails", label: "Guardrails", perm: "intellect.read" },
      { href: "/admin/intellect/conflicts", label: "Conflict Resolution", perm: "intellect.read" },
      { href: "/admin/intellect/lab", label: "Testing Laboratory", perm: "intellect.test" },
      { href: "/admin/intellect/versions", label: "Versions", perm: "intellect.read" },
      { href: "/admin/intellect/builder", label: "Import & Builder", perm: "intellect.write" },
      { href: "/admin/intellect/library", label: "Reference Library", perm: "intellect.read" },
      { href: "/admin/intellect/logs", label: "Execution Logs", perm: "intellect.read" },
    ],
  },
  {
    group: "Platform",
    items: [
      { href: "/admin/scenarios", label: "Scenarios", perm: "scenarios.write" },
      { href: "/admin/policies", label: "Orchestration Policies", perm: "dashboard.read" },
      { href: "/admin/users", label: "Users & Access", perm: "users.read" },
      { href: "/admin/audit", label: "Audit Log", perm: "audit.read" },
    ],
  },
];

const ALL_HREFS = NAV.flatMap((g) => g.items.map((i) => i.href));

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  const { can } = useAuth();
  return (
    <nav aria-label="Administration" className="space-y-5 font-mono">
      {NAV.map((g, gi) => {
        const items = g.items.filter((i) => can(i.perm));
        if (!items.length) return null;
        return (
          <div key={g.group}>
            <div className="mb-1.5 px-2 text-[10px] tracking-[0.22em] text-green/45">
              {String(gi).padStart(2, "0")} {"//"} {g.group.toUpperCase()}
            </div>
            <ul className="space-y-0.5 border-l border-green/10 pl-1">
              {items.map((i) => {
                // Longest matching href wins, so /admin/intellect doesn't stay lit on its sub-pages.
                const longer = ALL_HREFS.some((h) => h.length > i.href.length && (path === h || path.startsWith(h + "/")));
                const active = i.href === "/admin" ? path === "/admin"
                  : (path === i.href || path.startsWith(i.href + "/")) && !longer;
                return (
                  <li key={i.href}>
                    <Link href={i.href} onClick={onNavigate} aria-current={active ? "page" : undefined}
                      className={cx("group flex items-center gap-2 rounded-[3px] px-2 py-1.5 text-[12.5px] transition-colors",
                        active ? "bg-green/10 text-green [text-shadow:0_0_8px_rgba(60,245,154,0.45)]" : "text-dim hover:bg-green/[0.04] hover:text-text")}>
                      <span aria-hidden className={cx("text-[10px]", active ? "text-green" : "text-green/25 group-hover:text-green/60")}>
                        {active ? "▸" : "›"}
                      </span>
                      {i.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const hdr = useRef<HTMLElement>(null);
  // The header grows with the switchboard; keep the sidebar offset in step with its real height.
  useEffect(() => {
    const el = hdr.current;
    if (!el) return;
    const set = () => document.documentElement.style.setProperty("--x-hdr", `${el.offsetHeight}px`);
    set();
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => ro.disconnect();
  });
  return (
    <RequireAuth permission="dashboard.read">
      <div className="x-grid x-vignette min-h-dvh">
        <MatrixRain opacity={0.07} density={0.6} />
        <div className="x-above-rain">
          <header ref={hdr} className="sticky top-0 z-30 border-b border-green/15 bg-bg/90 backdrop-blur">
            <div className="flex h-14 items-center justify-between gap-3 px-4">
              <div className="flex items-center gap-3">
                <button className="rounded p-1 text-green/70 lg:hidden" onClick={() => setOpen(!open)} aria-label="Toggle navigation" aria-expanded={open}>☰</button>
                <Link href="/" aria-label="Command centre"><Wordmark /></Link>
                <span className="hidden border-l border-green/20 pl-3 font-mono text-[11px] tracking-[0.3em] sm:inline x-phosphor">
                  <GlitchText text="MASTER CONTROL" />
                </span>
              </div>
              <div className="flex items-center gap-4 text-sm">
                <Clock />
                <span className="hidden font-mono text-[11px] text-muted md:inline">
                  OPERATOR <span className="text-dim">{user?.email}</span> <span className="text-green/60">[{user?.role_name}]</span>
                </span>
                <Link href="/" className="font-mono text-[11px] tracking-[0.12em] text-dim hover:text-green">COMMAND CENTRE →</Link>
                <button onClick={logout} className="font-mono text-[11px] tracking-[0.12em] text-muted hover:text-text">SIGN OUT</button>
              </div>
            </div>
            <TelemetryStrip />
            <Switchboard />
          </header>
          <div className="flex">
            <aside className={cx("fixed top-[var(--x-hdr,6.4rem)] bottom-0 left-0 z-20 w-60 overflow-y-auto border-r border-green/10 bg-bg/95 p-3 transition-transform lg:sticky lg:top-[var(--x-hdr,6.4rem)] lg:h-[calc(100dvh-var(--x-hdr,6.4rem))] lg:translate-x-0",
              open ? "translate-x-0" : "-translate-x-full")}>
              <Nav onNavigate={() => setOpen(false)} />
              <div className="mt-6 border-t border-green/10 px-2 pt-3 font-mono text-[9.5px] leading-relaxed tracking-[0.14em] text-green/35">
                X // HYBRID COMPUTATIONAL INTELLIGENCE<br />AI · QUANTUM · INTELLECT
              </div>
            </aside>
            <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-8">{children}</main>
          </div>
        </div>
      </div>
    </RequireAuth>
  );
}
