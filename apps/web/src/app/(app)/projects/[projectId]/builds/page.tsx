import type { Metadata } from "next";
import { Suspense } from "react";
import { BuildCenterScreen } from "@/features/builds/build-center";

export const metadata: Metadata = { title: "Builds" };
export default async function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <Suspense>
      <BuildCenterScreen projectId={projectId} />
    </Suspense>
  );
}
