"use client";

import { useEffect, useRef } from "react";
import { cx } from "@/components/ui";
import type { ExecEvent } from "@/lib/types";

const ENGINE_COLOR: Record<string, string> = {
  system: "text-dim", ai: "text-cyan", quantum: "text-blue", intellect: "text-green", classical: "text-classical",
};

function time(at: string | null) {
  if (!at) return "";
  const d = new Date(at.endsWith("Z") || at.includes("+") ? at : at + "Z");
  return d.toLocaleTimeString(undefined, { hour12: false });
}

/** Every line is a stored backend event. Nothing is generated client-side. */
export function LiveConsole({ events, transport, status }: { events: ExecEvent[]; transport: string; status?: string }) {
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) end.current?.scrollIntoView({ block: "end" });
  }, [events.length]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-2 flex items-center justify-between text-[11px] text-muted">
        <span>{events.length} events</span>
        <span className="font-mono">{transport === "ws" ? "● live stream" : transport === "poll" ? "● polling" : status ? `■ ${status}` : "idle"}</span>
      </div>
      <div ref={box} role="log" aria-live="polite" aria-label="Execution events"
        className="min-h-[220px] flex-1 overflow-y-auto rounded-md border border-line bg-black/40 p-3 font-mono text-[12px] leading-[1.65]">
        {events.length === 0 ? (
          <div className="text-muted">Waiting for an execution. Events appear here as the backend records them.</div>
        ) : (
          events.map((e) => (
            <div key={e.seq} className="grid grid-cols-[64px_74px_1fr] gap-x-2">
              <span className="text-muted">{time(e.at)}</span>
              <span className={cx("uppercase", ENGINE_COLOR[e.engine] ?? "text-dim")}>{e.engine}</span>
              <span className={cx("break-words", /failed|unavailable/.test(e.type) ? "text-amber" : "text-text")}>{e.message}</span>
            </div>
          ))
        )}
        <div ref={end} />
      </div>
    </div>
  );
}
