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

const { getObservationStatus, refreshMeta, startDwell } = await import("../dist/lib/dwell.js");

async function waitForTerminalStatus(tabId, url) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const status = getObservationStatus(tabId, url);
    if (status.state === "sent" || status.state === "failed") return status;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error("Observation did not reach a terminal state");
}

async function configureDwell(reportResponse, urlPatterns = ["https://example.com/*"]) {
  globalThis.fetch = async (url) => {
    if (url.endsWith("/api/cli/meta")) {
      return Response.json({
        url_patterns: urlPatterns,
        dwell_threshold_ms: 0,
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
