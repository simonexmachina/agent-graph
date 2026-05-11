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

interface ObservationStatus {
  url: string;
  matches: boolean;
  state: "not_matched" | "waiting" | "sending" | "sent" | "failed" | "canceled";
  threshold_ms: number;
  started_at?: number;
  fires_at?: number;
  sent_at?: number;
  http_status?: number;
  error?: string;
}

interface ObservationStatusResponse {
  ok: boolean;
  status?: ObservationStatus | null;
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

async function getObservationStatus(): Promise<ObservationStatus | null> {
  const response = await chrome.runtime.sendMessage({
    type: "get_observation_status",
  }) as ObservationStatusResponse;
  if (!response.ok) throw new Error(response.error ?? "Failed to get observation status");
  return response.status ?? null;
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

function formatObservationStatus(status: ObservationStatus | null): { text: string; className: string } {
  if (status === null) {
    return { text: "No active browser tab", className: "status status--unknown" };
  }

  if (!status.matches || status.state === "not_matched") {
    return { text: "Not a matching URL pattern", className: "status status--warn" };
  }

  if (status.state === "waiting" && status.fires_at != null) {
    const seconds = Math.max(0, Math.ceil((status.fires_at - Date.now()) / 1000));
    return { text: `Will send after dwell threshold (${seconds}s)`, className: "status status--ok" };
  }

  if (status.state === "sending") {
    return { text: "Sending observation…", className: "status status--ok" };
  }

  if (status.state === "sent") {
    const suffix = status.http_status == null ? "" : ` (HTTP ${status.http_status})`;
    return { text: `Observation sent${suffix}`, className: "status status--ok" };
  }

  if (status.state === "failed") {
    return {
      text: status.error == null ? "Observation failed" : `Observation failed: ${status.error}`,
      className: "status status--error",
    };
  }

  return { text: "Observation canceled", className: "status status--unknown" };
}

function setObservationStatus(status: ObservationStatus | null): void {
  const statusEl = document.getElementById("observation-status");
  if (!statusEl) return;

  const rendered = formatObservationStatus(status);
  statusEl.textContent = rendered.text;
  statusEl.className = rendered.className;
}

async function render(): Promise<void> {
  const [healthy, activeUrl, meta, observationStatus] = await Promise.all([
    checkHealth(),
    getActiveUrl(),
    getCachedMeta(),
    getObservationStatus().catch(() => null),
  ]);

  setDot(healthy);

  const urlEl = document.getElementById("current-url");
  if (urlEl) urlEl.textContent = activeUrl ?? "None";

  const patternCountEl = document.getElementById("pattern-count");
  if (patternCountEl) patternCountEl.textContent = String(meta?.url_patterns.length ?? 0);

  setObservationStatus(observationStatus);
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
    setObservationStatus(await getObservationStatus());
  } finally {
    if (button) button.disabled = false;
  }
}

document.getElementById("reload-patterns")?.addEventListener("click", () => {
  reloadPatterns().catch(console.error);
});

render().catch(console.error);
setInterval(() => {
  render().catch(console.error);
}, 1000);
