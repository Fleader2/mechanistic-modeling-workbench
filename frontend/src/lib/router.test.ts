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
  assert.deepEqual(parseRoute("/projects/abc-123/unknown-sub-route"), { screen: "projects" });
});

test("/projects/<id>/studies/<id2> resolves to the study-detail screen with both ids", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789"), {
    screen: "study-detail",
    projectId: "abc-123",
    studyId: "xyz-789",
  });
});

test("a trailing slash on a study-detail path is tolerated", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/"), {
    screen: "study-detail",
    projectId: "abc-123",
    studyId: "xyz-789",
  });
});

test("URL-encoded ids in a study-detail path are both decoded", () => {
  assert.deepEqual(parseRoute("/projects/abc%20123/studies/xyz%20789"), {
    screen: "study-detail",
    projectId: "abc 123",
    studyId: "xyz 789",
  });
});

test("a nested, unsupported path under a study falls back to the projects screen", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/models"), {
    screen: "projects",
  });
});

test("/projects/<id>/studies/<id2>/models/<id3> resolves to the model-detail screen with all three ids", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/models/mod-001"), {
    screen: "model-detail",
    projectId: "abc-123",
    studyId: "xyz-789",
    modelId: "mod-001",
  });
});

test("a trailing slash on a model-detail path is tolerated", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/models/mod-001/"), {
    screen: "model-detail",
    projectId: "abc-123",
    studyId: "xyz-789",
    modelId: "mod-001",
  });
});

test("URL-encoded ids in a model-detail path are all decoded", () => {
  assert.deepEqual(parseRoute("/projects/abc%20123/studies/xyz%20789/models/mod%20001"), {
    screen: "model-detail",
    projectId: "abc 123",
    studyId: "xyz 789",
    modelId: "mod 001",
  });
});

test("a nested, unsupported path under a model falls back to the projects screen", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/models/mod-001/history"), {
    screen: "projects",
  });
});
