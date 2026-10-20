import test from "node:test";
import assert from "node:assert/strict";
import { createStaleGuard } from "./staleGuard.ts";

test("isCurrent is false before any request has started", () => {
  const guard = createStaleGuard<string>();
  assert.equal(guard.isCurrent("a"), false);
});

test("isCurrent is true for the key that was just started", () => {
  const guard = createStaleGuard<string>();
  guard.start("a");
  assert.equal(guard.isCurrent("a"), true);
});

test("a later start makes the earlier key stale, even if its response resolves later", () => {
  const guard = createStaleGuard<string>();
  guard.start("row-a");
  guard.start("row-b"); // simulates a rapid second row click before row-a's response arrives
  assert.equal(guard.isCurrent("row-a"), false, "row-a's now-stale response must be ignored");
  assert.equal(guard.isCurrent("row-b"), true, "row-b is the current selection");
});

test("restarting the same key keeps it current", () => {
  const guard = createStaleGuard<string>();
  guard.start("a");
  guard.start("a");
  assert.equal(guard.isCurrent("a"), true);
});
