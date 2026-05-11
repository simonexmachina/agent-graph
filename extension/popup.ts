/**
 * Popup UI — shows server health and the active tab URL being observed.
 */

const SERVER_HEALTH = "http://localhost:8765/health";
const CACHE_KEY = "agentgraph_meta_cache";

interface DwellMeta {
  url_patterns: string[];
  dwell_threshold_ms: number;
}

interface ReloadResponse {
  ok: boolean;
  meta?: DwellMeta;
  error?: string;
}

async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(SERVER_HEALTH, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

async function getActiveUrl(): Promise<string | null> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab?.url ?? null;
}

async function getCachedMeta(): Promise<DwellMeta | null> {
  const result = await chrome.storage.local.get(CACHE_KEY);
  return result[CACHE_KEY] as DwellMeta | null;
}

function setDot(healthy: boolean | null): void {
  const dot = document.getElementById("status-dot");
  if (!dot) return;
  dot.className = "dot";
  if (healthy === null) dot.classList.add("dot--unknown");
  else if (healthy) dot.classList.add("dot--ok");
  else dot.classList.add("dot--error");
  dot.title = healthy === null ? "Checking…" : healthy ? "Server online" : "Server offline";
}

async function render(): Promise<void> {
  const [healthy, activeUrl, meta] = await Promise.all([
    checkHealth(),
    getActiveUrl(),
    getCachedMeta(),
  ]);

  setDot(healthy);

  const urlEl = document.getElementById("current-url");
  if (urlEl) urlEl.textContent = activeUrl ?? "None";

  const patternCountEl = document.getElementById("pattern-count");
  if (patternCountEl) patternCountEl.textContent = String(meta?.url_patterns.length ?? 0);
}

async function reloadPatterns(): Promise<void> {
  const button = document.getElementById("reload-patterns") as HTMLButtonElement | null;
  if (button) button.disabled = true;

  try {
    const response = await chrome.runtime.sendMessage({ type: "reload_url_patterns" }) as ReloadResponse;
    if (!response.ok) throw new Error(response.error ?? "Failed to reload URL patterns");

    const patternCountEl = document.getElementById("pattern-count");
    if (patternCountEl && response.meta) {
      patternCountEl.textContent = String(response.meta.url_patterns.length);
    }
  } finally {
    if (button) button.disabled = false;
  }
}

document.getElementById("reload-patterns")?.addEventListener("click", () => {
  reloadPatterns().catch(console.error);
});

render().catch(console.error);
