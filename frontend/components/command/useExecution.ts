"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, wsBase } from "@/lib/api";
import type { ExecEvent, Execution } from "@/lib/types";

const TERMINAL = new Set(["completed", "failed", "cancelled", "awaiting_input"]);
const REFRESH_ON = /\.(completed|unavailable|skipped)$|^execution\.|^benchmark\./;

/** Live execution state: detail + ordered events from the backend (WebSocket, with polling fallback). */
export function useExecution(id: string | null) {
  const [execution, setExecution] = useState<Execution | null>(null);
  const [events, setEvents] = useState<ExecEvent[]>([]);
  const [transport, setTransport] = useState<"ws" | "poll" | "idle">("idle");
  const [error, setError] = useState<unknown>(null);
  const lastSeq = useRef(0);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadDetail = useCallback(async () => {
    if (!id) return;
    try {
      setExecution(await api.get<Execution>(`/executions/${id}`));
    } catch (e) {
      setError(e);
    }
  }, [id]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(loadDetail, 250);
  }, [loadDetail]);

  const addEvents = useCallback((incoming: ExecEvent[]) => {
    const fresh = incoming.filter((e) => e.seq > lastSeq.current);
    if (!fresh.length) return;
    lastSeq.current = fresh[fresh.length - 1].seq;
    setEvents((prev) => [...prev, ...fresh]);
    if (fresh.some((e) => REFRESH_ON.test(e.type))) scheduleRefresh();
  }, [scheduleRefresh]);

  useEffect(() => {
    setExecution(null);
    setEvents([]);
    setError(null);
    lastSeq.current = 0;
    if (!id) {
      setTransport("idle");
      return;
    }
    let cancelled = false;
    let ws: WebSocket | null = null;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      if (cancelled) return;
      setTransport("poll");
      try {
        addEvents(await api.get<ExecEvent[]>(`/executions/${id}/events?after=${lastSeq.current}`));
        const ex = await api.get<Execution>(`/executions/${id}`);
        if (cancelled) return;
        setExecution(ex);
        if (TERMINAL.has(ex.status)) {
          addEvents(await api.get<ExecEvent[]>(`/executions/${id}/events?after=${lastSeq.current}`));
          setTransport("idle");
          return;
        }
      } catch (e) {
        setError(e);
      }
      pollTimer = setTimeout(poll, 1200);
    };

    (async () => {
      await loadDetail();
      try {
        const { ticket } = await api.post<{ ticket: string }>(`/executions/${id}/ws-ticket`);
        if (cancelled) return;
        ws = new WebSocket(`${wsBase()}/api/ws/executions/${id}?ticket=${encodeURIComponent(ticket)}&after=${lastSeq.current}`);
        let opened = false;
        ws.onopen = () => {
          opened = true;
          setTransport("ws");
        };
        ws.onmessage = (m) => {
          const msg = JSON.parse(m.data);
          if (msg.type === "event") addEvents([msg.event]);
          if (msg.type === "status") {
            setTransport("idle");
            loadDetail();
          }
        };
        ws.onerror = () => {
          if (!opened) poll();
        };
        ws.onclose = () => {
          if (!cancelled && opened) loadDetail();
        };
      } catch {
        poll();
      }
    })();

    return () => {
      cancelled = true;
      ws?.close();
      if (pollTimer) clearTimeout(pollTimer);
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [id, addEvents, loadDetail]);

  return { execution, events, transport, error, reload: loadDetail };
}

export type EngineState = "idle" | "initializing" | "ready" | "processing" | "waiting" | "completed" | "failed" | "unavailable";

/** Derive per-engine state from real plan steps and events. Nothing here is decorative. */
export function engineStates(execution: Execution | null, events: ExecEvent[], available: Record<string, boolean>) {
  const states: Record<"ai" | "quantum" | "intellect", EngineState> = {
    ai: available.ai ? "ready" : "unavailable",
    quantum: available.quantum ? "ready" : "unavailable",
    intellect: available.intellect ? "ready" : "unavailable",
  };
  if (!execution?.plan) return states;
  const steps = execution.plan.steps;
  const engineOf = (k: string) => (k.startsWith("ai") ? "ai" : k.startsWith("quantum") ? "quantum" : k === "intellect" ? "intellect" : null);
  for (const s of steps) {
    const eng = engineOf(s.key);
    if (!eng) continue;
    if (s.status === "planned" && states[eng] !== "unavailable") states[eng] = "waiting";
  }
  for (const e of events) {
    const eng = e.engine as "ai" | "quantum" | "intellect";
    if (!(eng in states)) continue;
    if (/started|submitted|activated|stage_started/.test(e.type)) states[eng] = "processing";
    if (/\.completed$/.test(e.type)) states[eng] = "completed";
    if (/failed$/.test(e.type)) states[eng] = "failed";
    if (/unavailable$/.test(e.type)) states[eng] = "unavailable";
  }
  if (execution.status === "failed") {
    for (const k of Object.keys(states) as (keyof typeof states)[]) if (states[k] === "processing") states[k] = "failed";
  }
  return states;
}
