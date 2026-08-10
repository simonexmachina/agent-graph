/**
 * Service worker: dwell-based fetch trigger.
 *
 * URL patterns and the dwell threshold are loaded from the AgentGraph server
 * on startup. When the user focuses a matching URL for longer than the
 * threshold, a POST /report-dwell request is sent to the server.
 */

import {
  init,
  startDwell,
  cancelDwell,
  getObservationStatus,
  refreshMeta,
  updateMeta,
} from "./lib/dwell.js";

// Gmail metadata extracted by the content script, keyed by tab ID.
const gmailMetaByTab = new Map<number, Record<string, string>>();
const META_REFRESH_ALARM = "agentgraph_refresh_meta";
const META_REFRESH_PERIOD_MINUTES = 15;

// ---------------------------------------------------------------------------
// Tab tracking helpers
// ---------------------------------------------------------------------------

let activeTabId: number | null = null;
let activeUrl: string = "";
const gmailMetaRetryByTab = new Map<number, ReturnType<typeof setTimeout>>();

function clearGmailMetaRetry(tabId: number): void {
  const timer = gmailMetaRetryByTab.get(tabId);
  if (timer) {
    clearTimeout(timer);
    gmailMetaRetryByTab.delete(tabId);
  }
}

function hasUsableGmailMeta(meta: Record<string, string>): boolean {
  return Boolean(meta.gmail_message_id || meta.gmail_thread_id);
}

async function fetchGmailMetaFromTab(tabId: number): Promise<Record<string, string>> {
  try {
    const response = await chrome.tabs.sendMessage(tabId, { type: "agentgraph_get_gmail_meta" }) as {
      meta?: Record<string, string> | null;
    };
    return response?.meta ?? {};
  } catch {
    return {};
  }
}

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
    clearGmailMetaRetry(tabId);
    if (activeTabId !== null) cancelDwell(activeTabId);
    activeTabId = tabId;
    activeUrl = url;

    let meta = { ...(gmailMetaByTab.get(tabId) ?? {}) };
    if (url.includes("mail.google.com")) {
      const liveMeta = await fetchGmailMetaFromTab(tabId);
      if (Object.keys(liveMeta).length > 0) {
        meta = { ...meta, ...liveMeta };
        gmailMetaByTab.set(tabId, meta);
      }

      const looksLikeGmailThread = /https:\/\/mail\.google\.com\/mail\/u\/\d+\/#.+\/[^/]+$/.test(url);
      if (looksLikeGmailThread && !hasUsableGmailMeta(meta)) {
        gmailMetaRetryByTab.set(tabId, setTimeout(() => {
          if (activeTabId === tabId) {
            activeUrl = "";
            void onFocus(tabId);
          }
        }, 500));
        return;
      }
    }

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
  gmailMetaByTab.delete(tabId);
  clearGmailMetaRetry(tabId);
  if (activeTabId === tabId) {
    activeTabId = null;
    activeUrl = "";
  }
});

// ---------------------------------------------------------------------------
// Gmail content script messages
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type === "gmail_meta" && sender.tab?.id != null) {
    const tabId = sender.tab.id;
    const meta = message.meta as Record<string, string>;
    const mergedMeta = { ...(gmailMetaByTab.get(tabId) ?? {}), ...meta };
    gmailMetaByTab.set(tabId, mergedMeta);
    // Inject into any pending dwell for this tab (content script fires ~300ms
    // after navigation, well within the 3s threshold).
    updateMeta(tabId, mergedMeta);
    if (activeTabId === tabId && sender.tab.url === activeUrl && hasUsableGmailMeta(mergedMeta)) {
      clearGmailMetaRetry(tabId);
      activeUrl = "";
      void onFocus(tabId);
    }
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "server_url_updated") return false;

  chrome.storage.local.remove("agentgraph_meta_cache")
    .then(async () => {
      const meta = await refreshMeta({ throwOnError: true });
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

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== META_REFRESH_ALARM) return;
  void refreshPatternsAndRestartObservation();
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "reload_url_patterns") return false;

  refreshMeta({ throwOnError: true })
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
    gmailMetaByTab.delete(tabId);
    clearGmailMetaRetry(tabId);
  }
});

// ---------------------------------------------------------------------------
// Startup
// ---------------------------------------------------------------------------

async function refreshPatternsAndRestartObservation(): Promise<void> {
  await refreshMeta();
  if (activeTabId !== null) {
    activeUrl = "";
    await onFocus(activeTabId);
  }
}

async function initialiseBackground(): Promise<void> {
  await init();
  await chrome.alarms.create(META_REFRESH_ALARM, {
    periodInMinutes: META_REFRESH_PERIOD_MINUTES,
  });
}

initialiseBackground().catch(() => {/* server may not be running yet */});
