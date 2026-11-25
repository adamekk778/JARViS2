// 3.20 Přístupnost+: one-switch control steps around (474) and the day / evening theme (479).
import assert from "node:assert/strict";
import { test } from "node:test";
import { isDay, nextIndex } from "../../src/shared/access.ts";

test("the scan goes around the buttons", () => {
  assert.equal(nextIndex(-1, 3), 0);
  assert.equal(nextIndex(2, 3), 0);
  assert.equal(nextIndex(0, 0), -1);
});

test("light by day, dark in the evening", () => {
  assert.equal(isDay(new Date(2026, 10, 25, 12, 0)), true);
  assert.equal(isDay(new Date(2026, 10, 25, 20, 30)), false);
  assert.equal(isDay(new Date(2026, 10, 25, 6, 59)), false);
  assert.equal(isDay(new Date(2026, 10, 25, 16, 30), 7.5, 16.25), false);
});
