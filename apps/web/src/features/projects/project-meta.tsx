import type { Project } from "@apppilot/contracts";
import { FileArchive, MessageSquareText, Package } from "lucide-react";
import { Badge } from "@/components/ui/primitives";

export const SOURCE_META = {
  prompt: { label: "From prompt", icon: MessageSquareText },
  android_zip: { label: "Imported project", icon: FileArchive },
  apk: { label: "APK analysis", icon: Package },
} as const;

export function ProjectTechBadges({ project }: { project: Project }) {
  const Source = SOURCE_META[project.source];
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Badge tone={project.isApkAnalysis ? "warning" : "outline"}>
        <Source.icon aria-hidden />
        {Source.label}
      </Badge>
      <Badge tone="neutral">{project.language === "kotlin" ? "Kotlin" : "Java"}</Badge>
      <Badge tone="neutral">{project.uiToolkit === "compose" ? "Compose" : "XML views"}</Badge>
      {project.status === "creating" ? <Badge tone="ai">Generating</Badge> : null}
      {project.status === "analyzing" ? <Badge tone="info">Analyzing</Badge> : null}
      {project.status === "error" ? <Badge tone="danger">Error</Badge> : null}
    </span>
  );
}
