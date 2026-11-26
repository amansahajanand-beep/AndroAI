"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

interface Timing {
  /** Base delay per typed character (a little random jitter is added so it feels natural). */
  typeMs?: number;
  /** Delay per erased character (erasing is quicker than typing). */
  eraseMs?: number;
  /** How long a finished phrase stays on screen before it's erased. */
  holdMs?: number;
  /** Pause between erasing one phrase and typing the next. */
  gapMs?: number;
}

/**
 * Types each phrase character by character, holds it, erases it, then moves on to the next, forever.
 * While `active` is false it pauses where it is (and resumes from there), so it never runs in the
 * background. Returns the text to show right now.
 */
export function useTypewriter(phrases: readonly string[], active: boolean, { typeMs = 45, eraseMs = 22, holdMs = 1900, gapMs = 400 }: Timing = {}) {
  const [text, setText] = useState("");
  // Progress lives in refs so pausing and resuming continues mid-phrase.
  const phrase = useRef(0);
  const chars = useRef(0);
  const erasing = useRef(false);

  useEffect(() => {
    if (!active || phrases.length === 0) return;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const current = phrases[phrase.current % phrases.length] ?? "";
      if (!erasing.current) {
        chars.current = Math.min(current.length, chars.current + 1);
        setText(current.slice(0, chars.current));
        if (chars.current >= current.length) {
          erasing.current = true;
          timer = setTimeout(tick, holdMs);
        } else {
          timer = setTimeout(tick, typeMs + Math.random() * 35);
        }
      } else {
        chars.current = Math.max(0, chars.current - 1);
        setText(current.slice(0, chars.current));
        if (chars.current === 0) {
          erasing.current = false;
          phrase.current += 1;
          timer = setTimeout(tick, gapMs);
        } else {
          timer = setTimeout(tick, eraseMs);
        }
      }
    };
    timer = setTimeout(tick, chars.current === 0 ? gapMs : typeMs);
    return () => clearTimeout(timer);
  }, [active, phrases, typeMs, eraseMs, holdMs, gapMs]);

  return text;
}

const subscribeReducedMotion = (onChange: () => void) => {
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
};

/** True when the visitor asked their system for reduced motion. */
export function usePrefersReducedMotion() {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
}
