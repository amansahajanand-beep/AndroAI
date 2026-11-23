/**
 * The single source of truth for how statuses look and read across the app.
 * Colour is never the only signal: every status has an icon and a label.
 */
import type { AgentTaskStatus, BuildStatus, ValidationStatus } from "@apppilot/contracts";
import {
  Ban,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  CircleSlash,
  Clock,
  Hammer,
  Loader2,
  type LucideIcon,
  MinusCircle,
  Search,
  ShieldCheck,
  Sparkles,
  TestTube2,
  Wrench,
  XCircle,
  ListChecks,
  OctagonPause,
} from "lucide-react";
import { Badge } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "primary" | "ai" | "success" | "warning" | "danger" | "info";

interface StatusMeta {
  label: string;
  tone: Tone;
  icon: LucideIcon;
  spin?: boolean;
  description: string;
}

export const AGENT_STATUS: Record<AgentTaskStatus, StatusMeta> = {
  queued: { label: "Queued", tone: "neutral", icon: Clock, description: "Waiting for an agent worker." },
  planning: { label: "Planning", tone: "ai", icon: ListChecks, description: "Breaking the request into steps." },
  analyzing: { label: "Analyzing", tone: "ai", icon: Search, description: "Reading the code involved." },
  generating: { label: "Generating", tone: "ai", icon: Sparkles, description: "Writing code changes." },
  reviewing: { label: "Reviewing", tone: "ai", icon: ShieldCheck, description: "Checking its own changes." },
  building: { label: "Building", tone: "info", icon: Hammer, description: "Running a Gradle build." },
  testing: { label: "Testing", tone: "info", icon: TestTube2, description: "Running tests." },
  repairing: { label: "Repairing", tone: "warning", icon: Wrench, description: "Fixing errors from the last build or test run." },
  completed: { label: "Completed", tone: "success", icon: CheckCircle2, description: "Finished. Changes may be waiting for your review." },
  failed: { label: "Failed", tone: "danger", icon: XCircle, description: "Stopped with an error." },
  blocked: { label: "Blocked", tone: "warning", icon: OctagonPause, description: "Needs something from you before it can continue." },
  cancelled: { label: "Cancelled", tone: "neutral", icon: Ban, description: "Stopped before finishing." },
};

export const BUILD_STATUS: Record<BuildStatus, StatusMeta> = {
  queued: { label: "Queued", tone: "neutral", icon: Clock, description: "Waiting for a build worker." },
  running: { label: "Running", tone: "info", icon: Loader2, spin: true, description: "Gradle is running." },
  succeeded: { label: "Succeeded", tone: "success", icon: CheckCircle2, description: "Build finished without errors." },
  failed: { label: "Failed", tone: "danger", icon: XCircle, description: "Build finished with errors." },
  cancelled: { label: "Cancelled", tone: "neutral", icon: Ban, description: "Build was stopped." },
};

export const VALIDATION_STATUS: Record<ValidationStatus, StatusMeta> = {
  passed: { label: "Passed", tone: "success", icon: CheckCircle2, description: "Ran and met every assertion." },
  failed: { label: "Failed", tone: "danger", icon: XCircle, description: "Ran and at least one assertion failed." },
  blocked: { label: "Blocked", tone: "warning", icon: CircleSlash, description: "Didn't run because something it depends on failed, such as the build." },
  unverified: { label: "Unverified", tone: "info", icon: CircleHelp, description: "Ran, but the result couldn't be confirmed — for example, the emulator couldn't observe the expected screen." },
  skipped: { label: "Skipped", tone: "neutral", icon: MinusCircle, description: "Intentionally not run (e.g. @Ignore)." },
};

function StatusBadgeBase({ meta, className, iconOnly }: { meta: StatusMeta; className?: string; iconOnly?: boolean }) {
  const Icon = meta.icon;
  return (
    <Badge tone={meta.tone} className={className} title={meta.description}>
      <Icon className={cn(meta.spin && "animate-spin")} aria-hidden />
      {iconOnly ? <span className="sr-only">{meta.label}</span> : meta.label}
    </Badge>
  );
}

export const AgentStatusBadge = ({ status, className }: { status: AgentTaskStatus; className?: string }) => (
  <StatusBadgeBase meta={AGENT_STATUS[status]} className={className} />
);
export const BuildStatusBadge = ({ status, className }: { status: BuildStatus; className?: string }) => (
  <StatusBadgeBase meta={BUILD_STATUS[status]} className={className} />
);
export const ValidationBadge = ({
  status,
  className,
  iconOnly,
}: {
  status: ValidationStatus | null;
  className?: string;
  iconOnly?: boolean;
}) =>
  status ? (
    <StatusBadgeBase meta={VALIDATION_STATUS[status]} className={className} iconOnly={iconOnly} />
  ) : (
    <Badge tone="neutral" className={className}>
      <CircleDashed aria-hidden /> Pending
    </Badge>
  );

export const isAgentActive = (s: AgentTaskStatus) => !["completed", "failed", "blocked", "cancelled"].includes(s);
