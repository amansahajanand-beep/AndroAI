import type { Metadata } from "next";
import { ProjectSettingsScreen } from "@/features/projects/project-settings";

export const metadata: Metadata = { title: "Project settings" };
export default async function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return <ProjectSettingsScreen projectId={projectId} />;
}
