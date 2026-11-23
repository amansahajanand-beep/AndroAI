import type { Metadata } from "next";
import { Suspense } from "react";
import { IdeScreen } from "@/features/ide/ide-screen";
import { RecordProjectView } from "@/stores/recent-projects";

export const metadata: Metadata = { title: "IDE" };
export default async function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <Suspense>
      <RecordProjectView projectId={projectId} />
      <IdeScreen projectId={projectId} />
    </Suspense>
  );
}
