import assert from "node:assert/strict";
import test from "node:test";

const { BOOKMARK_INDICATOR_COLOR, getActionIndicator, getActionTitle } = await import("../dist/lib/action-indicator.js");

test("uses a black bookmark stripe in the toolbar icon", () => {
  assert.equal(BOOKMARK_INDICATOR_COLOR, "#000000");
});

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

test("includes bookmark state in the action tooltip", () => {
  assert.equal(getActionTitle("not_matched", true), "AgentGraph: bookmarked page");
  assert.equal(
    getActionTitle("sending", true),
    "AgentGraph: sending observation; bookmarked page",
  );
});
