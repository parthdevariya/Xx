"use client";

import { useEffect, useRef } from "react";

const GLYPHS = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワ0123456789XΣΨΩ∆λ";

function reduced(): boolean {
  return document.documentElement.dataset.reducedMotion === "true" ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Ambient digital rain. Decorative only: sits behind content, ignores pointer, ~30 fps, pauses when hidden,
 *  and is not drawn at all under reduced motion. */
export function MatrixRain({ opacity = 0.16, density = 1 }: { opacity?: number; density?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    let last = 0;
    let drops: number[] = [];
    let speeds: number[] = [];
    const size = 15;
    let w = 0, h = 0;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const cols = Math.ceil((w / size) * density);
      drops = Array.from({ length: cols }, () => Math.random() * -h / size);
      speeds = Array.from({ length: cols }, () => 0.35 + Math.random() * 0.75);
      ctx.fillStyle = "#050708";
      ctx.fillRect(0, 0, w, h);
    };

    const draw = (t: number) => {
      raf = requestAnimationFrame(draw);
      if (t - last < 33) return; // ~30 fps
      last = t;
      if (reduced()) {
        ctx.clearRect(0, 0, w, h);
        return;
      }
      ctx.fillStyle = "rgba(5, 7, 8, 0.12)";
      ctx.fillRect(0, 0, w, h);
      ctx.font = `${size - 2}px ui-monospace, monospace`;
      const step = w / drops.length;
      for (let i = 0; i < drops.length; i++) {
        const y = drops[i] * size;
        const ch = GLYPHS[(Math.random() * GLYPHS.length) | 0];
        ctx.fillStyle = Math.random() < 0.04 ? "rgba(210, 255, 230, 0.95)" : "rgba(60, 245, 154, 0.75)";
        ctx.fillText(ch, i * step, y);
        drops[i] += speeds[i];
        if (y > h && Math.random() > 0.975) drops[i] = Math.random() * -20;
      }
    };

    const onVis = () => {
      if (document.hidden) cancelAnimationFrame(raf);
      else raf = requestAnimationFrame(draw);
    };

    resize();
    raf = requestAnimationFrame(draw);
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [density]);

  return <canvas ref={ref} aria-hidden className="x-rain-layer" style={{ opacity }} />;
}
