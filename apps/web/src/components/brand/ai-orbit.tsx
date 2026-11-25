import { cn } from "@/lib/utils";

/** Drifting particles: position in %, drift offset and timing (fixed, so renders are stable). */
const PARTICLES = [
  { left: "14%", top: "30%", dx: "5px", dy: "-9px", dur: "6.5s", delay: "0s" },
  { left: "82%", top: "24%", dx: "-6px", dy: "-7px", dur: "7.5s", delay: "1.2s" },
  { left: "72%", top: "78%", dx: "-4px", dy: "-10px", dur: "6s", delay: "2.4s" },
  { left: "24%", top: "74%", dx: "6px", dy: "-6px", dur: "8s", delay: "0.6s" },
  { left: "50%", top: "8%", dx: "3px", dy: "-6px", dur: "7s", delay: "3.1s" },
];

/**
 * AppPilot's animated identity: a glowing glass core with tilted orbital rings, small satellites
 * and a few drifting particles. Pure CSS (see `.ai-orbit` in globals.css); decorative only.
 */
export function AiOrbit({ size = 56, className }: { size?: number; className?: string }) {
  return (
    <span aria-hidden className={cn("ai-orbit", className)} style={{ width: size, height: size }}>
      <span className="ai-orbit-glow" />
      <span className="ai-orbit-ring is-faint" style={{ "--inset": "2%", "--tilt": "-18deg", "--dur": "16s" } as React.CSSProperties} />
      <span className="ai-orbit-ring" style={{ "--inset": "10%", "--tilt": "22deg", "--dur": "9s" } as React.CSSProperties}>
        <span className="ai-orbit-sat" />
      </span>
      <span className="ai-orbit-ring" style={{ "--inset": "18%", "--tilt": "-34deg", "--dur": "6.5s" } as React.CSSProperties}>
        <span className="ai-orbit-sat" style={{ width: 4, height: 4, top: -2, left: "calc(50% - 2px)" }} />
      </span>
      <span className="ai-orbit-core" />
      {PARTICLES.map((p, i) => (
        <span
          key={i}
          className="ai-orbit-particle"
          style={{ left: p.left, top: p.top, "--dx": p.dx, "--dy": p.dy, "--dur": p.dur, "--delay": p.delay } as React.CSSProperties}
        />
      ))}
    </span>
  );
}
