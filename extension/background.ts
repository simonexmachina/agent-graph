/**
 * Service worker: dwell-based fetch trigger.
 *
 * URL patterns and the dwell threshold are loaded from the AgentGraph server
 * on startup. When the user focuses a matching URL for longer than the
 * threshold, a POST /fetch-url request is sent to the server.
 */

import {
  init,
  startDwell,
  cancelDwell,
  getObservationStatus,
  refreshMeta,
  updateMeta,
} from "./lib/dwell.js";

// Hex Gmail message IDs extracted by the content script, keyed by tab ID.
const gmailMessageIdByTab = new Map<number, string>();

// ---------------------------------------------------------------------------
// Tab tracking helpers
// ---------------------------------------------------------------------------

let activeTabId: number | null = null;
let activeUrl: string = "";

async function onFocus(tabId: number): Promise<void> {
  let tab: chrome.tabs.Tab;
  try {
    tab = await chrome.tabs.get(tabId);
  } catch {
    return;
  }

  const url = tab.url ?? "";
  if (!url.startsWith("http://") && !url.startsWith("https://")) return;

  if (tabId !== activeTabId || url !== activeUrl) {
    if (activeTabId !== null) cancelDwell(activeTabId);
    activeTabId = tabId;
    activeUrl = url;

    const meta: Record<string, string> = {};
    const gmailId = gmailMessageIdByTab.get(tabId);
    if (gmailId) meta.gmail_message_id = gmailId;

    startDwell(tabId, url, meta);
  }
}

function onBlur(): void {
  if (activeTabId !== null) {
    cancelDwell(activeTabId);
    activeTabId = null;
    activeUrl = "";
  }
}

// ---------------------------------------------------------------------------
// Chrome event listeners
// ---------------------------------------------------------------------------

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  await onFocus(tabId);
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, _tab) => {
  if (changeInfo.url || changeInfo.status === "complete" || changeInfo.title) {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (activeTab?.id === tabId) {
      await onFocus(tabId);
    }
  }
});

chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    onBlur();
    return;
  }
  const [activeTab] = await chrome.tabs.query({ active: true, windowId });
  if (activeTab?.id != null) {
    await onFocus(activeTab.id);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  cancelDwell(tabId);
  gmailMessageIdByTab.delete(tabId);
  if (activeTabId === tabId) {
    activeTabId = null;
    activeUrl = "";
  }
});

// ---------------------------------------------------------------------------
// Gmail content script messages
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type === "gmail_message_id" && sender.tab?.id != null) {
    const tabId = sender.tab.id;
    const messageId = message.messageId as string;
    gmailMessageIdByTab.set(tabId, messageId);
    // Inject into any pending dwell for this tab (content script fires ~300ms
    // after navigation, well within the 3s threshold).
    updateMeta(tabId, { gmail_message_id: messageId });
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "server_url_updated") return false;

  chrome.storage.local.remove("agentgraph_meta_cache")
    .then(async () => {
      const meta = await refreshMeta();
      if (activeTabId !== null) {
        activeUrl = "";
        await onFocus(activeTabId);
      }
      sendResponse({ ok: true, meta });
    })
    .catch((error: unknown) => {
      sendResponse({ ok: false, error: error instanceof Error ? error.message : "Unknown error" });
    });

  return true;
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "reload_url_patterns") return false;

  refreshMeta()
    .then(async (meta) => {
      if (activeTabId !== null) {
        activeUrl = "";
        await onFocus(activeTabId);
      }
      sendResponse({ ok: true, meta });
    })
    .catch((error: unknown) => {
      sendResponse({ ok: false, error: error instanceof Error ? error.message : "Unknown error" });
    });

  return true;
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "get_observation_status") return false;

  chrome.tabs.query({ active: true, currentWindow: true })
    .then(async ([tab]) => {
      if (tab?.id == null || tab.url == null) {
        sendResponse({ ok: true, status: null });
        return;
      }
      await onFocus(tab.id);
      sendResponse({ ok: true, status: getObservationStatus(tab.id, tab.url) });
    })
    .catch((error: unknown) => {
      sendResponse({ ok: false, error: error instanceof Error ? error.message : "Unknown error" });
    });

  return true;
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url && !changeInfo.url.includes("mail.google.com")) {
    gmailMessageIdByTab.delete(tabId);
  }
});

// ---------------------------------------------------------------------------
// Startup
// ---------------------------------------------------------------------------

init().catch(() => {/* server may not be running yet */});
