"use client";

import { useEffect, useState } from "react";

const CHARS = "アカサタナハマヤラワ01ΣΨΩ<>/#%&@";

/** Decodes text from random glyphs to its final value once on mount. Static under reduced motion. */
export function GlitchText({ text, className, duration = 900 }: { text: string; className?: string; duration?: number }) {
  const [shown, setShown] = useState(text);
  useEffect(() => {
    const reduced = document.documentElement.dataset.reducedMotion === "true" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setShown(text);
      return;
    }
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / duration);
      const fixed = Math.floor(p * text.length);
      setShown(text.split("").map((c, i) => (i < fixed || c === " " ? c : CHARS[(Math.random() * CHARS.length) | 0])).join(""));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [text, duration]);
  return <span className={className} aria-label={text}><span aria-hidden>{shown}</span></span>;
}
