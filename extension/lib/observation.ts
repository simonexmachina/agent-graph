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
 * Match a URL against Chrome-style match patterns.
 *
 * Connectors declare patterns as `<scheme>://<host>[:<port>]/<path>`, where the
 * host may begin with `*.` to cover a domain and its subdomains, and `*` in the
 * path matches any span of characters — including `/`, unlike a filesystem glob.
 * A pattern without a port matches any port; one with a port requires it.
 * Patterns without a wildcard match exactly.
 *
 * Mirrored in Python by `agentgraph.connectors.match_patterns.matches_pattern`;
 * `tests/fixtures/url_match_cases.json` holds the shared test vectors.
 */
export function matchesPattern(url: string, pattern: string): boolean {
  const patternParts = splitPattern(pattern);
  if (patternParts === null) return url === pattern;

  let target: URL;
  try {
    target = new URL(url);
  } catch {
    return false;
  }

  if (patternParts.scheme !== "*" && `${patternParts.scheme}:` !== target.protocol) return false;
  if (!portMatches(target, patternParts.port)) return false;
  if (!hostMatches(target.hostname, patternParts.host)) return false;
  return wildcardRegExp(patternParts.path).test(`${target.pathname}${target.search}`);
}

interface PatternParts {
  scheme: string;
  host: string;
  port: string;
  path: string;
}

function splitPattern(pattern: string): PatternParts | null {
  const schemeEnd = pattern.indexOf("://");
  if (schemeEnd === -1) return null;
  const scheme = pattern.slice(0, schemeEnd);
  const rest = pattern.slice(schemeEnd + 3);
  const pathStart = rest.indexOf("/");
  const authority = pathStart === -1 ? rest : rest.slice(0, pathStart);
  const path = pathStart === -1 ? "/*" : rest.slice(pathStart);
  return { scheme, ...splitAuthority(authority), path };
}

/** Peel a trailing `:<digits>` off the host, leaving `*` and IPv6-ish hosts intact. */
function splitAuthority(authority: string): { host: string; port: string } {
  const portStart = authority.lastIndexOf(":");
  if (portStart === -1) return { host: authority, port: "" };
  const port = authority.slice(portStart + 1);
  if (!/^\d+$/.test(port)) return { host: authority, port: "" };
  return { host: authority.slice(0, portStart), port };
}

function portMatches(target: URL, patternPort: string): boolean {
  // A pattern without a port matches any port, as Chrome match patterns do.
  if (patternPort === "") return true;
  return normalisePort(patternPort, target.protocol) === target.port;
}

/** `URL.port` is empty for a scheme's default port, so normalise the pattern the same way. */
function normalisePort(port: string, protocol: string): string {
  if (protocol === "http:" && port === "80") return "";
  if (protocol === "https:" && port === "443") return "";
  return port;
}

function hostMatches(hostname: string, hostPattern: string): boolean {
  const host = hostname.toLowerCase();
  const expected = hostPattern.toLowerCase();
  if (expected === "*") return true;
  if (expected.startsWith("*.")) {
    const domain = expected.slice(2);
    return host === domain || host.endsWith(`.${domain}`);
  }
  return host === expected;
}

function wildcardRegExp(pathPattern: string): RegExp {
  const escaped = pathPattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
  return new RegExp(`^${escaped}$`);
}

function matchesAny(url: string, pats: string[]): boolean {
  return pats.some((pattern) => matchesPattern(url, pattern));
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
