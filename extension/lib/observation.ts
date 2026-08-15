/**
 * Browser observation tracker: reports observation duration after the user spends
 * observation_threshold_ms on a URL that matches a connector pattern.
 *
 * Patterns and threshold are fetched from the server on startup and cached
 * in chrome.storage.local so they survive service-worker restarts.
 */

import { getMetaUrl, getServerBaseUrl, getReportObservationUrl } from "./config.js";

const CACHE_KEY = "agentgraph_meta_cache";
const DEFAULT_THRESHOLD_MS = 3000;

interface MetaCache {
  url_patterns: string[];
  observation_threshold_ms: number;
  fetched_at: number; // ms since epoch
}

export interface ObservationMeta {
  url_patterns: string[];
  observation_threshold_ms: number;
}

export interface ObservationStatus {
  observation_id?: string;
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
  threshold_reported_at?: number;
  threshold_accepted?: boolean;
  pending_observation_duration_ms?: number;
}

// In-memory state — rebuilt from cache on service worker restart.
let patterns: string[] = [];
let thresholdMs: number = DEFAULT_THRESHOLD_MS;

// Per-tab: { timer, url, meta }
interface ObservationEntry {
  observation_id: string;
  timer: ReturnType<typeof setTimeout>;
  url: string;
  meta: Record<string, string>;
  started_at: number;
  fires_at: number;
}

interface ReportResult {
  ok: boolean;
  http_status?: number;
  error?: string;
}

const pending = new Map<number, ObservationEntry>();
const observations = new Map<number, ObservationStatus>();

// ---------------------------------------------------------------------------
// Pattern matching
// ---------------------------------------------------------------------------

/**
 * Match exact URL rules and Chrome-style path-prefix rules.
 */
function matchesAny(url: string, pats: string[]): boolean {
  for (const pat of pats) {
    if (pat.endsWith("/*") ? url.startsWith(pat.slice(0, -1)) : url === pat) return true;
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
    thresholdMs = cache.observation_threshold_ms;
  }
}

export async function refreshMeta(options: { throwOnError?: boolean } = {}): Promise<ObservationMeta> {
  try {
    const serverBaseUrl = await getServerBaseUrl();
    const resp = await fetch(getMetaUrl(serverBaseUrl), { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) {
      throw new Error(`Metadata refresh failed: HTTP ${resp.status}`);
    }
    const data = await resp.json() as { url_patterns?: string[]; observation_threshold_ms?: number };
    patterns = data.url_patterns ?? [];
    thresholdMs = data.observation_threshold_ms ?? DEFAULT_THRESHOLD_MS;
    const cache: MetaCache = {
      url_patterns: patterns,
      observation_threshold_ms: thresholdMs,
      fetched_at: Date.now(),
    };
    await chrome.storage.local.set({ [CACHE_KEY]: cache });
  } catch (error: unknown) {
    if (options.throwOnError) throw error;
    // Server not running — keep cached values
  }

  return { url_patterns: patterns, observation_threshold_ms: thresholdMs };
}

// ---------------------------------------------------------------------------
// Observation timer management
// ---------------------------------------------------------------------------

export function startObservation(
  tabId: number,
  url: string,
  meta: Record<string, string> = {},
): void {
  cancelObservation(tabId);
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
  const observationId = crypto.randomUUID();
  observations.set(tabId, {
    observation_id: observationId,
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
    const obs = observations.get(tabId);
    if (obs && obs.matches) {
      obs.state = "sending";
      obs.threshold_reported_at = Date.now();
      void sendReportObservation(
        obs.url,
        thresholdMs,
        observationId,
        true,
        obs.meta || {},
      ).then((result) => {
        obs.http_status = result.http_status;
        if (result.ok) {
          obs.threshold_accepted = true;
          obs.sent_at = Date.now();
          if (obs.pending_observation_duration_ms && obs.pending_observation_duration_ms > 0) {
            void sendReportObservation(
              obs.url,
              obs.pending_observation_duration_ms,
              observationId,
              false,
              obs.meta || {},
            );
            obs.pending_observation_duration_ms = undefined;
          }
          if (observations.get(tabId) === obs && obs.state === "sending") {
            obs.state = "sent";
          }
        } else {
          obs.pending_observation_duration_ms = undefined;
          obs.error = result.error;
          if (observations.get(tabId) === obs && obs.state === "sending") {
            obs.state = "failed";
          }
        }
      });
    }
  }, thresholdMs);

  pending.set(tabId, {
    observation_id: observationId,
    timer,
    url,
    meta,
    started_at: startedAt,
    fires_at: firesAt,
  });
}

export function cancelObservation(tabId: number): void {
  const entry = pending.get(tabId);
  if (entry) {
    clearTimeout(entry.timer);
    pending.delete(tabId);
  }

  const obs = observations.get(tabId);
  if (obs && obs.matches && obs.started_at) {
    obs.state = "canceled";
    const elapsed = Date.now() - obs.started_at;
    if (elapsed > 0) {
      const meta = entry?.meta || obs.meta || {};

      // A visit becomes an observation only after it reaches the observation threshold.
      if (obs.threshold_reported_at && obs.observation_id) {
        const remaining = elapsed - thresholdMs;
        if (remaining > 0) {
          if (obs.threshold_accepted) {
            void sendReportObservation(
              obs.url,
              remaining,
              obs.observation_id,
              false,
              meta,
            );
          } else {
            obs.pending_observation_duration_ms = remaining;
          }
        }
      }
    }
    // Prevent double-reporting if cancelObservation is called multiple times
    obs.started_at = undefined;
    obs.threshold_reported_at = undefined;
  }
}

/** Update pending meta and report whether this tab already has an observation. */
export function updateMeta(tabId: number, extra: Record<string, string>): boolean {
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
  return entry !== undefined || obs !== undefined;
}

// ---------------------------------------------------------------------------
// Server request
// ---------------------------------------------------------------------------

export async function sendReportObservation(
  url: string,
  durationMs: number,
  observationId: string,
  observed: boolean,
  meta: Record<string, string>,
): Promise<ReportResult> {
  try {
    const serverBaseUrl = await getServerBaseUrl();
    const response = await fetch(getReportObservationUrl(serverBaseUrl), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        observation_duration_ms: durationMs,
        observation_id: observationId,
        observed,
        meta: Object.keys(meta).length ? meta : undefined,
      }),
    });
    if (!response.ok) {
      let detail: string | undefined;
      try {
        const body = await response.json() as { detail?: unknown };
        if (typeof body.detail === "string" && body.detail) detail = body.detail;
      } catch {
        // Error responses are not required to contain JSON.
      }
      const error = detail ? `HTTP ${response.status}: ${detail}` : `HTTP ${response.status}`;
      console.error(`POST /report-observation failed with ${error}`);
      return { ok: false, http_status: response.status, error };
    }
    return { ok: true, http_status: response.status };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Unknown error";
    console.error(`POST /report-observation failed: ${message}`);
    return { ok: false, error: message };
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
