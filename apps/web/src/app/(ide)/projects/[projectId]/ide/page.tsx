import type { Metadata } from "next";
import { Suspense } from "react";
import { IdeScreen } from "@/features/ide/ide-screen";

export const metadata: Metadata = { title: "IDE" };
export default async function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <Suspense>
      <IdeScreen projectId={projectId} />
    </Suspense>
  );
}
