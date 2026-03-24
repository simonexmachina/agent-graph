/**
 * Service worker: focus/blur event emitter.
 *
 * Tracks the active tab. When focus changes (tab switch, window switch,
 * or navigation) we emit a blur for the previous URL and a focus for
 * the new one. Events are persisted via event-queue before delivery so
 * they survive service-worker termination.
 */

import { type ObserveEvent, enqueue, flush } from "./lib/event-queue.js";

interface TabState {
  tabId: number;
  url: string;
  title: string;
  focusedAt: string; // ISO-8601
}

// In-memory state (survives within a single service-worker lifetime).
// Restored from storage on startup if needed.
const STATE_KEY = "agentgraph_active_tab";

async function readState(): Promise<TabState | null> {
  const result = await chrome.storage.local.get(STATE_KEY);
  return (result[STATE_KEY] as TabState | undefined) ?? null;
}

async function writeState(state: TabState | null): Promise<void> {
  if (state === null) {
    await chrome.storage.local.remove(STATE_KEY);
  } else {
    await chrome.storage.local.set({ [STATE_KEY]: state });
  }
}

function now(): string {
  return new Date().toISOString();
}

/** Emit a blur for the current state if one exists. */
async function emitBlur(state: TabState): Promise<void> {
  const event: ObserveEvent = {
    type: "blur",
    url: state.url,
    tab_id: state.tabId,
    timestamp: now(),
  };
  await enqueue(event);
}

/** Emit a focus for the given tab. */
async function emitFocus(tabId: number, url: string, title: string): Promise<void> {
  const ts = now();
  const event: ObserveEvent = {
    type: "focus",
    url,
    title,
    tab_id: tabId,
    timestamp: ts,
  };
  const state: TabState = { tabId, url, title, focusedAt: ts };
  await writeState(state);
  await enqueue(event);
}

/** Called whenever the active tab or its URL/title might have changed. */
async function handleTabChange(tabId: number): Promise<void> {
  let tab: chrome.tabs.Tab;
  try {
    tab = await chrome.tabs.get(tabId);
  } catch {
    // Tab may have been closed already
    return;
  }

  const url = tab.url ?? "";
  const title = tab.title ?? "";

  // Ignore non-web pages
  if (!url.startsWith("http://") && !url.startsWith("https://")) {
    return;
  }

  const prev = await readState();

  if (prev && (prev.tabId !== tabId || prev.url !== url)) {
    await emitBlur(prev);
  }

  if (!prev || prev.tabId !== tabId || prev.url !== url) {
    await emitFocus(tabId, url, title);
  }
}

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  await handleTabChange(tabId);
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, _tab) => {
  // Only act when the URL is finalised (status=complete) or title changes
  if (changeInfo.status === "complete" || changeInfo.title) {
    const activeTab = await chrome.tabs.query({ active: true, currentWindow: true });
    if (activeTab[0]?.id === tabId) {
      await handleTabChange(tabId);
    }
  }
});

chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    // Browser lost focus — emit blur for current tab
    const prev = await readState();
    if (prev) {
      await emitBlur(prev);
      await writeState(null);
    }
    return;
  }
  const [activeTab] = await chrome.tabs.query({ active: true, windowId });
  if (activeTab?.id != null) {
    await handleTabChange(activeTab.id);
  }
});

// On service worker startup: flush any queued events from a previous session
flush().catch(() => {/* best-effort */});
