import assert from "node:assert/strict";
import test from "node:test";

const storage = new Map();

globalThis.chrome = {
  storage: {
    local: {
      async get(key) {
        return { [key]: storage.get(key) };
      },
      async set(values) {
        for (const [key, value] of Object.entries(values)) storage.set(key, value);
      },
    },
  },
};

const {
  cancelObservation,
  getObservationStatus,
  matchesPattern,
  refreshMeta,
  startObservation,
  updateMeta,
} = await import("../dist/lib/observation.js");

async function waitForTerminalStatus(tabId, url) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const status = getObservationStatus(tabId, url);
    if (status.state === "sent" || status.state === "failed") return status;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error("Observation did not reach a terminal state");
}

async function waitFor(predicate, message) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(message);
}

async function configureObservation(
  reportResponse,
  urlPatterns = ["https://example.com/*"],
  durationThresholdMs = 0,
) {
  globalThis.fetch = async (url) => {
    if (url.endsWith("/api/meta")) {
      return Response.json({
        url_patterns: urlPatterns,
        observation_threshold_ms: durationThresholdMs,
      });
    }
    if (reportResponse instanceof Error) throw reportResponse;
    return reportResponse;
  };
  await refreshMeta();
}

test("exact observation rules do not match child URLs", async () => {
  await configureObservation(new Response(null, { status: 204 }), ["https://example.com/exact"]);

  startObservation(4, "https://example.com/exact/child");
  assert.equal(getObservationStatus(4, "https://example.com/exact/child").state, "not_matched");

  startObservation(5, "https://example.com/exact");
  const status = await waitForTerminalStatus(5, "https://example.com/exact");
  assert.equal(status.state, "sent");
});

test("marks an observation as sent after a successful report", async () => {
  await configureObservation(new Response(null, { status: 204 }));

  const url = "https://example.com/success";
  startObservation(1, url);

  const status = await waitForTerminalStatus(1, url);
  assert.equal(status.state, "sent");
  assert.equal(status.http_status, 204);
  assert.equal(typeof status.sent_at, "number");
});

test("marks an observation as failed after an unsuccessful report", async () => {
  await configureObservation(new Response(null, { status: 503 }));

  const url = "https://example.com/failure";
  startObservation(2, url);

  const status = await waitForTerminalStatus(2, url);
  assert.equal(status.state, "failed");
  assert.equal(status.http_status, 503);
  assert.equal(status.error, "HTTP 503");
});

test("includes server detail in an unsuccessful observation", async () => {
  await configureObservation(Response.json(
    { detail: "Connector fetch failed for gdrive folder/folder-1" },
    { status: 502 },
  ));

  const url = "https://example.com/detailed-failure";
  startObservation(8, url);

  const status = await waitForTerminalStatus(8, url);
  assert.equal(
    status.error,
    "HTTP 502: Connector fetch failed for gdrive folder/folder-1",
  );
});

test("marks an observation as failed when the report request rejects", async () => {
  await configureObservation(new Error("Connection refused"));

  const url = "https://example.com/network-failure";
  startObservation(3, url);

  const status = await waitForTerminalStatus(3, url);
  assert.equal(status.state, "failed");
  assert.equal(status.http_status, undefined);
  assert.equal(status.error, "Connection refused");
});

test("can surface metadata refresh errors to explicit callers", async () => {
  await configureObservation(new Response(null, { status: 503 }));
  globalThis.fetch = async () => new Response(null, { status: 503 });
  await assert.rejects(
    () => refreshMeta({ throwOnError: true }),
    /Metadata refresh failed: HTTP 503/,
  );
});

test("Gmail metadata enriches an existing observation without requiring a restart", async () => {
  const reports = [];
  globalThis.fetch = async (url, options = {}) => {
    if (url.endsWith("/api/meta")) {
      return Response.json({
        url_patterns: ["https://mail.google.com/*"],
        observation_threshold_ms: 20,
      });
    }
    reports.push(JSON.parse(options.body));
    return new Response(null, { status: 204 });
  };
  await refreshMeta();

  const url = "https://mail.google.com/mail/u/0/#inbox/opaque";
  startObservation(6, url);
  assert.equal(updateMeta(6, { gmail_message_id: "19ff5129584f3514" }), true);
  await waitForTerminalStatus(6, url);

  assert.equal(reports.length, 1);
  assert.equal(reports[0].observed, true);
  assert.match(reports[0].observation_id, /^[0-9a-f-]{36}$/);
  assert.equal(reports[0].observation_duration_ms, 20);
  assert.deepEqual(reports[0].meta, { gmail_message_id: "19ff5129584f3514" });
});

test("reports one observation followed by a duration-only update", async () => {
  const reports = [];
  globalThis.fetch = async (url, options = {}) => {
    if (url.endsWith("/api/meta")) {
      return Response.json({
        url_patterns: ["https://example.com/*"],
        observation_threshold_ms: 20,
      });
    }
    reports.push(JSON.parse(options.body));
    return new Response(null, { status: 204 });
  };
  await refreshMeta();

  const url = "https://example.com/observed";
  startObservation(7, url);
  await waitForTerminalStatus(7, url);
  await new Promise((resolve) => setTimeout(resolve, 10));
  cancelObservation(7);
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(reports.length, 2);
  assert.equal(reports[0].observed, true);
  assert.equal(reports[1].observed, false);
  assert.equal(reports[1].observation_id, reports[0].observation_id);
});

