"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, Code2, Hammer, Info, MousePointerSquareDashed, Settings, TestTube2 } from "lucide-react";
import { ErrorState } from "@/components/states/states";
import { Alert, Skeleton } from "@/components/ui/primitives";
import { useProject } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { ProjectTechBadges } from "./project-meta";

const TABS = [
  { seg: "ide", label: "IDE", icon: Code2 },
  { seg: "agent", label: "AI agent", icon: Bot },
  { seg: "builds", label: "Builds", icon: Hammer },
  { seg: "tests", label: "Tests", icon: TestTube2 },
  { seg: "visual-editor", label: "Visual editor", icon: MousePointerSquareDashed },
  { seg: "settings", label: "Settings", icon: Settings },
] as const;

export function ApkAnalysisNotice({ className }: { className?: string }) {
  return (
    <Alert tone="warning" className={className}>
      <Info />
      <span>
        <strong className="font-medium">This is an APK analysis, not source code.</strong> Files here were reconstructed
        from compiled output and may be obfuscated or incomplete. Agent changes produce new code; they can&apos;t recover
        or edit the original project.
      </span>
    </Alert>
  );
}

export function ProjectFrame({ projectId, children }: { projectId: string; children: React.ReactNode }) {
  const project = useProject(projectId);
  const pathname = usePathname();

  return (
    <div>
      <div className="border-b border-border bg-surface/60">
        <div className="mx-auto w-full px-4 pt-5 sm:px-6 lg:w-[min(90%,1600px)] lg:px-0">
          {project.isPending ? (
            <Skeleton className="h-6 w-48" />
          ) : project.isError ? (
            <ErrorState error={project.error} onRetry={() => project.refetch()} compact />
          ) : (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <Link href="/projects" className="text-[14px] text-muted-foreground hover:text-foreground">
                Projects
              </Link>
              <span className="text-subtle-foreground" aria-hidden>
                /
              </span>
              <h1 className="text-base font-semibold">{project.data.name}</h1>
              <ProjectTechBadges project={project.data} />
            </div>
          )}
          <nav aria-label="Project" className="-mb-px mt-3 flex gap-1 overflow-x-auto">
            {TABS.map((t) => {
              const href = `/projects/${projectId}/${t.seg}`;
              const active = pathname.startsWith(href);
              return (
                <Link
                  key={t.seg}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "inline-flex h-9 shrink-0 items-center gap-1.5 border-b-2 px-2.5 text-[14px] transition-colors",
                    active ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  <t.icon className="size-3.5" aria-hidden />
                  {t.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
      {project.data?.isApkAnalysis ? (
        <div className="mx-auto w-full px-4 pt-4 sm:px-6 lg:w-[min(90%,1600px)] lg:px-0">
          <ApkAnalysisNotice />
        </div>
      ) : null}
      {children}
    </div>
  );
}
