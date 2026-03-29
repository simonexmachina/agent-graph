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

// Hex Gmail message IDs extracted by the content script, keyed by tab ID.
// Cleared when the tab navigates away from a thread URL.
const gmailMessageIdByTab = new Map<number, string>();

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
  const meta: Record<string, string> = {};
  const gmailMessageId = gmailMessageIdByTab.get(tabId);
  if (gmailMessageId) meta.gmail_message_id = gmailMessageId;

  const event: ObserveEvent = {
    type: "focus",
    url,
    title,
    tab_id: tabId,
    timestamp: ts,
    ...(Object.keys(meta).length > 0 && { meta }),
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
    // Clear stale Gmail message ID so the initial focus event carries no meta
    // and the content script re-sends the correct ID for the new page.
    if (prev?.url !== url) {
      gmailMessageIdByTab.delete(tabId);
    }
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
  // Act on URL changes (covers SPA hash navigation like Gmail), status=complete
  // (covers full page loads), or title changes (covers late title updates).
  if (changeInfo.url || changeInfo.status === "complete" || changeInfo.title) {
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

// Receive Gmail message IDs from the content script.
// Cache the ID and re-emit a focus event so the server can patch the meta on
// the existing observation (the content script fires ~300ms after the initial
// focus event, after which the original observation has no meta yet).
chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type === "gmail_message_id" && sender.tab?.id != null) {
    const tabId = sender.tab.id;
    gmailMessageIdByTab.set(tabId, message.messageId as string);

    // Re-emit focus with meta so the server patches the existing observation
    chrome.tabs.get(tabId, async (tab) => {
      if (tab?.url?.includes("mail.google.com")) {
        await emitFocus(tabId, tab.url, tab.title ?? "");
      }
    });
  }
});

// Clear cached message ID when a tab navigates away from a Gmail thread
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url && !changeInfo.url.includes("mail.google.com")) {
    gmailMessageIdByTab.delete(tabId);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  gmailMessageIdByTab.delete(tabId);
});

// On service worker startup: flush any queued events from a previous session
flush().catch(() => {/* best-effort */});
