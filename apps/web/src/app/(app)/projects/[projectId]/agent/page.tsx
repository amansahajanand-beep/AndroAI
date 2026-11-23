import type { Metadata } from "next";
import { Suspense } from "react";
import { AgentScreen } from "@/features/agent/agent-screen";

export const metadata: Metadata = { title: "AI agent" };
export default async function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <Suspense>
      <AgentScreen projectId={projectId} />
    </Suspense>
  );
}
