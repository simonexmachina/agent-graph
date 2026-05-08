/**
 * Popup UI — shows server health, active tab URL, and queue depth.
 * Allows the user to manually flush the queue.
 */

import { flush } from "./lib/event-queue.js";

const SERVER_HEALTH = "http://localhost:8765/health";
const QUEUE_KEY = "agentgraph_event_queue";
const STATE_KEY = "agentgraph_active_tab";

async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(SERVER_HEALTH, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

async function getQueueCount(): Promise<number> {
  const result = await chrome.storage.local.get(QUEUE_KEY);
  const queue = (result[QUEUE_KEY] as unknown[] | undefined) ?? [];
  return queue.length;
}

async function getActiveUrl(): Promise<string | null> {
  const result = await chrome.storage.local.get(STATE_KEY);
  const state = result[STATE_KEY] as { url?: string } | undefined;
  return state?.url ?? null;
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
  const [healthy, queueCount, activeUrl] = await Promise.all([
    checkHealth(),
    getQueueCount(),
    getActiveUrl(),
  ]);

  setDot(healthy);

  const urlEl = document.getElementById("current-url");
  if (urlEl) urlEl.textContent = activeUrl ?? "None";

  const countEl = document.getElementById("queue-count");
  if (countEl) countEl.textContent = String(queueCount);
}

document.getElementById("flush-btn")?.addEventListener("click", async () => {
  const btn = document.getElementById("flush-btn") as HTMLButtonElement;
  btn.disabled = true;
  btn.textContent = "Flushing…";
  await flush();
  await render();
  btn.textContent = "Flush queue";
  btn.disabled = false;
});

// Initial render
render().catch(console.error);
