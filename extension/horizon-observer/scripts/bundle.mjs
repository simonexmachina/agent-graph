/**
 * esbuild bundler — compiles TypeScript entry points into dist/.
 * Copies static assets (manifest.json, popup.html, popup.css) alongside.
 */

import * as esbuild from "esbuild";
import { copyFileSync, mkdirSync } from "fs";

mkdirSync("dist", { recursive: true });
mkdirSync("dist/lib", { recursive: true });

await esbuild.build({
  entryPoints: ["background.ts", "popup.ts", "lib/event-queue.ts", "content-gmail.ts"],
  bundle: false,
  format: "esm",
  outdir: "dist",
  target: "chrome120",
  sourcemap: false,
});

// Copy static assets
for (const file of ["manifest.json", "popup.html", "popup.css"]) {
  copyFileSync(file, `dist/${file}`);
}

console.log("Build complete → dist/");
