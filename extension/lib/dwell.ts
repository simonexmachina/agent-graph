/**
 * Dwell tracker: fires a /fetch-url request after the user spends
 * dwell_threshold_ms on a URL that matches a connector pattern.
 *
 * Patterns and threshold are fetched from the server on startup and cached
 * in chrome.storage.local so they survive service-worker restarts.
 */

const SERVER_BASE = "http://localhost:8765";
const META_URL = `${SERVER_BASE}/api/cli/meta`;
const FETCH_URL = `${SERVER_BASE}/fetch-url`;

const CACHE_KEY = "agentgraph_meta_cache";
const DEFAULT_THRESHOLD_MS = 3000;

interface MetaCache {
  url_patterns: string[];
  dwell_threshold_ms: number;
  fetched_at: number; // ms since epoch
}

// In-memory state — rebuilt from cache on service worker restart.
let patterns: string[] = [];
let thresholdMs: number = DEFAULT_THRESHOLD_MS;

// Per-tab: { timer, url, meta }
interface DwellEntry {
  timer: ReturnType<typeof setTimeout>;
  url: string;
  meta: Record<string, string>;
}
const pending = new Map<number, DwellEntry>();

// ---------------------------------------------------------------------------
// Pattern matching
// ---------------------------------------------------------------------------

/**
 * Match a URL against a Chrome match pattern (supports * wildcard in path).
 * We only need simple prefix matching since all our patterns end with /*.
 */
function matchesAny(url: string, pats: string[]): boolean {
  for (const pat of pats) {
    // Convert "https://mail.google.com/*" → prefix "https://mail.google.com/"
    const prefix = pat.endsWith("/*") ? pat.slice(0, -1) : pat.replace(/\*$/, "");
    if (url.startsWith(prefix)) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Server meta fetch + cache
// ---------------------------------------------------------------------------

async function loadCachedMeta(): Promise<void> {
  const result = await chrome.storage.local.get(CACHE_KEY);
  const cache = result[CACHE_KEY] as MetaCache | undefined;
  if (cache) {
    patterns = cache.url_patterns;
    thresholdMs = cache.dwell_threshold_ms;
  }
}

async function refreshMeta(): Promise<void> {
  try {
    const resp = await fetch(META_URL, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) return;
    const data = await resp.json() as { url_patterns?: string[]; dwell_threshold_ms?: number };
    patterns = data.url_patterns ?? [];
    thresholdMs = data.dwell_threshold_ms ?? DEFAULT_THRESHOLD_MS;
    const cache: MetaCache = {
      url_patterns: patterns,
      dwell_threshold_ms: thresholdMs,
      fetched_at: Date.now(),
    };
    await chrome.storage.local.set({ [CACHE_KEY]: cache });
  } catch {
    // Server not running — keep cached values
  }
}

// ---------------------------------------------------------------------------
// Dwell timer management
// ---------------------------------------------------------------------------

export function startDwell(
  tabId: number,
  url: string,
  meta: Record<string, string> = {},
): void {
  cancelDwell(tabId);
  if (!matchesAny(url, patterns)) return;

  const timer = setTimeout(() => {
    pending.delete(tabId);
    sendFetch(url, meta).catch(() => {/* best-effort */});
  }, thresholdMs);

  pending.set(tabId, { timer, url, meta });
}

export function cancelDwell(tabId: number): void {
  const entry = pending.get(tabId);
  if (entry) {
    clearTimeout(entry.timer);
    pending.delete(tabId);
  }
}

/** Update pending meta for a tab (e.g. Gmail message ID arrives after focus). */
export function updateMeta(tabId: number, extra: Record<string, string>): void {
  const entry = pending.get(tabId);
  if (entry) {
    Object.assign(entry.meta, extra);
  }
}

// ---------------------------------------------------------------------------
// Server request
// ---------------------------------------------------------------------------

async function sendFetch(url: string, meta: Record<string, string>): Promise<void> {
  await fetch(FETCH_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, meta: Object.keys(meta).length ? meta : undefined }),
  });
}

// ---------------------------------------------------------------------------
// Initialise: load cache then refresh from server
// ---------------------------------------------------------------------------

export async function init(): Promise<void> {
  await loadCachedMeta();
  await refreshMeta();
}
