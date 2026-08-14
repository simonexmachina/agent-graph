import assert from "node:assert/strict";
import test from "node:test";

const { refreshPendingObservation } = await import("../dist/lib/observation-status.js");

function status(state) {
  return {
    url: "https://mail.google.com/mail/u/0/#inbox/thread-id",
    matches: true,
    state,
    threshold_ms: 3000,
  };
}

test("refreshes a waiting observation to its latest background state", async () => {
  const sent = { ...status("sent"), http_status: 202, sent_at: Date.now() };
  const refreshed = await refreshPendingObservation(status("waiting"), async () => sent);

  assert.equal(refreshed, sent);
});

test("continues refreshing while an observation is sending", async () => {
  const failed = { ...status("failed"), error: "HTTP 503" };
  const refreshed = await refreshPendingObservation(status("sending"), async () => failed);

  assert.equal(refreshed, failed);
});

test("does not refresh a terminal observation", async () => {
  const sent = status("sent");
  let loads = 0;
  const refreshed = await refreshPendingObservation(sent, async () => {
    loads += 1;
    return status("waiting");
  });

  assert.equal(refreshed, sent);
  assert.equal(loads, 0);
});
