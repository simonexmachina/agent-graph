/**
 * Gmail content script — extracts Gmail identifiers from the DOM and sends
 * them to the background service worker whenever a thread is viewed.
 *
 * We capture both legacy API IDs and Gmail UI-specific IDs/URLs. The API IDs
 * let the backend fetch the correct thread, while the UI IDs let us preserve a
 * working Gmail link instead of guessing from the API thread ID.
 */

// A thread URL ends with 16+ alphanumeric chars after the last '/'.
// Handles all hash patterns Gmail uses:
//   #inbox/{token}
//   #search/{query}/{token}       ← query may contain % encoded chars
//   #sent/{token}, etc.
const GMAIL_THREAD_HASH_RE = /\/[A-Za-z0-9_+=:\-|]{16,}$/;
const HEX_ID_RE = /^[0-9a-f]{16,}$/;
const UI_MESSAGE_ID_RE = /^msg-[^:]+:.+$/;
const UI_THREAD_ID_RE = /^thread-[^:]+:.+$/;

interface GmailMetaPayload {
  gmail_message_id?: string;
  gmail_thread_id?: string;
  gmail_ui_message_id?: string;
  gmail_ui_thread_id?: string;
  gmail_popout_url?: string;
}

function isThreadUrl(): boolean {
  return GMAIL_THREAD_HASH_RE.test(location.hash);
}

function extractThreadElement(): HTMLElement | null {
  return (
    document.querySelector<HTMLElement>("[data-legacy-thread-id]") ??
    document.querySelector<HTMLElement>("[data-thread-id]") ??
    document.querySelector<HTMLElement>("[data-legacy-message-id]") ??
    document.querySelector<HTMLElement>("[data-message-id]")
  );
}

function extractAccountIndex(): string {
  const match = location.pathname.match(/\/mail\/u\/([^/]+)\//);
  return match?.[1] ?? "0";
}

function extractSearchScope(): string {
  const hash = location.hash.startsWith("#") ? location.hash.slice(1) : location.hash;
  const [first] = hash.split("/");
  if (!first || UI_THREAD_ID_RE.test(first)) return "all";
  return first === "search" ? "query" : first;
}

function extractPopoutUrlFromDom(): string | null {
  const anchor = document.querySelector<HTMLAnchorElement>('a[href*="/popout?"]');
  if (!anchor?.href) return null;
  return new URL(anchor.href, location.origin).toString();
}

function buildPopoutUrl(threadId: string, messageId: string | undefined): string {
  const url = new URL(`https://mail.google.com/mail/u/${extractAccountIndex()}/popout`);
  url.searchParams.set("search", extractSearchScope());
  url.searchParams.set("th", `#${threadId}${messageId ? `|${messageId}` : ""}`);
  url.searchParams.set("cvid", "1");
  return url.toString();
}

function extractMeta(): GmailMetaPayload | null {
  const el = extractThreadElement();
  if (!el) return null;

  const meta: GmailMetaPayload = {};
  if (el.dataset.legacyMessageId && HEX_ID_RE.test(el.dataset.legacyMessageId)) {
    meta.gmail_message_id = el.dataset.legacyMessageId;
  }
  if (el.dataset.legacyThreadId && HEX_ID_RE.test(el.dataset.legacyThreadId)) {
    meta.gmail_thread_id = el.dataset.legacyThreadId;
  }
  if (el.dataset.messageId && UI_MESSAGE_ID_RE.test(el.dataset.messageId)) {
    meta.gmail_ui_message_id = el.dataset.messageId;
  }
  if (el.dataset.threadId && UI_THREAD_ID_RE.test(el.dataset.threadId)) {
    meta.gmail_ui_thread_id = el.dataset.threadId;
  }

  meta.gmail_popout_url = extractPopoutUrlFromDom() ?? undefined;
  if (!meta.gmail_popout_url && meta.gmail_ui_thread_id) {
    meta.gmail_popout_url = buildPopoutUrl(meta.gmail_ui_thread_id, meta.gmail_ui_message_id);
  }

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

// Gmail uses hash-based SPA routing — fire on every hash navigation
window.addEventListener("hashchange", scheduleReport);

// Also fire on initial page load (e.g. direct link to a thread)
scheduleReport();
