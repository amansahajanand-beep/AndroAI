import type { Metadata } from "next";
import { VisualEditorScreen } from "@/features/visual-editor/visual-editor";

export const metadata: Metadata = { title: "Visual editor" };
export default async function Page({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return <VisualEditorScreen projectId={projectId} />;
}
