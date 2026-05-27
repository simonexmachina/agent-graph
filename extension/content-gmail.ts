/**
 * Gmail content script — extracts Gmail identifiers from the DOM and sends
 * them to the background service worker whenever a thread is viewed.
 *
 * We capture Gmail IDs from the DOM so the backend can fetch the correct
 * thread via the Gmail API even when the visible URL uses Gmail's opaque
 * browser-only token.
 */

// A thread URL ends with 16+ alphanumeric chars after the last '/'.
// Handles all hash patterns Gmail uses:
//   #inbox/{token}
//   #search/{query}/{token}       ← query may contain % encoded chars
//   #sent/{token}, etc.
const GMAIL_THREAD_HASH_RE = /\/[A-Za-z0-9_+=:\-|]{16,}$/;
const HEX_ID_RE = /^[0-9a-f]{16,}$/;
interface GmailMetaPayload {
  gmail_message_id?: string;
  gmail_thread_id?: string;
}

function isThreadUrl(): boolean {
  return GMAIL_THREAD_HASH_RE.test(location.hash);
}

function findAttrValue(
  selector: string,
  attr: string,
  pattern: RegExp,
): string | undefined {
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(selector))) {
    const value = el.getAttribute(attr);
    if (value && pattern.test(value)) return value;
  }
  return undefined;
}

function extractMeta(): GmailMetaPayload | null {
  const meta: GmailMetaPayload = {};
  meta.gmail_message_id = findAttrValue("[data-legacy-message-id]", "data-legacy-message-id", HEX_ID_RE);
  meta.gmail_thread_id = findAttrValue("[data-legacy-thread-id]", "data-legacy-thread-id", HEX_ID_RE);
  return Object.keys(meta).length > 0 ? meta : null;
}

let lastUrl = "";
let lastMeta = "";
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

function reportIfChanged(): void {
  if (!isThreadUrl()) return;

  const meta = extractMeta();
  if (!meta) return;

  const url = location.href;
  const metaKey = JSON.stringify(meta);
  if (url === lastUrl && metaKey === lastMeta) return;

  lastUrl = url;
  lastMeta = metaKey;
  chrome.runtime.sendMessage({ type: "gmail_meta", meta });
}

function scheduleReport(): void {
  if (debounceTimer !== null) clearTimeout(debounceTimer);
  // Short delay: Gmail renders the thread asynchronously after URL change
  debounceTimer = setTimeout(reportIfChanged, 300);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "agentgraph_get_gmail_meta") return false;
  sendResponse({ meta: extractMeta() });
  return false;
});

// Gmail uses hash-based SPA routing — fire on every hash navigation
window.addEventListener("hashchange", scheduleReport);

// Also fire on initial page load (e.g. direct link to a thread)
scheduleReport();
