/**
 * esbuild bundler — compiles TypeScript entry points into dist/.
 * Copies static assets (manifest.json, popup/options HTML and CSS) alongside.
 */

import * as esbuild from "esbuild";
import { copyFileSync, cpSync, mkdirSync } from "fs";

mkdirSync("dist", { recursive: true });
mkdirSync("dist/lib", { recursive: true });

await esbuild.build({
  entryPoints: ["background.ts", "popup.ts", "lib/dwell.ts", "content-gmail.ts"],
  bundle: false,
  format: "esm",
  outdir: "dist",
  target: "chrome120",
  sourcemap: false,
});

// Copy static assets
for (const file of ["manifest.json", "popup.html", "popup.css", "options.html", "options.css"]) {
  copyFileSync(file, `dist/${file}`);
}

cpSync("assets", "dist/assets", { recursive: true });

console.log("Build complete → dist/");
