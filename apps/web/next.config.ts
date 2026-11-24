import path from "node:path";
import type { NextConfig } from "next";

const apiMode = process.env.NEXT_PUBLIC_API_MODE ?? "live";
if (
  apiMode === "mock" &&
  process.env.NODE_ENV === "production" &&
  process.env.ALLOW_MOCK_IN_PRODUCTION !== "true"
) {
  throw new Error(
    "NEXT_PUBLIC_API_MODE=mock is for local UI development only. " +
      "Set ALLOW_MOCK_IN_PRODUCTION=true to build a mock demo deliberately.",
  );
}

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

// The monorepo root: @apppilot/contracts lives in ../../packages/shared-types, outside this app.
const repoRoot = path.resolve(__dirname, "../..");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  turbopack: { root: repoRoot },
  outputFileTracingRoot: repoRoot,
  // The dev rewrite proxy buffers request bodies and silently truncates at 10 MB by default, which would
  // corrupt project uploads (limit: UPLOAD_MAX_BYTES, 200 MB). Production routes /api straight to the API (Nginx).
  experimental: { middlewareClientMaxBodySize: "210mb" },
  transpilePackages: ["@apppilot/contracts"],
  // Dev only: let the LocalTunnel hostname (e.g. my-app.loca.lt) load HMR and font/dev resources.
  allowedDevOrigins: ["*.loca.lt"],
  async rewrites() {
    if (apiMode === "mock") return [];
    // Same-origin proxy so the backend's httpOnly session cookie stays first-party.
    return [{ source: "/api/v1/:path*", destination: `${backendUrl}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;
