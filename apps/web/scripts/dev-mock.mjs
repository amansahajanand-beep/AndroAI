// Cross-platform `next dev` in mock mode (works in PowerShell, cmd and bash).
import { spawn } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const nextBin = require.resolve("next/dist/bin/next");
const child = spawn(process.execPath, [nextBin, "dev", ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, NEXT_PUBLIC_API_MODE: "mock" },
});
child.on("exit", (code) => process.exit(code ?? 0));
