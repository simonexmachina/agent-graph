/**
 * Gmail content script — extracts the hex message ID from the DOM and sends
 * it to the background service worker whenever a thread is viewed.
 *
 * Gmail is an SPA: URL hash changes don't reload the page. We use a
 * MutationObserver to detect when a thread renders and extract its message ID
 * from the `data-legacy-message-id` attribute Gmail sets on each message element.
 *
 * The hex ID extracted here (e.g. "19d2cdaaeb487302") is the same ID used by
 * the Gmail REST API — unlike the URL token (FMfcgzQ...) which is Gmail's own
 * proprietary encoding incompatible with the API.
 */

// A thread URL ends with 16+ alphanumeric chars after the last '/'.
// Handles all hash patterns Gmail uses:
//   #inbox/{token}
//   #search/{query}/{token}       ← query may contain % encoded chars
//   #sent/{token}, etc.
const GMAIL_THREAD_HASH_RE = /\/[A-Za-z0-9_+=\-]{16,}$/;

function isThreadUrl(): boolean {
  return GMAIL_THREAD_HASH_RE.test(location.hash);
}

/** Extract the first hex message ID from the rendered thread. */
function extractMessageId(): string | null {
  // Gmail sets data-legacy-message-id on each message container
  const el =
    document.querySelector<HTMLElement>("[data-legacy-message-id]") ??
    document.querySelector<HTMLElement>("[data-message-id]");
  return el?.dataset.legacyMessageId ?? el?.dataset.messageId ?? null;
}

let lastUrl = "";
let lastMessageId = "";
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

function reportIfChanged(): void {
  if (!isThreadUrl()) return;

  const messageId = extractMessageId();
  console.log({messageId})
  if (!messageId) return;

  const url = location.href;
  if (url === lastUrl && messageId === lastMessageId) return;

  lastUrl = url;
  lastMessageId = messageId;

  chrome.runtime.sendMessage({ type: "gmail_message_id", messageId });
}

function scheduleReport(): void {
  if (debounceTimer !== null) clearTimeout(debounceTimer);
  // Short delay: Gmail renders the thread asynchronously after URL change
  debounceTimer = setTimeout(reportIfChanged, 300);
}

// Gmail uses hash-based SPA routing — fire on every hash navigation
window.addEventListener("hashchange", scheduleReport);

// Also fire on initial page load (e.g. direct link to a thread)
scheduleReport();
