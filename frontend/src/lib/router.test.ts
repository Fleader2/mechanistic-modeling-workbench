import { test } from "node:test";
import assert from "node:assert/strict";
import { parseRoute } from "./router.ts";

test("root path resolves to the projects screen", () => {
  assert.deepEqual(parseRoute("/"), { screen: "projects" });
});

test("the bare /projects path resolves to the projects screen", () => {
  assert.deepEqual(parseRoute("/projects"), { screen: "projects" });
});

test("/projects/<id> resolves to the project-detail screen with that id", () => {
  assert.deepEqual(parseRoute("/projects/abc-123"), {
    screen: "project-detail",
    projectId: "abc-123",
  });
});

test("a trailing slash on a project-detail path is tolerated", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/"), {
    screen: "project-detail",
    projectId: "abc-123",
  });
});

test("a URL-encoded id is decoded", () => {
  assert.deepEqual(parseRoute("/projects/abc%20123"), {
    screen: "project-detail",
    projectId: "abc 123",
  });
});

test("an unrecognized path falls back to the projects screen", () => {
  assert.deepEqual(parseRoute("/not-a-real-route"), { screen: "projects" });
});

test("a nested, unsupported path under /projects falls back to the projects screen", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz"), { screen: "projects" });
});
