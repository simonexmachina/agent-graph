/**
 * Popup UI — shows server health and the active tab URL being observed.
 */

const CACHE_KEY = "agentgraph_meta_cache";

import { getHealthUrl, getServerBaseUrl } from "./lib/config.js";
import { type ObservationStatus, refreshPendingObservation } from "./lib/observation-status.js";

interface ObservationMeta {
  url_patterns: string[];
  observation_threshold_ms: number;
}

interface ObservationStatusResponse {
  ok: boolean;
  status?: ObservationStatus | null;
  error?: string;
}

interface PageEntity {
  id: string;
  bookmarked?: boolean;
}

interface PageActionResponse {
  ok: boolean;
  entity?: PageEntity | null;
  error?: string;
}

let displayedObservationStatus: ObservationStatus | null = null;
let observationRefreshInFlight = false;

async function checkHealth(): Promise<boolean> {
  try {
    const serverBaseUrl = await getServerBaseUrl();
    const res = await fetch(getHealthUrl(serverBaseUrl), { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

async function getActiveUrl(): Promise<string | null> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab?.url ?? null;
}

async function getCachedMeta(): Promise<ObservationMeta | null> {
  const result = await chrome.storage.local.get(CACHE_KEY);
  return result[CACHE_KEY] as ObservationMeta | null;
}

async function getObservationStatus(): Promise<ObservationStatus | null> {
  const response = await chrome.runtime.sendMessage({
    type: "get_observation_status",
  }) as ObservationStatusResponse;
  if (!response.ok) throw new Error(response.error ?? "Failed to get observation status");
  return response.status ?? null;
}

async function pageAction(
  action: "page" | "fetch" | "bookmark",
  bookmarked?: boolean,
  entityId?: string,
): Promise<PageActionResponse> {
  return await chrome.runtime.sendMessage({
    type: "extension_page_action",
    action,
    bookmarked,
    entity_id: entityId,
  }) as PageActionResponse;
}

function setPageActionStatus(message: string, variant: "neutral" | "success" | "error" = "neutral"): void {
  const status = document.getElementById("page-action-status");
  if (!status) return;
  status.textContent = message;
  status.className = `status status--${variant === "neutral" ? "unknown" : variant === "success" ? "ok" : "error"}`;
}

function setBookmarkState(entity: PageEntity | null, enabled: boolean): void {
  const button = document.getElementById("toggle-bookmark") as HTMLButtonElement | null;
  if (!button) return;
  button.disabled = !enabled;
  const bookmarked = Boolean(entity?.bookmarked);
  button.textContent = bookmarked ? "Remove bookmark" : "Bookmark";
  button.dataset.bookmarked = bookmarked ? "true" : "false";
  if (entity) button.dataset.entityId = entity.id;
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
    return { text: `Will send after observation threshold (${seconds}s)`, className: "status status--ok" };
  }

  if (status.state === "sending") {
    return { text: "Sending observation…", className: "status status--ok" };
  }

  if (status.state === "sent") {
    return { text: "Observation sent", className: "status status--ok" };
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

async function refreshDisplayedObservationStatus(): Promise<void> {
  if (observationRefreshInFlight) return;
  observationRefreshInFlight = true;
  try {
    displayedObservationStatus = await refreshPendingObservation(
      displayedObservationStatus,
      getObservationStatus,
    );
    setObservationStatus(displayedObservationStatus);
  } finally {
    observationRefreshInFlight = false;
  }
}

async function render(): Promise<void> {
  const [serverBaseUrl, healthy, activeUrl, meta, observationStatus] = await Promise.all([
    getServerBaseUrl(),
    checkHealth(),
    getActiveUrl(),
    getCachedMeta(),
    getObservationStatus().catch(() => null),
  ]);

  setDot(healthy);

  const serverUrlEl = document.getElementById("server-url");
  if (serverUrlEl) serverUrlEl.textContent = serverBaseUrl;

  const urlEl = document.getElementById("current-url");
  if (urlEl) urlEl.textContent = activeUrl ?? "None";

  const patternCountEl = document.getElementById("pattern-count");
  if (patternCountEl) patternCountEl.textContent = String(meta?.url_patterns.length ?? 0);

  setObservationStatus(observationStatus);
  displayedObservationStatus = observationStatus;

  const fetchButton = document.getElementById("fetch-page") as HTMLButtonElement | null;
  const isHttpPage = activeUrl?.startsWith("http://") || activeUrl?.startsWith("https://") || false;
  if (fetchButton) fetchButton.disabled = !isHttpPage;
  if (!isHttpPage) {
    setBookmarkState(null, false);
    setPageActionStatus("Active tab is not an HTTP(S) page");
    return;
  }

  const response = await pageAction("page");
  if (!response.ok) {
    setBookmarkState(null, true);
    setPageActionStatus(response.error ?? "Could not read page state", "error");
    return;
  }
  setBookmarkState(response.entity ?? null, true);
  setPageActionStatus(response.entity ? "Page is indexed" : "Page is not indexed");
}

async function runPageAction(action: "fetch" | "bookmark"): Promise<void> {
  const fetchButton = document.getElementById("fetch-page") as HTMLButtonElement | null;
  const bookmarkButton = document.getElementById("toggle-bookmark") as HTMLButtonElement | null;
  if (fetchButton) fetchButton.disabled = true;
  if (bookmarkButton) bookmarkButton.disabled = true;
  setPageActionStatus(action === "fetch" ? "Fetching page…" : "Updating bookmark…");
  try {
    const desired = action === "bookmark" ? bookmarkButton?.dataset.bookmarked !== "true" : undefined;
    const response = await pageAction(action, desired, bookmarkButton?.dataset.entityId);
    if (!response.ok) throw new Error(response.error ?? "Page action failed");
    if (response.entity) {
      setBookmarkState(response.entity, true);
      if (bookmarkButton) bookmarkButton.dataset.entityId = response.entity.id;
    }
    setPageActionStatus(action === "fetch" ? "Page fetched" : desired ? "Page bookmarked" : "Bookmark removed", "success");
    if (action === "fetch") {
      const refreshed = await pageAction("page");
      if (refreshed.ok) {
        setBookmarkState(refreshed.entity ?? null, true);
        if (bookmarkButton && refreshed.entity) bookmarkButton.dataset.entityId = refreshed.entity.id;
      }
    }
  } catch (error: unknown) {
    setPageActionStatus(error instanceof Error ? error.message : "Page action failed", "error");
    if (bookmarkButton) bookmarkButton.disabled = false;
  } finally {
    if (fetchButton) fetchButton.disabled = false;
    if (bookmarkButton && bookmarkButton.dataset.bookmarked !== undefined) bookmarkButton.disabled = false;
  }
}

document.getElementById("open-options")?.addEventListener("click", () => {
  chrome.runtime.openOptionsPage().catch(async () => {
    await chrome.tabs.create({ url: chrome.runtime.getURL("options.html") });
  });
});

document.getElementById("fetch-page")?.addEventListener("click", () => {
  runPageAction("fetch").catch(console.error);
});

document.getElementById("toggle-bookmark")?.addEventListener("click", () => {
  runPageAction("bookmark").catch(console.error);
});

render().catch(console.error);
setInterval(() => {
  refreshDisplayedObservationStatus().catch(console.error);
}, 250);
