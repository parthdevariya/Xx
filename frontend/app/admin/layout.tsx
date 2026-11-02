"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { cx } from "@/components/ui";
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
    <nav aria-label="Administration" className="space-y-5">
      {NAV.map((g) => {
        const items = g.items.filter((i) => can(i.perm));
        if (!items.length) return null;
        return (
          <div key={g.group}>
            <div className="x-label mb-1.5 px-2">{g.group}</div>
            <ul className="space-y-0.5">
              {items.map((i) => {
                // Longest matching href wins, so /admin/intellect doesn't stay lit on its sub-pages.
                const longer = ALL_HREFS.some((h) => h.length > i.href.length && (path === h || path.startsWith(h + "/")));
                const active = i.href === "/admin" ? path === "/admin"
                  : (path === i.href || path.startsWith(i.href + "/")) && !longer;
                return (
                  <li key={i.href}>
                    <Link href={i.href} onClick={onNavigate}
                      className={cx("block rounded-md px-2 py-1.5 text-sm transition-colors",
                        active ? "bg-green/10 text-green" : "text-dim hover:bg-white/5 hover:text-text")}>
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
  return (
    <RequireAuth permission="dashboard.read">
      <div className="min-h-dvh bg-bg">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-line bg-bg/90 px-4 backdrop-blur">
          <div className="flex items-center gap-3">
            <button className="rounded p-1 text-dim lg:hidden" onClick={() => setOpen(!open)} aria-label="Toggle navigation">☰</button>
            <Link href="/" aria-label="Command centre"><Wordmark /></Link>
            <span className="x-label hidden sm:inline">Administration</span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <Link href="/" className="text-dim hover:text-green">Command centre →</Link>
            <span className="hidden text-muted md:inline">{user?.email} · {user?.role_name}</span>
            <button onClick={logout} className="text-muted hover:text-text">Sign out</button>
          </div>
        </header>
        <div className="flex">
          <aside className={cx("fixed inset-y-14 left-0 z-20 w-60 overflow-y-auto border-r border-line bg-bg p-3 transition-transform lg:sticky lg:top-14 lg:h-[calc(100dvh-3.5rem)] lg:translate-x-0",
            open ? "translate-x-0" : "-translate-x-full")}>
            <Nav onNavigate={() => setOpen(false)} />
          </aside>
          <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-8">{children}</main>
        </div>
      </div>
    </RequireAuth>
  );
}
