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

test("/projects/<id>/studies/<id2>/upload-antimony resolves to the upload-antimony screen", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/upload-antimony"), {
    screen: "upload-antimony",
    projectId: "abc-123",
    studyId: "xyz-789",
  });
});

test("a trailing slash on an upload-antimony path is tolerated", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/upload-antimony/"), {
    screen: "upload-antimony",
    projectId: "abc-123",
    studyId: "xyz-789",
  });
});

test("/projects/<id>/studies/<id2>/module-sets resolves to the module-sets list screen", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/module-sets"), {
    screen: "module-sets",
    projectId: "abc-123",
    studyId: "xyz-789",
  });
});

test("a trailing slash on a module-sets path is tolerated", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/module-sets/"), {
    screen: "module-sets",
    projectId: "abc-123",
    studyId: "xyz-789",
  });
});

test("/projects/<id>/studies/<id2>/module-set-drafts/<id3> resolves to the draft screen", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/module-set-drafts/draft-1"), {
    screen: "module-set-draft",
    projectId: "abc-123",
    studyId: "xyz-789",
    draftId: "draft-1",
  });
});

test("/projects/<id>/studies/<id2>/module-sets/<id3>/versions/<n> resolves to the version screen", () => {
  assert.deepEqual(
    parseRoute("/projects/abc-123/studies/xyz-789/module-sets/MS-001/versions/2"),
    {
      screen: "module-set-version",
      projectId: "abc-123",
      studyId: "xyz-789",
      moduleSetId: "MS-001",
      version: "2",
    },
  );
});

test("URL-encoded ids in a module-set-version path are all decoded", () => {
  assert.deepEqual(
    parseRoute("/projects/abc%20123/studies/xyz%20789/module-sets/ms%20001/versions/2"),
    {
      screen: "module-set-version",
      projectId: "abc 123",
      studyId: "xyz 789",
      moduleSetId: "ms 001",
      version: "2",
    },
  );
});

test("a nested, unsupported path under a module-set version falls back to the projects screen", () => {
  assert.deepEqual(
    parseRoute("/projects/abc-123/studies/xyz-789/module-sets/MS-001/versions/2/compare"),
    { screen: "projects" },
  );
});

test(
  "/projects/<id>/studies/<id2>/module-sets/<id3>/versions/<n>/members/<id4>/execution " +
    "resolves to the module-set-member-execution screen",
  () => {
    assert.deepEqual(
      parseRoute(
        "/projects/abc-123/studies/xyz-789/module-sets/MS-001/versions/2/members/mem-1/execution",
      ),
      {
        screen: "module-set-member-execution",
        projectId: "abc-123",
        studyId: "xyz-789",
        moduleSetId: "MS-001",
        version: "2",
        memberId: "mem-1",
      },
    );
  },
);

test("a trailing slash on a module-set-member-execution path is tolerated", () => {
  assert.deepEqual(
    parseRoute(
      "/projects/abc-123/studies/xyz-789/module-sets/MS-001/versions/2/members/mem-1/execution/",
    ),
    {
      screen: "module-set-member-execution",
      projectId: "abc-123",
      studyId: "xyz-789",
      moduleSetId: "MS-001",
      version: "2",
      memberId: "mem-1",
    },
  );
});

test("/projects/<id>/studies/<id2>/datasets/time-series resolves to the time-series-datasets screen", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/datasets/time-series"), {
    screen: "time-series-datasets",
    projectId: "abc-123",
    studyId: "xyz-789",
  });
});

test("a trailing slash on a time-series-datasets path is tolerated", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/datasets/time-series/"), {
    screen: "time-series-datasets",
    projectId: "abc-123",
    studyId: "xyz-789",
  });
});

test("/projects/<id>/studies/<id2>/datasets/time-series/<id3> resolves to the time-series-dataset-detail screen", () => {
  assert.deepEqual(
    parseRoute("/projects/abc-123/studies/xyz-789/datasets/time-series/ds-1"),
    {
      screen: "time-series-dataset-detail",
      projectId: "abc-123",
      studyId: "xyz-789",
      datasetId: "ds-1",
    },
  );
});

test("a trailing slash on a time-series-dataset-detail path is tolerated", () => {
  assert.deepEqual(
    parseRoute("/projects/abc-123/studies/xyz-789/datasets/time-series/ds-1/"),
    {
      screen: "time-series-dataset-detail",
      projectId: "abc-123",
      studyId: "xyz-789",
      datasetId: "ds-1",
    },
  );
});

test("URL-encoded ids in a time-series-dataset-detail path are all decoded", () => {
  assert.deepEqual(
    parseRoute("/projects/abc%20123/studies/xyz%20789/datasets/time-series/ds%201"),
    {
      screen: "time-series-dataset-detail",
      projectId: "abc 123",
      studyId: "xyz 789",
      datasetId: "ds 1",
    },
  );
});

test("/projects/<id>/studies/<id2>/datasets/time-series/<id3>/alias-mapping/<id4> resolves to the dataset-model-alias-mapping screen", () => {
  assert.deepEqual(
    parseRoute("/projects/abc-123/studies/xyz-789/datasets/time-series/ds-1/alias-mapping/mod-1"),
    {
      screen: "dataset-model-alias-mapping",
      projectId: "abc-123",
      studyId: "xyz-789",
      datasetId: "ds-1",
      modelId: "mod-1",
    },
  );
});

