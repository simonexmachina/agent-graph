import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_SERVER_BASE_URL,
  getFetchUrl,
  getHealthUrl,
  getMetaUrl,
  normalizeServerBaseUrl,
} from "../dist/lib/config.js";

test("normalizeServerBaseUrl accepts localhost and strips trailing slash", () => {
  assert.equal(normalizeServerBaseUrl("http://localhost:9999/"), "http://localhost:9999");
  assert.equal(normalizeServerBaseUrl("http://127.0.0.1:8765"), "http://127.0.0.1:8765");
});

test("normalizeServerBaseUrl rejects unsupported hosts and malformed URLs", () => {
  assert.throws(() => normalizeServerBaseUrl("not a url"), /full URL/);
  assert.throws(() => normalizeServerBaseUrl("https://localhost:8765"), /Only http/);
  assert.throws(() => normalizeServerBaseUrl("http://192.168.1.10:8765"), /localhost or 127.0.0.1/);
  assert.throws(() => normalizeServerBaseUrl("http://localhost"), /explicit port/);
  assert.throws(() => normalizeServerBaseUrl("http://localhost:8765/api"), /must not include a path/);
});

test("derived endpoints are built from the configured base URL", () => {
  assert.equal(DEFAULT_SERVER_BASE_URL, "http://localhost:8765");
  assert.equal(getHealthUrl(DEFAULT_SERVER_BASE_URL), "http://localhost:8765/health");
  assert.equal(getMetaUrl(DEFAULT_SERVER_BASE_URL), "http://localhost:8765/api/cli/meta");
  assert.equal(getFetchUrl(DEFAULT_SERVER_BASE_URL), "http://localhost:8765/fetch-url");
});
