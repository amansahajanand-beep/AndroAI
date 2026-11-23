import type { Metadata } from "next";
import { Suspense } from "react";
import { NewProjectWizard } from "@/features/wizard/new-project-wizard";

export const metadata: Metadata = { title: "New project" };
export default function Page() {
  return (
    <Suspense>
      <NewProjectWizard />
    </Suspense>
  );
}
