// Copies Monaco's prebuilt AMD bundle into public/ so the editor is served
// from our own origin (no third-party CDN, CSP-friendly, works offline).
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
// monaco-editor's "exports" hides package.json, so walk up from its entry point.
let pkgDir = dirname(require.resolve("monaco-editor"));
while (!existsSync(join(pkgDir, "package.json")) || JSON.parse(readFileSync(join(pkgDir, "package.json"), "utf8")).name !== "monaco-editor") {
  const parent = dirname(pkgDir);
  if (parent === pkgDir) throw new Error("Could not locate the monaco-editor package.");
  pkgDir = parent;
}
const { version } = JSON.parse(readFileSync(join(pkgDir, "package.json"), "utf8"));
const src = join(pkgDir, "min", "vs");
const destRoot = join(here, "..", "public", "monaco");
const dest = join(destRoot, "vs");
const stamp = join(destRoot, "VERSION");

if (existsSync(stamp) && readFileSync(stamp, "utf8").trim() === version) {
  process.exit(0);
}
mkdirSync(destRoot, { recursive: true });
cpSync(src, dest, { recursive: true });
writeFileSync(stamp, version);
console.log(`[monaco] copied monaco-editor@${version} to public/monaco/vs`);
