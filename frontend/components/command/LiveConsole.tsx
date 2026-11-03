"use client";

import { useEffect, useRef, useState } from "react";
import { cx } from "@/components/ui";
import type { ExecEvent } from "@/lib/types";

const ENGINE_TAG: Record<string, string> = {
  system: "text-dim border-dim/30", ai: "text-cyan border-cyan/40", quantum: "text-blue border-blue/40",
  intellect: "text-green border-green/40", classical: "text-classical border-classical/30",
};

function time(at: string | null) {
  if (!at) return "";
  const d = new Date(at.endsWith("Z") || at.includes("+") ? at : at + "Z");
  return d.toLocaleTimeString(undefined, { hour12: false });
}

/** Terminal of stored backend events. Nothing here is generated client-side. */
export function LiveConsole({ events, transport, status }: { events: ExecEvent[]; transport: string; status?: string }) {
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [freshFrom, setFreshFrom] = useState(0);
  const prevLen = useRef(0);

  useEffect(() => {
    const el = box.current;
    if (events.length > prevLen.current) setFreshFrom(prevLen.current);
    prevLen.current = events.length;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) end.current?.scrollIntoView({ block: "end" });
  }, [events.length]);

  const live = transport === "ws" || transport === "poll";
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-2 flex items-center justify-between font-mono text-[10.5px] tracking-[0.12em] text-muted">
        <span>{String(events.length).padStart(4, "0")} EVENTS</span>
        <span className={cx("flex items-center gap-1.5", live && "text-green")}>
          <span className={cx("h-1.5 w-1.5 rounded-full", live ? "bg-green x-pulse" : "bg-muted")} />
          {transport === "ws" ? "LIVE STREAM" : transport === "poll" ? "POLLING" : status ? status.toUpperCase() : "IDLE"}
        </span>
      </div>
      <div ref={box} role="log" aria-live="polite" aria-label="Execution events"
        className="x-scanlines min-h-[220px] flex-1 overflow-y-auto rounded-[3px] border border-green/15 bg-black/70 p-3 font-mono text-[12px] leading-[1.7] shadow-[inset_0_0_30px_-10px_rgba(60,245,154,0.25)]">
        {events.length === 0 ? (
          <div className="text-green/60">
            <span className="text-green/40">x@core:~$</span> awaiting execution — events stream here as the backend records them
            <span className="x-cursor" />
          </div>
        ) : (
          <>
            {events.map((e, i) => (
              <div key={e.seq} className={cx("grid grid-cols-[62px_78px_1fr] gap-x-2 rounded-sm px-1", i >= freshFrom && "x-flash")}>
                <span className="text-green/35">{time(e.at)}</span>
                <span><span className={cx("inline-block min-w-[66px] border px-1 text-center text-[10px] uppercase leading-[16px] tracking-wider", ENGINE_TAG[e.engine] ?? "text-dim border-dim/30")}>{e.engine}</span></span>
                <span className={cx("break-words", /failed|unavailable/.test(e.type) ? "text-amber" : /completed$/.test(e.type) ? "text-[#b8ffd9]" : "text-text")}>{e.message}</span>
              </div>
            ))}
            {live && <div className="px-1 text-green/50"><span className="x-cursor" /></div>}
          </>
        )}
        <div ref={end} />
      </div>
    </div>
  );
}
