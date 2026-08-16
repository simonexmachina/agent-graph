import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const diagramsDir = dirname(fileURLToPath(import.meta.url));
const docsSrcDir = dirname(diagramsDir);
const outputDir = join(docsSrcDir, "assets", "diagrams");
const mmdc = join(docsSrcDir, "node_modules", ".bin", "mmdc");
const browserCandidates = [
  process.env.PUPPETEER_EXECUTABLE_PATH,
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);
const executablePath = browserCandidates.find((candidate) => existsSync(candidate));

if (!executablePath) {
  throw new Error("No Chrome or Chromium executable found for Mermaid rendering");
}

mkdirSync(outputDir, { recursive: true });
const puppeteerConfig = join(tmpdir(), "agentgraph-mermaid-puppeteer.json");
writeFileSync(puppeteerConfig, JSON.stringify({ executablePath }), "utf8");

const diagrams = [
  "architecture-overview",
  "architecture-converging-flows",
  "architecture-four-lanes",
  "architecture-central-hub",
  "architecture-lifecycle-loop",
  "context-lifecycle",
];
const themes = ["light", "dark"];

function render(name, theme, format, scale = "1") {
  const extension = format === "png" ? "png" : "svg";
  const args = [
    "-i", join(diagramsDir, `${name}.mmd`),
    "-o", join(outputDir, `${name}-${theme}.${extension}`),
    "-c", join(diagramsDir, `mermaid-${theme}.json`),
    "-p", puppeteerConfig,
    "-b", theme === "dark" ? "#07080a" : "#ffffff",
    "-s", scale,
  ];
  const result = spawnSync(mmdc, args, { stdio: "inherit" });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

for (const diagram of diagrams) {
  for (const theme of themes) render(diagram, theme, "svg");
}
render("architecture-overview", "dark", "png", "2");
