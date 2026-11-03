"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, ContentBadge, ErrorNote, Select, cx } from "@/components/ui";
import { api } from "@/lib/api";
import type { ContentClass, ExecEvent } from "@/lib/types";

export type SwarmState = {
  stages: { name: string; status: string; detail?: string }[];
  graph: { entities: { id: string; name: string; type: string; summary: string }[]; relations: { source: string; target: string; type: string }[];
    prediction_question: string; key_variables: string[] } | null;
  agents: { id: string; name: string; entity_id: string; role: string; persona: string; stance: number; initial_stance: number;
    influence: number; platform: string; interests: string[]; memory: string[] }[];
  posts: { id: string; platform: string; round: number; author: string; author_name: string; content: string; kind: string;
    parent: string | null; likes: number; dislikes: number; reposts: number; comments: number }[];
  actions: { round: number; platform: string; agent_id: string; action: string; target: string; content: string; post_id: string | null }[];
  rounds: { round: number; platform: string; actions: number; mean_stance: number; polarisation: number; by_action: Record<string, number> }[];
  metrics: { stance_start: number; stance_end: number; polarisation_start: number; polarisation_end: number; action_totals: Record<string, number>;
    largest_shifts: { agent: string; from: number; to: number; delta: number }[]; most_engaged: { agent: string; engagement: number }[];
    top_posts: { id: string; author: string; platform: string; content: string; likes: number; reposts: number; comments: number }[];
    edges: { source: string; target: string; kind: string; weight: number }[] } | null;
  report: { headline: string; prediction: string; confidence: string; drivers: string[]; turning_points: string[]; minority_views: string[];
    risks: string[]; recommendation: string } | null;
  stance_axis?: string; models: string[]; test_provider: boolean; error?: string; config: { agents: number; rounds: number };
};

const GOLD = "#f5c542";
const TYPE_COLOR: Record<string, string> = { person: "#45d9f5", group: "#7c8cff", organisation: "#c792ea", institution: "#c792ea",
  concept: "#3cf59a", event: "#ffb84d", place: "#93a39b", resource: "#93a39b" };
const ACTION_GLYPH: Record<string, string> = { CREATE_POST: "✎ posted", QUOTE_POST: "❝ quoted", CREATE_COMMENT: "↳ commented", LIKE_POST: "♥ liked",
  DISLIKE_POST: "▼ disliked", REPOST: "⟳ reposted", FOLLOW: "+ followed", MUTE: "⊘ muted", DO_NOTHING: "· idle" };

function stanceColor(s: number) {
  const t = Math.max(-1, Math.min(1, s));
  if (t >= 0) return `rgb(${Math.round(150 - 90 * t)}, ${Math.round(160 + 85 * t)}, ${Math.round(155 - 1 * t)})`;
  return `rgb(${Math.round(150 + 105 * -t)}, ${Math.round(160 - 65 * -t)}, ${Math.round(155 - 50 * -t)})`;
}

// ------------------------------------------------------------------ step tracker

