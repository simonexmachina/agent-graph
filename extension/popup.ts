/**
 * Popup UI — shows server health and the active tab URL being observed.
 */

const SERVER_HEALTH = "http://localhost:8765/health";

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
  const [healthy, activeUrl] = await Promise.all([checkHealth(), getActiveUrl()]);

  setDot(healthy);

  const urlEl = document.getElementById("current-url");
  if (urlEl) urlEl.textContent = activeUrl ?? "None";
}

render().catch(console.error);
