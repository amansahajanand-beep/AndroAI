"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Flies its child (the AppPilot arrow) on a looping, curved lap around the
 * viewport, then lands it exactly where it sits in the layout. The path is
 * computed in screen space from the arrow's resting position, so it works at
 * any viewport size. Uses the Web Animations API (no animation library needed).
 */

const WAYPOINTS: [number, number][] = [
  [1.12, 0.2],
  [0.88, 0.72],
  [0.5, 0.8],
  [0.12, 0.58],
  [0.14, 0.18],
  [0.5, 0.07],
  [0.9, 0.26],
  [0.8, 0.58],
]; // the final waypoint (the resting spot) is appended at runtime

const DURATION = 7600;
const START_DELAY = 450;
const TRAIL = [0.55, 0.42, 0.32, 0.24, 0.17, 0.11].map((o, i) => ({ opacity: o, size: 0.34 - i * 0.035, lag: (i + 1) * 120 }));

type Pt = { x: number; y: number };

function catmull(p0: Pt, p1: Pt, p2: Pt, p3: Pt, t: number): Pt {
  const t2 = t * t;
  const t3 = t2 * t;
  const f = (a: number, b: number, c: number, d: number) =>
    0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
  return { x: f(p0.x, p1.x, p2.x, p3.x), y: f(p0.y, p1.y, p2.y, p3.y) };
}

const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

function buildPath(cx: number, cy: number) {
  const W = window.innerWidth;
  const H = window.innerHeight;
  const pts: Pt[] = [...WAYPOINTS.map(([x, y]) => ({ x: x * W, y: y * H })), { x: cx, y: cy }];
  const ext = [pts[0]!, ...pts, pts[pts.length - 1]!];
  const samples: Pt[] = [];
  for (let i = 1; i < ext.length - 2; i++) {
    for (let s = 0; s < 16; s++) samples.push(catmull(ext[i - 1]!, ext[i]!, ext[i + 1]!, ext[i + 2]!, s / 16));
  }
  samples.push({ x: cx, y: cy });
  // constant speed along the curve: offsets follow cumulative arc length
  const cum = [0];
  for (let i = 1; i < samples.length; i++) {
    cum.push(cum[i - 1]! + Math.hypot(samples[i]!.x - samples[i - 1]!.x, samples[i]!.y - samples[i - 1]!.y));
  }
  const total = cum[cum.length - 1]!;
  // heading of travel, measured over a wide window so it is smooth, then unwrapped
  const headings: number[] = [];
  samples.forEach((_, i) => {
    const a = samples[Math.max(0, i - 4)]!;
    const b = samples[Math.min(samples.length - 1, i + 4)]!;
    let h = (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI + 90; // arrow tip points up at rest
    const prev = headings[i - 1];
    if (prev !== undefined) while (h - prev > 180) h -= 360; else while (h > 180) h -= 360;
    if (prev !== undefined) while (h - prev < -180) h += 360;
    headings.push(h);
  });
  // low-pass so direction changes ease in and out
  const smoothed = headings.map((_, i) => {
    let sum = 0;
    let n = 0;
    for (let k = -6; k <= 6; k++) {
      const v = headings[i + k];
      if (v !== undefined) {
        sum += v;
        n++;
      }
    }
    return sum / n;
  });
  return samples.map((p, i) => {
    const u = cum[i]! / total;
    return { u, dx: p.x - cx, dy: p.y - cy, heading: smoothed[i]! };
  });
}

export function PilotFlight({ className, children }: { className?: string; children: ReactNode }) {
  const root = useRef<HTMLSpanElement>(null);
  const fly = useRef<HTMLSpanElement>(null);
  const dots = useRef<(HTMLSpanElement | null)[]>([]);

  useEffect(() => {
    const rootEl = root.current;
    const flyEl = fly.current;
    if (!rootEl || !flyEl) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      flyEl.style.opacity = "1";
      return;
    }

    let cancelled = false;
    const anims: Animation[] = [];

    const start = () => {
      if (cancelled) return;
      const r = rootEl.getBoundingClientRect();
      const path = buildPath(r.left + r.width / 2, r.top + r.height / 2);

      const arrow = path.map(({ u, dx, dy, heading }, i) => {
        // the tip follows the direction of travel; only in the final stretch does it ease upright
        const land = smooth(0.88, 1, u);
        const upright = 360 * Math.round(path[Math.floor(path.length * 0.88)]!.heading / 360);
        const rot = heading * (1 - land) + upright * land;
        const flip = 0;
        const scale = 1 + 0.1 * Math.sin(Math.PI * u) * (1 - land);
        return {
          offset: u,
          opacity: i === 0 ? 0 : 1,
          transform: `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px) perspective(700px) rotateZ(${rot.toFixed(1)}deg) rotateY(${flip.toFixed(1)}deg) scale(${scale.toFixed(3)})`,
        };
      });
      // de-duplicate offsets (WAAPI needs non-decreasing offsets) and fade in quickly
      arrow.forEach((k, i) => {
        if (i > 0 && k.offset < arrow[i - 1]!.offset) k.offset = arrow[i - 1]!.offset;
      });
      const opts: KeyframeAnimationOptions = {
        duration: DURATION,
        delay: START_DELAY,
        easing: "cubic-bezier(0.33, 0.08, 0.2, 1)",
        fill: "both",
      };
      const a = flyEl.animate(arrow, opts);
      anims.push(a);
      a.finished
        .then(() => {
          flyEl.style.opacity = "1";
          a.cancel();
        })
        .catch(() => {});

      TRAIL.forEach((t, i) => {
        const el = dots.current[i];
        if (!el) return;
        const frames = path.map(({ u, dx, dy }) => ({
          offset: u,
          opacity: u < 0.03 ? 0 : u > 0.86 ? 0 : t.opacity * (1 - smooth(0.7, 0.86, u)),
          transform: `translate(-50%, -50%) translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px)`,
        }));
        frames.forEach((k, j) => {
          if (j > 0 && k.offset < frames[j - 1]!.offset) k.offset = frames[j - 1]!.offset;
        });
        const d = el.animate(frames, { ...opts, delay: START_DELAY + t.lag });
        anims.push(d);
        d.finished.then(() => d.cancel()).catch(() => {});
      });
    };

    const fonts = document.fonts?.ready;
    if (fonts) fonts.then(() => requestAnimationFrame(start));
    else requestAnimationFrame(start);

    return () => {
      cancelled = true;
      anims.forEach((a) => a.cancel());
    };
  }, []);

  return (
    <span ref={root} className={cn("relative", className)}>
      <span aria-hidden className="pointer-events-none absolute inset-0">
        {TRAIL.map((t, i) => (
          <span
            key={i}
            ref={(el) => {
              dots.current[i] = el;
            }}
            className="absolute left-1/2 top-1/2 rounded-full opacity-0 blur-[6px]"
            style={{
              width: `${t.size * 100}%`,
              height: `${t.size * 100}%`,
              backgroundImage: "radial-gradient(circle, rgb(167 139 250), rgb(109 94 248) 70%, transparent)",
            }}
          />
        ))}
      </span>
      {/* hidden until the flight begins; the effect reveals it (or shows it at once under reduced motion) */}
      <span ref={fly} className="pilot-fly block size-full" style={{ opacity: 0 }}>
        {children}
      </span>
    </span>
  );
}