test("defers trailing duration until the initial observation succeeds", async () => {
  const reports = [];
  let completeInitialReport;
  const initialResponse = new Promise((resolve) => {
    completeInitialReport = resolve;
  });
  globalThis.fetch = async (url, options = {}) => {
    if (url.endsWith("/api/meta")) {
      return Response.json({
        url_patterns: ["https://example.com/*"],
        observation_threshold_ms: 5,
      });
    }
    reports.push(JSON.parse(options.body));
    if (reports.length === 1) return initialResponse;
    return new Response(null, { status: 204 });
  };
  await refreshMeta();

  const url = "https://example.com/slow-success";
  startObservation(9, url);
  await waitFor(() => reports.length === 1, "Initial observation was not sent");
  await new Promise((resolve) => setTimeout(resolve, 10));
  cancelObservation(9);
  assert.equal(reports.length, 1);

  completeInitialReport(new Response(null, { status: 204 }));
  await waitFor(() => reports.length === 2, "Trailing duration was not sent after success");
  assert.equal(reports[1].observed, false);
  assert.equal(reports[1].observation_id, reports[0].observation_id);
});

test("discards trailing duration when the initial observation fails", async () => {
  const reports = [];
  let failInitialReport;
  const initialResponse = new Promise((resolve) => {
    failInitialReport = resolve;
  });
  globalThis.fetch = async (url, options = {}) => {
    if (url.endsWith("/api/meta")) {
      return Response.json({
        url_patterns: ["https://example.com/*"],
        observation_threshold_ms: 5,
      });
    }
    reports.push(JSON.parse(options.body));
    return initialResponse;
  };
  await refreshMeta();

  const url = "https://example.com/slow-failure";
  startObservation(10, url);
  await waitFor(() => reports.length === 1, "Initial observation was not sent");
  await new Promise((resolve) => setTimeout(resolve, 10));
  cancelObservation(10);
  failInitialReport(new Response(null, { status: 502 }));
  await new Promise((resolve) => setTimeout(resolve, 10));

  assert.equal(reports.length, 1);
});


test("matches host wildcards across subdomains", () => {
  const pattern = "https://*.atlassian.net/wiki/*";

  assert.equal(
    matchesPattern(
      "https://hello.atlassian.net/wiki/spaces/~71202099c5dd/pages/7650323840/Team+Brain",
      pattern,
    ),
    true,
  );
  assert.equal(matchesPattern("https://atlassian.net/wiki/spaces/ENG", pattern), true);
  assert.equal(matchesPattern("https://hello.atlassian.net/browse/ENG-1", pattern), false);
  assert.equal(matchesPattern("https://hello.atlassian.net.evil.test/wiki/x", pattern), false);
  assert.equal(matchesPattern("http://hello.atlassian.net/wiki/x", pattern), false);
});

test("matches literal host path prefixes", () => {
  assert.equal(
    matchesPattern("https://mail.google.com/mail/u/0/#inbox", "https://mail.google.com/*"),
    true,
  );
  assert.equal(matchesPattern("https://mail.google.com", "https://mail.google.com/*"), true);
  assert.equal(
    matchesPattern("https://docs.google.com/document/d/abc/edit", "https://docs.google.com/document/*"),
    true,
  );
  assert.equal(
    matchesPattern("https://docs.google.com/spreadsheets/d/abc", "https://docs.google.com/document/*"),
    false,
  );
  assert.equal(matchesPattern("https://evil.test/https://mail.google.com/x", "https://mail.google.com/*"), false);
});

test("matches wildcards in the middle of a path and query", () => {
  assert.equal(
    matchesPattern(
      "https://acme.atlassian.net/jira/software/projects/ENG/boards/1?selectedIssue=ENG-2",
      "https://*.atlassian.net/jira/*",
    ),
    true,
  );
  assert.equal(matchesPattern("https://example.com/a/b/c", "https://example.com/a/*/c"), true);
});

test("patterns without wildcards match exactly", () => {
  assert.equal(matchesPattern("https://example.com/page", "https://example.com/page"), true);
  assert.equal(matchesPattern("https://example.com/page/other", "https://example.com/page"), false);
});

test("observation is skipped for a non-matching tenant path", async () => {
  globalThis.fetch = async () =>
    Response.json({
      url_patterns: ["https://*.atlassian.net/wiki/*"],
      observation_threshold_ms: 5,
    });
  await refreshMeta();

  const matched = "https://hello.atlassian.net/wiki/spaces/ENG/pages/1/Plan";
  const unmatched = "https://hello.atlassian.net/browse/ENG-1";
  startObservation(41, matched);
  assert.equal(getObservationStatus(41, matched).matches, true);
  cancelObservation(41);
  startObservation(42, unmatched);
  assert.equal(getObservationStatus(42, unmatched).matches, false);
  cancelObservation(42);
});