function Steps({ s }: { s: SwarmState }) {
  return (
    <ol className="grid grid-cols-5 gap-1">
      {s.stages.map((st, i) => {
        const active = st.status === "running", done = st.status === "done", avail = st.status === "available", failed = st.status === "failed";
        return (
          <li key={st.name} className="relative">
            <div className={cx("relative overflow-hidden rounded-[3px] border px-2 py-2 transition-all",
              done ? "border-[#f5c542]/60 bg-[#f5c542]/[0.07]" : active ? "border-[#f5c542] bg-[#f5c542]/[0.12]" : avail ? "border-green/50 bg-green/[0.06]" : failed ? "border-red/50" : "border-line")}
              style={active ? { boxShadow: `0 0 18px -4px ${GOLD}` } : undefined}>
              {active && <motion.div aria-hidden className="absolute inset-y-0 w-1/3" style={{ background: `linear-gradient(90deg, transparent, ${GOLD}40, transparent)` }}
                animate={{ left: ["-35%", "110%"] }} transition={{ duration: 1.4, repeat: Infinity, ease: "linear" }} />}
              <div className="relative flex items-center gap-1.5">
                <span className="font-mono text-[10px]" style={{ color: done || active ? GOLD : avail ? "#3cf59a" : "#64716b" }}>{String(i + 1).padStart(2, "0")}</span>
                <span className={cx("truncate text-[12px]", done || active || avail ? "text-text" : "text-muted")}>{st.name}</span>
              </div>
              <div className="relative mt-0.5 truncate font-mono text-[9.5px] tracking-wider text-muted" title={st.detail}>
                {failed ? "FAILED" : active ? "RUNNING…" : done ? (st.detail ?? "DONE") : avail ? "AVAILABLE" : "PENDING"}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// ------------------------------------------------------------------ force graph

type N = { id: string; kind: "entity" | "agent"; label: string; color: string; r: number; x: number; y: number; vx: number; vy: number };

function useForce(nodes: N[], links: { s: string; t: string; strength: number }[], w: number, h: number, reduced: boolean) {
  const [, tick] = useState(0);
  const store = useRef<Map<string, N>>(new Map());
  const map = store.current;
  for (const n of nodes) {
    const prev = map.get(n.id);
    if (prev) Object.assign(prev, { label: n.label, color: n.color, r: n.r });
    else map.set(n.id, { ...n, x: w / 2 + (Math.random() - 0.5) * w * 0.6, y: h / 2 + (Math.random() - 0.5) * h * 0.6, vx: 0, vy: 0 });
  }
  for (const id of Array.from(map.keys())) if (!nodes.find((n) => n.id === id)) map.delete(id);
  const linksRef = useRef(links);
  linksRef.current = links;
  useEffect(() => {
    let raf = 0, frame = 0, energy = 1;
    const step = () => {
      const arr = Array.from(map.values());
      const alpha = reduced ? 0.6 : Math.max(0.02, energy);
      for (let i = 0; i < arr.length; i++) for (let j = i + 1; j < arr.length; j++) {
        const a = arr[i], b = arr[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        const d2 = Math.max(dx * dx + dy * dy, 30);
        const f = (260 * alpha) / d2;
        dx *= f; dy *= f;
        a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy;
      }
      for (const l of linksRef.current) {
        const a = map.get(l.s), b = map.get(l.t);
        if (!a || !b) continue;
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = ((d - 55) / d) * 0.03 * l.strength * alpha * 4;
        a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
      }
      for (const n of arr) {
        n.vx += (w / 2 - n.x) * 0.008; n.vy += (h / 2 - n.y) * 0.011;
        n.vx *= 0.82; n.vy *= 0.82;
        n.x = Math.max(n.r + 4, Math.min(w - n.r - 4, n.x + n.vx));
        n.y = Math.max(n.r + 4, Math.min(h - n.r - 4, n.y + n.vy));
      }
      energy *= 0.995;
      frame++;
      if (frame % 2 === 0) tick((t) => t + 1);
      if (!reduced && (energy > 0.02 || frame < 400)) raf = requestAnimationFrame(step);
    };
    if (reduced) { for (let k = 0; k < 300; k++) step(); tick((t) => t + 1); }
    else raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [nodes.length, links.length, w, h, reduced, map]);
  return map;
}

function SwarmGraph({ s, reduced, onPick }: { s: SwarmState; reduced: boolean; onPick: (id: string) => void }) {
  const W = 620, H = 380;
  const nodes = useMemo<N[]>(() => [
    ...(s.graph?.entities ?? []).map((e) => ({ id: e.id, kind: "entity" as const, label: e.name, color: TYPE_COLOR[e.type] ?? "#93a39b", r: 7, x: 0, y: 0, vx: 0, vy: 0 })),
    ...s.agents.map((a) => ({ id: a.id, kind: "agent" as const, label: a.name, color: stanceColor(a.stance), r: 4 + a.influence * 6, x: 0, y: 0, vx: 0, vy: 0 })),
  ], [s.graph, s.agents]);
  const authors = useMemo(() => Object.fromEntries(s.posts.map((p) => [p.id, p.author])), [s.posts]);
  const links = useMemo(() => [
    ...(s.graph?.relations ?? []).map((r) => ({ s: r.source, t: r.target, strength: 1 })),
    ...s.agents.map((a) => ({ s: a.id, t: a.entity_id, strength: 0.6 })),
  ], [s.graph, s.agents]);
  const map = useForce(nodes, links, W, H, reduced);
  const recent = useMemo(() => s.actions.slice(-18).map((a) => ({ ...a, to: a.action === "FOLLOW" || a.action === "MUTE" ? a.target : authors[a.target] }))
    .filter((a) => a.to && a.to !== a.agent_id), [s.actions, authors]);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto max-h-[440px] w-full rounded-[3px] border border-[#f5c542]/20 bg-black/60" role="img"
      aria-label={`Swarm graph: ${s.graph?.entities.length ?? 0} entities, ${s.agents.length} agents, ${s.actions.length} actions`}>
      <defs>
        <filter id="sw-glow"><feGaussianBlur stdDeviation="2" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      {links.map((l, i) => {
        const a = map.get(l.s), b = map.get(l.t);
        if (!a || !b) return null;
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={l.strength === 1 ? "rgba(245,197,66,0.22)" : "rgba(140,255,200,0.07)"} strokeWidth={l.strength === 1 ? 1 : 0.6} />;
      })}
      {recent.map((a, i) => {
        const from = map.get(a.agent_id), to = map.get(a.to!);
        if (!from || !to) return null;
        const neg = a.action === "MUTE" || a.action === "DISLIKE_POST";
        const col = neg ? "#ff5f6d" : "#45d9f5";
        return (
          <g key={`${a.round}-${a.platform}-${a.agent_id}-${i}`}>
            <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke={col} strokeOpacity={0.35} strokeWidth={1} />
            {!reduced && <motion.circle r={2.4} fill={col} filter="url(#sw-glow)" cx={from.x} cy={from.y}
              initial={{ cx: from.x, cy: from.y, opacity: 0 }}
              animate={{ cx: [from.x, to.x], cy: [from.y, to.y], opacity: [0, 1, 0] }}
              transition={{ duration: 1.6, repeat: Infinity, delay: (i % 6) * 0.25, ease: "easeInOut" }} />}
          </g>
        );
      })}
      {Array.from(map.values()).map((n) => (
        <g key={n.id} transform={`translate(${n.x},${n.y})`} className="cursor-pointer" onClick={() => n.kind === "agent" && onPick(n.id)}>
          {n.kind === "entity"
            ? <rect x={-n.r} y={-n.r} width={n.r * 2} height={n.r * 2} transform="rotate(45)" fill="#060a08" stroke={n.color} strokeWidth={1.4} filter="url(#sw-glow)" />
            : <circle r={n.r} fill={n.color} fillOpacity={0.85} stroke="#030605" strokeWidth={1} filter="url(#sw-glow)" />}
          <text y={n.kind === "entity" ? -11 : -n.r - 3} textAnchor="middle" fontSize={n.kind === "entity" ? 8.5 : 7.5}
            fill={n.kind === "entity" ? "#d6e2db" : "rgba(214,226,219,0.65)"} fontFamily="monospace">{n.label.slice(0, 18)}</text>
          <title>{n.label}</title>
        </g>
      ))}
    </svg>
  );
}

// ------------------------------------------------------------------ feeds, chart, report

function Feed({ s, platform }: { s: SwarmState; platform: "feed" | "forum" }) {
  const posts = s.posts.filter((p) => p.platform === platform).slice(-14).reverse();
  const label = platform === "feed" ? "FEED // public posts" : "FORUM // threads";
  return (
    <div className="flex min-h-0 flex-col rounded-[3px] border border-line bg-black/50">
      <div className="flex items-center justify-between border-b border-line px-2.5 py-1.5 font-mono text-[10px] tracking-[0.18em]" style={{ color: platform === "feed" ? "#45d9f5" : "#c792ea" }}>
        <span>{label}</span><span className="text-muted">{s.posts.filter((p) => p.platform === platform).length} POSTS</span>
      </div>
      <div className="max-h-72 min-h-[120px] space-y-1.5 overflow-y-auto p-2">
        <AnimatePresence initial={false}>
          {posts.map((p) => (
            <motion.div key={p.id} layout initial={{ opacity: 0, y: -10, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
              className={cx("rounded-[2px] border border-line/70 bg-white/[0.02] p-2 text-[12px]", p.parent && "ml-3 border-l-2")}>
              <div className="mb-0.5 flex items-center gap-1.5 font-mono text-[10px]">
                <span style={{ color: stanceColor(s.agents.find((a) => a.id === p.author)?.stance ?? 0) }}>● {p.author_name}</span>
                <span className="text-muted">R{p.round} · {p.kind === "QUOTE_POST" ? "quote" : p.kind === "CREATE_COMMENT" ? "comment" : "post"}</span>
              </div>
              <div className="text-dim">{p.content}</div>
              <div className="mt-1 flex gap-3 font-mono text-[10px] text-muted">
                <span>♥ {p.likes}</span><span>⟳ {p.reposts}</span><span>↳ {p.comments}</span>{p.dislikes > 0 && <span>▼ {p.dislikes}</span>}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        {!posts.length && <div className="p-3 text-center font-mono text-[10.5px] text-muted">awaiting simulation…</div>}
      </div>
    </div>
  );
}

function StanceChart({ s }: { s: SwarmState }) {
  const W = 300, H = 120, R = s.config.rounds;
  const x = (r: number) => 24 + ((r - 1) / Math.max(1, R - 1)) * (W - 36);
  const y = (v: number) => H / 2 - v * (H / 2 - 12);
  const line = (pl: string) => s.rounds.filter((r) => r.platform === pl).map((r) => `${x(r.round)},${y(r.mean_stance)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-36 w-full" role="img" aria-label="Mean stance by round on each platform">
      <line x1={20} y1={H / 2} x2={W - 8} y2={H / 2} stroke="rgba(140,255,200,0.12)" strokeDasharray="3 4" />
      <text x={2} y={14} fontSize="8" fill="#3cf59a" fontFamily="monospace">+1</text>
      <text x={2} y={H - 4} fontSize="8" fill="#ff8a7a" fontFamily="monospace">-1</text>
      {Array.from({ length: R }, (_, i) => <text key={i} x={x(i + 1)} y={H - 2} fontSize="7.5" fill="#64716b" textAnchor="middle" fontFamily="monospace">R{i + 1}</text>)}
      {(["feed", "forum"] as const).map((pl) => {
        const pts = line(pl);
        const col = pl === "feed" ? "#45d9f5" : "#c792ea";
        return pts ? (
          <g key={pl}>
            <motion.polyline points={pts} fill="none" stroke={col} strokeWidth={2} initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1 }}
              style={{ filter: `drop-shadow(0 0 4px ${col})` }} />
            {s.rounds.filter((r) => r.platform === pl).map((r) => <circle key={r.round} cx={x(r.round)} cy={y(r.mean_stance)} r={2.5} fill={col} />)}
          </g>
        ) : null;
      })}
    </svg>
  );
}

function Chat({ executionId, s }: { executionId: string; s: SwarmState }) {
  const [target, setTarget] = useState("report");
  const [msg, setMsg] = useState("");
  const [log, setLog] = useState<{ role: "user" | "assistant"; content: string; who?: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function send() {
    if (!msg.trim()) return;
    const history = log.filter((l) => l.who === undefined || l.role === "user").map(({ role, content }) => ({ role, content }));
    const mine = { role: "user" as const, content: msg };
    setLog((l) => [...l, mine]);
    setMsg(""); setBusy(true); setError(null);
    try {
      const r = await api.post<{ who: string; reply: string; test_provider: boolean }>(`/executions/${executionId}/swarm/chat`, { target, message: mine.content, history });
      setLog((l) => [...l, { role: "assistant", content: r.reply, who: r.who + (r.test_provider ? " (test)" : "") }]);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-60"><Select value={target} onChange={(e) => { setTarget(e.target.value); setLog([]); }} aria-label="Chat with"
          options={[{ value: "report", label: "ReportAgent", description: "Asks about the prediction and metrics" },
            ...s.agents.map((a) => ({ value: a.id, label: a.name, description: `${a.role} · stance ${a.stance >= 0 ? "+" : ""}${a.stance.toFixed(2)}` }))]} /></div>
        <span className="text-[11px] text-muted">Simulated agents speak from their persona and memory. They are not real people.</span>
      </div>
      <div className="max-h-56 space-y-1.5 overflow-y-auto rounded-[3px] border border-line bg-black/50 p-2 text-[12.5px]">
        {log.length === 0 && <div className="font-mono text-[10.5px] text-muted">open channel — ask a question</div>}
        {log.map((l, i) => (
          <div key={i} className={l.role === "user" ? "text-text" : "text-dim"}>
            <span className="mr-1.5 font-mono text-[10px]" style={{ color: l.role === "user" ? "#3cf59a" : GOLD }}>{l.role === "user" ? "YOU" : l.who?.toUpperCase()}</span>{l.content}
          </div>
        ))}
        {busy && <div className="font-mono text-[10.5px] text-muted x-cursor">transmitting</div>}
      </div>
      <ErrorNote error={error} />
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input value={msg} onChange={(e) => setMsg(e.target.value)} maxLength={4000} placeholder="Message…" aria-label="Message"
          className="h-9 flex-1 rounded-[3px] border border-green/15 bg-black/50 px-3 text-sm text-text focus:border-green/60 focus:outline-none" />
        <Button type="submit" size="sm" variant="primary" loading={busy} disabled={!msg.trim()}>Send</Button>
      </form>
    </div>
  );
}

// ------------------------------------------------------------------ theatre

export function SwarmTheatre({ swarm, cls, events, executionId, reducedMotion, canChat }: {
  swarm: SwarmState | null; cls?: ContentClass; events: ExecEvent[]; executionId: string; reducedMotion: boolean; canChat: boolean;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const live = events.filter((e) => e.type.startsWith("swarm."));
  if (!swarm) {
    return (
      <div className="flex items-center gap-3 font-mono text-[11px] tracking-[0.18em] text-[#f5c542]/80">
        <motion.span className="h-2 w-2 rotate-45 bg-[#f5c542]" animate={reducedMotion ? undefined : { opacity: [0.3, 1, 0.3] }} transition={{ duration: 1, repeat: Infinity }} />
        SWARM INITIALISING — {live[live.length - 1]?.message ?? "waiting for the first stage"}
      </div>
    );
  }
  const agent = swarm.agents.find((a) => a.id === picked);
  const ticker = swarm.actions.slice(-8).reverse();
  const names = Object.fromEntries(swarm.agents.map((a) => [a.id, a.name]));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {cls && <ContentBadge cls={cls} />}
        {swarm.models.map((m) => <Badge key={m}>{m}</Badge>)}
        <span className="text-muted">{swarm.config.agents} agents · {swarm.config.rounds} rounds · Feed + Forum</span>
        {swarm.graph?.prediction_question && <span className="ml-auto max-w-xl truncate text-dim" title={swarm.graph.prediction_question}>Q: {swarm.graph.prediction_question}</span>}
      </div>
      <Steps s={swarm} />
      {swarm.error && <ErrorNote error={swarm.error} />}
      <div className="grid gap-3 xl:grid-cols-[1.25fr_1fr]">
        <div className="space-y-2">
          <SwarmGraph s={swarm} reduced={reducedMotion} onPick={setPicked} />
          <div className="flex flex-wrap gap-3 text-[10.5px] text-muted">
            <span>◆ entity</span><span>● agent (size = influence, colour = stance)</span>
            <span className="text-cyan">— support / engage</span><span className="text-red">— mute / dislike</span>
            {swarm.stance_axis && <span>axis: {swarm.stance_axis}</span>}
          </div>
          {agent && (
            <div className="rounded-[3px] border border-[#f5c542]/40 bg-black/60 p-2.5 text-xs">
              <div className="flex items-center justify-between"><span className="font-mono" style={{ color: GOLD }}>{agent.name} · {agent.role}</span>
                <button onClick={() => setPicked(null)} className="text-muted hover:text-text" aria-label="Close agent">✕</button></div>
              <p className="mt-1 text-dim">{agent.persona}</p>
              <div className="mt-1 font-mono text-[10.5px] text-muted">stance {agent.initial_stance.toFixed(2)} → {agent.stance.toFixed(2)} · influence {agent.influence.toFixed(2)} · {agent.platform}</div>
              {agent.memory.length > 0 && <div className="mt-1 text-[11px] text-muted">memory: {agent.memory.join(" · ")}</div>}
            </div>
          )}
        </div>
        <div className="space-y-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <Feed s={swarm} platform="feed" />
            <Feed s={swarm} platform="forum" />
          </div>
          <div className="x-scanlines rounded-[3px] border border-line bg-black/60 p-2 font-mono text-[10.5px]">
            {ticker.length === 0 ? <span className="text-muted">no actions yet</span> : ticker.map((a, i) => (
              <motion.div key={`${a.round}-${a.platform}-${a.agent_id}-${swarm.actions.length - i}`} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} className="truncate text-dim">
                <span className="text-muted">R{a.round} {a.platform === "feed" ? "FD" : "FR"}</span> <span style={{ color: GOLD }}>{names[a.agent_id]}</span> {ACTION_GLYPH[a.action] ?? a.action} {a.target && <span className="text-muted">{names[a.target] ?? a.target}</span>}
              </motion.div>
            ))}
          </div>
        </div>
      </div>
      {swarm.rounds.length > 0 && (
        <div className="grid gap-3 lg:grid-cols-[1fr_1.4fr]">
          <div className="rounded-[3px] border border-line p-2.5">
            <div className="x-label mb-1">Mean stance by round <span className="text-cyan">Feed</span> / <span className="text-[#c792ea]">Forum</span></div>
            <StanceChart s={swarm} />
          </div>
          {swarm.metrics && (
            <div className="grid gap-2 rounded-[3px] border border-line p-2.5 text-xs sm:grid-cols-2">
              <div>
                <div className="x-label mb-1">Computed from the action log</div>
                <div className="space-y-0.5 text-dim">
                  <div>Stance <span className="font-mono text-text">{swarm.metrics.stance_start?.toFixed(2)} → {swarm.metrics.stance_end?.toFixed(2)}</span></div>
                  <div>Polarisation <span className="font-mono text-text">{swarm.metrics.polarisation_start?.toFixed(2)} → {swarm.metrics.polarisation_end?.toFixed(2)}</span></div>
                  <div className="flex flex-wrap gap-1 pt-1">{Object.entries(swarm.metrics.action_totals).map(([k, v]) => <span key={k} className="rounded-sm border border-line px-1 font-mono text-[10px]">{(ACTION_GLYPH[k] ?? k).split(" ")[0]} {v}</span>)}</div>
                </div>
              </div>
              <div>
                <div className="x-label mb-1">Largest stance shifts</div>
                {swarm.metrics.largest_shifts.slice(0, 4).map((x) => (
                  <div key={x.agent} className="flex justify-between font-mono text-[11px]"><span className="truncate text-dim">{x.agent}</span>
                    <span style={{ color: x.delta >= 0 ? "#3cf59a" : "#ff8a7a" }}>{x.delta >= 0 ? "+" : ""}{x.delta.toFixed(2)}</span></div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {swarm.report && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="rounded-[3px] border p-3" style={{ borderColor: `${GOLD}66`, boxShadow: `0 0 26px -14px ${GOLD}` }}>
          <div className="mb-1 flex flex-wrap items-center gap-2 font-mono text-[10.5px] tracking-[0.2em]" style={{ color: GOLD }}>
            REPORTAGENT {"//"} PREDICTION <Badge tone={swarm.report.confidence === "high" ? "green" : swarm.report.confidence === "medium" ? "amber" : "neutral"}>{swarm.report.confidence} confidence</Badge>
          </div>
          <div className="font-display text-base text-text">{swarm.report.headline}</div>
          <p className="mt-1 text-sm text-dim">{swarm.report.prediction}</p>
          <div className="mt-2 grid gap-3 text-xs sm:grid-cols-3">
            {([["Drivers", swarm.report.drivers], ["Minority views", swarm.report.minority_views], ["Risks", swarm.report.risks]] as const).map(([t, xs]) => (
              <div key={t}><div className="x-label mb-0.5">{t}</div>{xs.length ? xs.map((x, i) => <div key={i} className="text-dim">· {x}</div>) : <div className="text-muted">—</div>}</div>
            ))}
          </div>
          {swarm.report.recommendation && <p className="mt-2 text-xs text-text"><span className="text-muted">Recommendation:</span> {swarm.report.recommendation}</p>}
          <p className="mt-2 text-[10.5px] text-muted">A rehearsal with model agents — not a poll of real people. This prediction is passed to the Intellect pipeline as evidence.</p>
        </motion.div>
      )}
      {swarm.report && canChat && (
        <div className="rounded-[3px] border border-green/25 p-3">
          <div className="mb-2 font-mono text-[10.5px] tracking-[0.2em] text-green">05 {"//"} DEEP INTERACTION</div>
          <Chat executionId={executionId} s={swarm} />
        </div>
      )}
    </div>
  );
}
