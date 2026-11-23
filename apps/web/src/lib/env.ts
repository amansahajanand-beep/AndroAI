/**
 * Build-time configuration. NEXT_PUBLIC_* values are inlined by Next.js.
 */
export type ApiMode = "live" | "mock";

export const API_MODE: ApiMode = process.env.NEXT_PUBLIC_API_MODE === "mock" ? "mock" : "live";
export const IS_MOCK = API_MODE === "mock";

const mb = (v: string | undefined, fallback: number) => {
  const n = Number(v);
  return (Number.isFinite(n) && n > 0 ? n : fallback) * 1024 * 1024;
};

export const MAX_ZIP_BYTES = mb(process.env.NEXT_PUBLIC_MAX_ZIP_MB, 500);
export const MAX_APK_BYTES = mb(process.env.NEXT_PUBLIC_MAX_APK_MB, 200);
