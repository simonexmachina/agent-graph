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
  cancelDwell,
  getObservationStatus,
  refreshMeta,
  startDwell,
  updateMeta,
} = await import("../dist/lib/dwell.js");

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

async function configureDwell(
  reportResponse,
  urlPatterns = ["https://example.com/*"],
  dwellThresholdMs = 0,
) {
  globalThis.fetch = async (url) => {
    if (url.endsWith("/api/cli/meta")) {
      return Response.json({
        url_patterns: urlPatterns,
        dwell_threshold_ms: dwellThresholdMs,
      });
    }
    if (reportResponse instanceof Error) throw reportResponse;
    return reportResponse;
  };
  await refreshMeta();
}

test("exact observation rules do not match child URLs", async () => {
  await configureDwell(new Response(null, { status: 204 }), ["https://example.com/exact"]);

  startDwell(4, "https://example.com/exact/child");
  assert.equal(getObservationStatus(4, "https://example.com/exact/child").state, "not_matched");

  startDwell(5, "https://example.com/exact");
  const status = await waitForTerminalStatus(5, "https://example.com/exact");
  assert.equal(status.state, "sent");
});

test("marks an observation as sent after a successful report", async () => {
  await configureDwell(new Response(null, { status: 204 }));

  const url = "https://example.com/success";
  startDwell(1, url);

  const status = await waitForTerminalStatus(1, url);
  assert.equal(status.state, "sent");
  assert.equal(status.http_status, 204);
  assert.equal(typeof status.sent_at, "number");
});

test("marks an observation as failed after an unsuccessful report", async () => {
  await configureDwell(new Response(null, { status: 503 }));

  const url = "https://example.com/failure";
  startDwell(2, url);

  const status = await waitForTerminalStatus(2, url);
  assert.equal(status.state, "failed");
  assert.equal(status.http_status, 503);
  assert.equal(status.error, "HTTP 503");
});

test("includes server detail in an unsuccessful observation", async () => {
  await configureDwell(Response.json(
    { detail: "Connector fetch failed for gdrive folder/folder-1" },
    { status: 502 },
  ));

  const url = "https://example.com/detailed-failure";
  startDwell(8, url);

  const status = await waitForTerminalStatus(8, url);
  assert.equal(
    status.error,
    "HTTP 502: Connector fetch failed for gdrive folder/folder-1",
  );
});

test("marks an observation as failed when the report request rejects", async () => {
  await configureDwell(new Error("Connection refused"));

  const url = "https://example.com/network-failure";
  startDwell(3, url);

  const status = await waitForTerminalStatus(3, url);
  assert.equal(status.state, "failed");
  assert.equal(status.http_status, undefined);
  assert.equal(status.error, "Connection refused");
});

test("can surface metadata refresh errors to explicit callers", async () => {
  await configureDwell(new Response(null, { status: 503 }));
  globalThis.fetch = async () => new Response(null, { status: 503 });
  await assert.rejects(
    () => refreshMeta({ throwOnError: true }),
    /Metadata refresh failed: HTTP 503/,
  );
});

test("Gmail metadata enriches an existing observation without requiring a restart", async () => {
  const reports = [];
  globalThis.fetch = async (url, options = {}) => {
    if (url.endsWith("/api/cli/meta")) {
      return Response.json({
        url_patterns: ["https://mail.google.com/*"],
        dwell_threshold_ms: 20,
      });
    }
    reports.push(JSON.parse(options.body));
    return new Response(null, { status: 204 });
  };
  await refreshMeta();

  const url = "https://mail.google.com/mail/u/0/#inbox/opaque";
  startDwell(6, url);
  assert.equal(updateMeta(6, { gmail_message_id: "19ff5129584f3514" }), true);
  await waitForTerminalStatus(6, url);

  assert.equal(reports.length, 1);
  assert.equal(reports[0].observed, true);
  assert.match(reports[0].observation_id, /^[0-9a-f-]{36}$/);
  assert.deepEqual(reports[0].meta, { gmail_message_id: "19ff5129584f3514" });
});

test("reports one observation followed by a dwell-only update", async () => {
  const reports = [];
  globalThis.fetch = async (url, options = {}) => {
    if (url.endsWith("/api/cli/meta")) {
      return Response.json({
        url_patterns: ["https://example.com/*"],
        dwell_threshold_ms: 20,
      });
    }
    reports.push(JSON.parse(options.body));
    return new Response(null, { status: 204 });
  };
  await refreshMeta();

  const url = "https://example.com/observed";
  startDwell(7, url);
  await waitForTerminalStatus(7, url);
  await new Promise((resolve) => setTimeout(resolve, 10));
  cancelDwell(7);
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(reports.length, 2);
  assert.equal(reports[0].observed, true);
  assert.equal(reports[1].observed, false);
  assert.equal(reports[1].observation_id, reports[0].observation_id);
});

test("defers trailing dwell until the initial observation succeeds", async () => {
  const reports = [];
  let completeInitialReport;
  const initialResponse = new Promise((resolve) => {
    completeInitialReport = resolve;
  });
  globalThis.fetch = async (url, options = {}) => {
    if (url.endsWith("/api/cli/meta")) {
      return Response.json({
        url_patterns: ["https://example.com/*"],
        dwell_threshold_ms: 5,
      });
    }
    reports.push(JSON.parse(options.body));
    if (reports.length === 1) return initialResponse;
    return new Response(null, { status: 204 });
  };
  await refreshMeta();

  const url = "https://example.com/slow-success";
  startDwell(9, url);
  await waitFor(() => reports.length === 1, "Initial observation was not sent");
  await new Promise((resolve) => setTimeout(resolve, 10));
  cancelDwell(9);
  assert.equal(reports.length, 1);

  completeInitialReport(new Response(null, { status: 204 }));
  await waitFor(() => reports.length === 2, "Trailing dwell was not sent after success");
  assert.equal(reports[1].observed, false);
  assert.equal(reports[1].observation_id, reports[0].observation_id);
});

test("discards trailing dwell when the initial observation fails", async () => {
  const reports = [];
  let failInitialReport;
  const initialResponse = new Promise((resolve) => {
    failInitialReport = resolve;
  });
  globalThis.fetch = async (url, options = {}) => {
    if (url.endsWith("/api/cli/meta")) {
      return Response.json({
        url_patterns: ["https://example.com/*"],
        dwell_threshold_ms: 5,
      });
    }
    reports.push(JSON.parse(options.body));
    return initialResponse;
  };
  await refreshMeta();

  const url = "https://example.com/slow-failure";
  startDwell(10, url);
  await waitFor(() => reports.length === 1, "Initial observation was not sent");
  await new Promise((resolve) => setTimeout(resolve, 10));
  cancelDwell(10);
  failInitialReport(new Response(null, { status: 502 }));
  await new Promise((resolve) => setTimeout(resolve, 10));

  assert.equal(reports.length, 1);
});
