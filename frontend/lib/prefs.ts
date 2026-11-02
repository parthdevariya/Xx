"use client";

import { useEffect, useState } from "react";

// Per-viewer conveniences only (skip intro, reduced motion). Safe when storage is unavailable.
function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: preference lasts for this page only */
  }
}

export function usePref(key: string, initial: boolean): [boolean, (v: boolean) => void] {
  const [value, setValue] = useState(initial);
  useEffect(() => {
    const v = read(`x.${key}`);
    if (v !== null) setValue(v === "1");
  }, [key]);
  const set = (v: boolean) => {
    setValue(v);
    write(`x.${key}`, v ? "1" : "0");
  };
  return [value, set];
}

export function useReducedMotion(): [boolean, (v: boolean) => void] {
  const [pref, setPref] = usePref("reducedMotion", false);
  const [system, setSystem] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setSystem(mq.matches);
    const on = (e: MediaQueryListEvent) => setSystem(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  const reduced = pref || system;
  useEffect(() => {
    document.documentElement.dataset.reducedMotion = reduced ? "true" : "false";
  }, [reduced]);
  return [reduced, setPref];
}