test("a trailing slash on a dataset-model-alias-mapping path is tolerated", () => {
  assert.deepEqual(
    parseRoute(
      "/projects/abc-123/studies/xyz-789/datasets/time-series/ds-1/alias-mapping/mod-1/",
    ),
    {
      screen: "dataset-model-alias-mapping",
      projectId: "abc-123",
      studyId: "xyz-789",
      datasetId: "ds-1",
      modelId: "mod-1",
    },
  );
});

test("URL-encoded ids in a dataset-model-alias-mapping path are all decoded", () => {
  assert.deepEqual(
    parseRoute(
      "/projects/abc%20123/studies/xyz%20789/datasets/time-series/ds%201/alias-mapping/mod%201",
    ),
    {
      screen: "dataset-model-alias-mapping",
      projectId: "abc 123",
      studyId: "xyz 789",
      datasetId: "ds 1",
      modelId: "mod 1",
    },
  );
});

test("a dataset-model-alias-mapping path never matches the shorter time-series-dataset-detail route", () => {
  const route = parseRoute(
    "/projects/abc-123/studies/xyz-789/datasets/time-series/ds-1/alias-mapping/mod-1",
  );
  assert.notEqual(route.screen, "time-series-dataset-detail");
});

test("/projects/<id>/studies/<id2>/datasets/initial-conditions resolves to the initial-conditions-datasets screen", () => {
  assert.deepEqual(
    parseRoute("/projects/abc-123/studies/xyz-789/datasets/initial-conditions"),
    {
      screen: "initial-conditions-datasets",
      projectId: "abc-123",
      studyId: "xyz-789",
    },
  );
});

test("a trailing slash on an initial-conditions-datasets path is tolerated", () => {
  assert.deepEqual(
    parseRoute("/projects/abc-123/studies/xyz-789/datasets/initial-conditions/"),
    {
      screen: "initial-conditions-datasets",
      projectId: "abc-123",
      studyId: "xyz-789",
    },
  );
});

test("/projects/<id>/studies/<id2>/datasets/initial-conditions/<id3> resolves to the initial-conditions-dataset-detail screen", () => {
  assert.deepEqual(
    parseRoute("/projects/abc-123/studies/xyz-789/datasets/initial-conditions/ds-1"),
    {
      screen: "initial-conditions-dataset-detail",
      projectId: "abc-123",
      studyId: "xyz-789",
      datasetId: "ds-1",
    },
  );
});

test("URL-encoded ids in an initial-conditions-dataset-detail path are all decoded", () => {
  assert.deepEqual(
    parseRoute("/projects/abc%20123/studies/xyz%20789/datasets/initial-conditions/ds%201"),
    {
      screen: "initial-conditions-dataset-detail",
      projectId: "abc 123",
      studyId: "xyz 789",
      datasetId: "ds 1",
    },
  );
});

test("/projects/<id>/studies/<id2>/datasets/initial-conditions/<id3>/alias-mapping/<id4> resolves to the initial-conditions-alias-mapping screen", () => {
  assert.deepEqual(
    parseRoute(
      "/projects/abc-123/studies/xyz-789/datasets/initial-conditions/ds-1/alias-mapping/mod-1",
    ),
    {
      screen: "initial-conditions-alias-mapping",
      projectId: "abc-123",
      studyId: "xyz-789",
      datasetId: "ds-1",
      modelId: "mod-1",
    },
  );
});

test("a trailing slash on an initial-conditions-alias-mapping path is tolerated", () => {
  assert.deepEqual(
    parseRoute(
      "/projects/abc-123/studies/xyz-789/datasets/initial-conditions/ds-1/alias-mapping/mod-1/",
    ),
    {
      screen: "initial-conditions-alias-mapping",
      projectId: "abc-123",
      studyId: "xyz-789",
      datasetId: "ds-1",
      modelId: "mod-1",
    },
  );
});

test("an initial-conditions-alias-mapping path never matches the shorter initial-conditions-dataset-detail route", () => {
  const route = parseRoute(
    "/projects/abc-123/studies/xyz-789/datasets/initial-conditions/ds-1/alias-mapping/mod-1",
  );
  assert.notEqual(route.screen, "initial-conditions-dataset-detail");
});

test("an initial-conditions-datasets path never matches the time-series-datasets route", () => {
  const route = parseRoute("/projects/abc-123/studies/xyz-789/datasets/initial-conditions");
  assert.notEqual(route.screen, "time-series-datasets");
});

test("/projects/<id>/studies/<id>/calibration-jobs resolves to the calibration-jobs screen", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/calibration-jobs"), {
    screen: "calibration-jobs",
    projectId: "abc-123",
    studyId: "xyz-789",
  });
});

test("/projects/<id>/studies/<id>/calibration-jobs/<id> resolves to the calibration-job-detail screen", () => {
  assert.deepEqual(parseRoute("/projects/abc-123/studies/xyz-789/calibration-jobs/job-1"), {
    screen: "calibration-job-detail",
    projectId: "abc-123",
    studyId: "xyz-789",
    jobId: "job-1",
  });
});
