/**
 * Dwell tracker: fires a /fetch-url request after the user spends
 * dwell_threshold_ms on a URL that matches a connector pattern.
 *
 * Patterns and threshold are fetched from the server on startup and cached
 * in chrome.storage.local so they survive service-worker restarts.
 */

import { getFetchUrl, getMetaUrl, getServerBaseUrl, getReportDwellUrl } from "./config.js";

const CACHE_KEY = "agentgraph_meta_cache";
const DEFAULT_THRESHOLD_MS = 3000;

interface MetaCache {
  url_patterns: string[];
  dwell_threshold_ms: number;
  fetched_at: number; // ms since epoch
}

export interface DwellMeta {
  url_patterns: string[];
  dwell_threshold_ms: number;
}

export interface ObservationStatus {
  url: string;
  matches: boolean;
  state: "not_matched" | "waiting" | "sending" | "sent" | "failed" | "canceled";
  threshold_ms: number;
  started_at?: number;
  fires_at?: number;
  sent_at?: number;
  http_status?: number;
  error?: string;
  meta?: Record<string, string>;
}

// In-memory state — rebuilt from cache on service worker restart.
let patterns: string[] = [];
let thresholdMs: number = DEFAULT_THRESHOLD_MS;

// Per-tab: { timer, url, meta }
interface DwellEntry {
  timer: ReturnType<typeof setTimeout>;
  url: string;
  meta: Record<string, string>;
  started_at: number;
  fires_at: number;
}
const pending = new Map<number, DwellEntry>();
const observations = new Map<number, ObservationStatus>();

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

export async function refreshMeta(): Promise<DwellMeta> {
  try {
    const serverBaseUrl = await getServerBaseUrl();
    const resp = await fetch(getMetaUrl(serverBaseUrl), { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) return { url_patterns: patterns, dwell_threshold_ms: thresholdMs };
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

  return { url_patterns: patterns, dwell_threshold_ms: thresholdMs };
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
  if (!matchesAny(url, patterns)) {
    observations.set(tabId, {
      url,
      matches: false,
      state: "not_matched",
      threshold_ms: thresholdMs,
    });
    return;
  }

  const startedAt = Date.now();
  const firesAt = startedAt + thresholdMs;
  observations.set(tabId, {
    url,
    matches: true,
    state: "waiting",
    threshold_ms: thresholdMs,
    started_at: startedAt,
    fires_at: firesAt,
    meta,
  });

  const timer = setTimeout(() => {
    pending.delete(tabId);
    observations.set(tabId, {
      url,
      matches: true,
      state: "sending",
      threshold_ms: thresholdMs,
      started_at: startedAt,
      fires_at: firesAt,
      meta,
    });

    sendFetch(url, meta)
      .then((httpStatus) => {
        observations.set(tabId, {
          url,
          matches: true,
          state: "sent",
          threshold_ms: thresholdMs,
          started_at: startedAt,
          fires_at: firesAt,
          sent_at: Date.now(),
          http_status: httpStatus,
          meta,
        });
      })
      .catch((error: unknown) => {
        observations.set(tabId, {
          url,
          matches: true,
          state: "failed",
          threshold_ms: thresholdMs,
          started_at: startedAt,
          fires_at: firesAt,
          sent_at: Date.now(),
          error: error instanceof Error ? error.message : "Unknown error",
          meta,
        });
      });
  }, thresholdMs);

  pending.set(tabId, { timer, url, meta, started_at: startedAt, fires_at: firesAt });
}

export function cancelDwell(tabId: number): void {
  const entry = pending.get(tabId);
  if (entry) {
    clearTimeout(entry.timer);
    pending.delete(tabId);
    observations.set(tabId, {
      url: entry.url,
      matches: true,
      state: "canceled",
      threshold_ms: thresholdMs,
      started_at: entry.started_at,
      fires_at: entry.fires_at,
      meta: entry.meta,
    });
  }

  // Track dwell time across the entire focus session (not just pending)
  const obs = observations.get(tabId);
  if (obs && obs.matches && obs.started_at) {
    const elapsed = Date.now() - obs.started_at;
    if (elapsed > 0) {
      const meta = entry?.meta || obs.meta || {};
      void sendReportDwell(obs.url, elapsed, meta);
    }
    // Prevent double-reporting if cancelDwell is called multiple times
    obs.started_at = undefined;
  }
}

/** Update pending meta for a tab (e.g. Gmail message ID arrives after focus). */
export function updateMeta(tabId: number, extra: Record<string, string>): void {
  const entry = pending.get(tabId);
  if (entry) {
    Object.assign(entry.meta, extra);
  }
  const obs = observations.get(tabId);
  if (obs && obs.meta) {
    Object.assign(obs.meta, extra);
  } else if (obs) {
    obs.meta = { ...extra };
  }
}

// ---------------------------------------------------------------------------
// Server request
// ---------------------------------------------------------------------------

async function sendFetch(url: string, meta: Record<string, string>): Promise<number> {
  const serverBaseUrl = await getServerBaseUrl();
  const response = await fetch(getFetchUrl(serverBaseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, meta: Object.keys(meta).length ? meta : undefined }),
  });
  if (!response.ok) {
    throw new Error(`POST /fetch-url failed with HTTP ${response.status}`);
  }
  return response.status;
}

export async function sendReportDwell(url: string, dwellMs: number, meta: Record<string, string>): Promise<void> {
  const serverBaseUrl = await getServerBaseUrl();
  const response = await fetch(getReportDwellUrl(serverBaseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, dwell_ms: dwellMs, meta: Object.keys(meta).length ? meta : undefined }),
  });
  if (!response.ok) {
    console.error(`POST /report-dwell failed with HTTP ${response.status}`);
  }
}

export function getObservationStatus(tabId: number, url: string): ObservationStatus {
  const current = observations.get(tabId);
  if (current?.url === url) return current;

  const matches = matchesAny(url, patterns);
  return {
    url,
    matches,
    state: matches ? "canceled" : "not_matched",
    threshold_ms: thresholdMs,
  };
}

// ---------------------------------------------------------------------------
// Initialise: load cache then refresh from server
// ---------------------------------------------------------------------------

export async function init(): Promise<void> {
  await loadCachedMeta();
  await refreshMeta();
}
