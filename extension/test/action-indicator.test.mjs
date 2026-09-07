import assert from "node:assert/strict";
import test from "node:test";

const { getActionIndicator } = await import("../dist/lib/action-indicator.js");

test("maps active observation states to distinct toolbar indicators", () => {
  assert.deepEqual(getActionIndicator("waiting"), {
    color: "#2563eb",
    title: "AgentGraph: observing page",
  });
  assert.deepEqual(getActionIndicator("sending"), {
    color: "#f59e0b",
    title: "AgentGraph: sending observation",
  });
  assert.deepEqual(getActionIndicator("sent"), {
    color: "#16a34a",
    title: "AgentGraph: observation sent",
  });
});

test("uses the normal toolbar icon for inactive observation states", () => {
  for (const state of ["not_matched", "failed", "canceled"]) {
    assert.equal(getActionIndicator(state), null);
  }
});
