import type { Metadata } from "next";
import { Suspense } from "react";
import { TestingCenterScreen } from "@/features/tests/testing-center";

export const metadata: Metadata = { title: "Tests" };
export default async function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <Suspense>
      <TestingCenterScreen projectId={projectId} />
    </Suspense>
  );
}
