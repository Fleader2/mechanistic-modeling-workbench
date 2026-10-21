# Read-Only "Model Overview" Navigation

Builds directly on `docs/18_modeling_study_increment.md`'s "03 — Modeling Study" increment.
This increment makes Figma's own "05 — Model Overview" screen (node `46:564`, "05 — Curated
fatty acid model," file `4tLH4HX0rdgPxjpNB1aJOW`) real: opening a model from the Study screen's
model table, a model-overview route with strict Project–Study–Model ownership enforcement, and
an honest "Overview"/"History" split of what metadata and version lineage this schema actually,
durably records. No schema changes, no artifact-persistence work, no scientific execution, no
Figma edits.

## Durability audit (done before writing any code, per this increment's own instruction)

Read `app/models/model.py`, `app/models/model_module.py`, `app/models/module_execution_snapshot.py`,
`app/models/run_record.py`, `app/models/model_build_request.py`, and `app/models/modeling_decision.py`
directly, to answer the task's own first question honestly instead of guessing from the Figma mock:

- **`Model`'s own columns are durable and require no run**: `stable_identifier`, `name`,
  `source_type`, `status`, `artifact_reference`, `parent_model_id`, `version_label`, `notes`,
  `created_at`/`updated_at`. These are shown on the "Overview" tab.
- **Version lineage is durable and requires no run**: the `parent_model_id` self-reference between
  `Model` rows. This is the *only* version lineage this schema records -- there is no fine-grained,
  per-parameter change-log table anywhere (no "changed by," "evidence," or "before → after value"
  columns exist; this system has no user/author entity at all), unlike Figma's own much richer
  "History" tab mock (a "Version / event" table with a named author "Morgan Lee," per-parameter
  diffs, and an "Evidence lineage" sentence). The "History" tab shown here is the honest, coarser
  version of that: the `parent_model_id` chain between whole `Model` rows, nothing finer.
- **`artifact_reference` is an opaque pointer, never a scientific artifact to parse or render**:
  per `Model`'s own module docstring, it is "wherever Agent 2's transient output currently lives,"
  an opaque string the Workbench never interprets. Shown here as a plain reference string, exactly
  as the task required -- never fetched, never rendered as content.
- **`ModuleExecutionSnapshot`/`RunRecord` require an actual run to exist, and were never used
  here**: both are keyed to a specific execution (`run_record_id`), and `ModuleExecutionSnapshot`'s
  own `snapshot_payload` is explicitly opaque, decoded nowhere except one documented persistence
  function this increment never calls. No "whole model content" is ever inferred from them, per
  the task's own explicit instruction.
- **`ModelModule` rows ARE durably persisted without requiring a run** (materialized once a
  hierarchy search accepts a module, per `docs/07_executable_module_materialization.md`) --
  the one genuinely available "scientific artifact" this audit found that this increment does
  *not* surface. Deferred deliberately (see "Remaining limitations"): showing it meaningfully
  (depth, `execution_status`, partial-materialization semantics) is its own scope decision this
  increment's own bullets never asked for, unlike `Model`'s own columns and its lineage.
- **`ModelBuildRequest`/`ModelingDecision`**: the former is what the user *wants* built, never the
  built model itself (see its own module docstring); the latter has no author/timestamp-of-change
  granularity either and is a reconciliation workflow, not a version-change log. Neither backs
  anything Figma's "Model Overview"/"History" tabs show.

Conclusion acted on: the "Overview" tab shows `Model`'s own real columns; the "History" tab shows
the `parent_model_id` chain; every other Figma tab (Compartments/Species/Reactions/Parameters/
Antimony/Modules) is deferred -- disabled, never silently dropped -- because none has complete,
correctly-scoped, durably-available content for this screen.

## Backend: persistence layer

Two small, additive, read-only functions in `app/persistence/model.py`, following
`get_subproject_for_project`'s own established ownership-check convention:

- `get_model_for_subproject(session, subproject_id, model_id) -> Model | None` -- a model id that
  exists but belongs to a *different* subproject returns `None`, identically to one that does not
  exist at all.
- `list_child_models(session, parent_model_id) -> list[Model]` -- every `Model` whose
  `parent_model_id` is this one, ordered by name, **regardless of which subproject each child
  belongs to** (the raw, unscoped fact -- `parent_model_id` has no schema-level constraint tying a
  child to its parent's own study). Scoping that safely is deliberately the API layer's job, not
  this function's; see below.

Covered by dedicated persistence tests: found-for-its-own-subproject, `None` for an unknown id,
`None` for the ownership-mismatch case; and, for `list_child_models`, empty, and -- explicitly --
that it *does* return a cross-subproject child (the raw truth), with a comment pointing at where
the scoping actually happens.

## Backend: HTTP API

Two new nested routes in the existing `app/api/v1/routes/projects.py`:

- `GET /api/v1/projects/{project_id}/subprojects/{subproject_id}/models/{model_id}` ->
  `ModelDetail` -- every real column. A 404 for an unknown project, an unknown study, an unknown
  model, *or* a model that belongs to a different study (or a study belonging to a different
  project) -- all indistinguishable to the caller, enforced via a new `_require_model` helper
  mirroring `_require_modeling_study`'s own pattern.
- `GET /api/v1/projects/{project_id}/subprojects/{subproject_id}/models/{model_id}/lineage` ->
  `ModelLineage` -- `{parent, parent_out_of_scope, children, children_out_of_scope_count}`. The
  scoping decision lives here, not in persistence: a parent/child is only ever included in
  `parent`/`children` when it belongs to the *same* `subproject_id` as the model being viewed; one
  that exists but belongs to a different study is disclosed via the two `*_out_of_scope` fields
  instead of being silently dropped (which would misrepresent "no earlier version recorded" when
  one exists) or exposed cross-study (an ownership leak through this study's own URL).

`app/schemas/model.py` gained `ModelDetail` (every real `Model` column, following
`SubprojectDetail`'s own precedent) and `ModelLineage`. Neither invents Figma's "Scope" /
"Structure" / "Parameters" summary counts, its "Construction: ... Calibration: ... Validation:
..." sentence, or its rich per-change "History" fields -- see the durability audit above.
Verified by a dedicated test assertion (`test_get_one_model` asserts `"scope"`/`"structure"` are
absent from the response body).

Test coverage: `tests/api/test_model_detail.py` (success; 404 for an unknown project, study, or
model; 404 for a model belonging to a different study *or* a different project, asserted not to
leak it; 422 for a malformed id) and `tests/api/test_model_lineage.py` (empty; parent+children
within the same study; a parent that exists but is out-of-scope, discloses `parent_out_of_scope`
and never names it; a child that exists but is out-of-scope, discloses the count and never names
it; the same 404/422 cases).

## Frontend

- `frontend/src/lib/router.ts`: extended with a fourth route,
  `{ screen: "model-detail"; projectId; studyId; modelId }`, matched by a new
  `/^\/projects\/([^/]+)\/studies\/([^/]+)\/models\/([^/]+)\/?$/` pattern checked before the
  study-detail pattern. Four new tests cover it (basic match, trailing slash, URL-encoded ids, a
  nested unsupported path under a model falling back correctly); the prior increment's own
  "unsupported path" example (`.../studies/xyz-789/models`, no trailing model id) still correctly
  falls back, unaffected.
- `frontend/src/components/ModelsTable.tsx`: "Model" is now a real, accessible `RouterLink` (plus
  a row `onDoubleClick`) to `/projects/{projectId}/studies/{studyId}/models/{modelId}`, mirroring
  `ProjectsTable`/`ModelingStudiesTable`'s own identical pattern -- this is the increment that
  reverses the *previous* increment's deliberate "plain text, not a link" choice, now that opening
  a model is genuinely in scope.
- `frontend/src/components/ModelTabs.tsx` (new): "Model context tabs" (Figma node `46:593`).
  "Overview" and "History" are real, clickable tabs (plain component state, not sub-routes -- both
  live at the identical URL); the other six (Compartments/Species/Reactions/Parameters/Antimony/
  Modules) render disabled (`aria-disabled="true"`, `title="Not available in this increment"`),
  matching the "disable honestly, never fake" precedent every prior increment already established.
- `frontend/src/components/ModelInformationCard.tsx` (new): the "Overview" tab's own card, named
  "Model information" (not Figma's own "Model overview," to avoid confusing it with the *tab*
  it lives under). Shows `source_type`, `status`, `artifact_reference`, `notes` -- the real
  columns -- and nothing else; see "Honest-disclosure deviations" below for what it omits and why.
  "Validate model" / "Export Antimony" / "Save new version" are scientific-execution/export/
  editing actions, all disabled.
- `frontend/src/components/ModelLineageCard.tsx` (new): the "History" tab's own honest content --
  "Earlier version" / "Later versions," each either a real link (`RouterLink` to that model's own
  overview, within this same study) or an explicit disclosure sentence ("An earlier version exists
  outside this Modeling Study (not shown)." / "N later version(s) exist outside this Modeling
  Study (not shown)." / "No earlier version recorded." / "No later versions recorded.") -- never a
  silently-empty section when a parent/child genuinely exists elsewhere, and never a cross-study
  link.
- `frontend/src/components/ModelOverviewScreen.tsx` (new): the main screen. Fetches project, then
  study (scoped to that project), then model (scoped to that study), then -- only on the model's
  own success -- its lineage, mirroring `StudyDetailScreen`'s own chain-fetch pattern exactly.
  Reuses the identical `createStaleGuard` pattern, keyed by the combined
  `projectId`/`studyId`/`modelId` triple.
- `frontend/src/components/Sidebar.tsx`: extended for the `model-detail` route. Shows "Current
  Project" (a link back) and the "Current study" label exactly as the study-detail route does, but
  **"Study overview" becomes a real link back, not an active item** (unlike on the study-detail
  route itself) -- see the deliberate deviation from Figma's own prototype choice below. The same
  four disabled items (`All models`/`All datasets`/`All modules`/`Runs & Results`) remain.
- `App.tsx`: added the `model-detail` route branch and wired the same lifted `onProjectChange`/
  `onStudyChange` callbacks `StudyDetailScreen` already uses, so the sidebar shows the right
  project/study context without `ModelOverviewScreen` needing to know anything about the sidebar.
- `frontend/src/format.ts`: added `formatModelSourceType` (`GENERATED`→"Generated" etc.),
  matching the existing `formatModelStatus`/`formatTaskType`/`formatWorkflowStatus` precedent.

### Honest-disclosure deviations from Figma (intentional, documented)

- **No "Scope" / "Structure" / "Parameters" summary, no "Construction: ... Calibration: ...
  Validation: ..." sentence.** Figma's own "Model overview" card shows these (e.g. "2 compartments
  · 18 species · 12 reactions," "Construction: Protein abundance v1 + literature kinetics..."):
  none of that content -- species, reactions, parameters, construction method, calibration/
  validation claims -- is ever persisted for a `Model` anywhere in this schema (the durability
  audit above). Inventing it would violate the task's own explicit "do not invent scientific
  readiness" instruction directly, so it is omitted entirely, not replaced with a "Not captured"
  placeholder (there is no fixed field slot to even label honestly here, unlike the Study/Project
  screens' fixed field sets).
- **`status` is explicitly captioned as a recorded lifecycle status, not a scientific-readiness
  verdict.** Figma's own "Ready"/"Draft" labels (in its "Models" table, shown as e.g. "v1.3 ·
  Ready") blur exactly the distinction the task asked this increment to keep clear. The field is
  labeled "Status (recorded)" with a one-line caption underneath, directly satisfying "distinguish
  recorded status from scientific readiness."
- **No "Values needing review" parameter table, no per-change "History" audit log.** Neither has
  any backing table (no parameter/evidence/review schema, no user/author entity, no fine-grained
  change-event table) -- see the durability audit. Omitted entirely.
- **No fabricated page-subtitle identifier/editing-session claim.** Figma's subtitle reads
  "MOD-001 · v1.3 · Microbial Metabolism · All changes saved" -- "All changes saved" implies a
  live editing session this read-only screen has no concept of. The real subtitle shown is
  "{stable_identifier} · {version_label or Not captured} · {status}" -- three real facts, nothing
  invented, and no repeated project-level context (already shown in the sidebar).
- **Sidebar: "Study overview" is a real link back on a model's own page, not an active item; no
  item is marked "active" at all on this route.** Figma's own prototype instead highlights "All
  models" as the active section for a model page -- a deliberate deviation here. That choice
  presumes the "All models" list screen genuinely exists as a navigational step between the study
  and the model, which this increment does not build; marking a disabled, unbuilt destination
  "active" would be confusing, not helpful, and there is no honest substitute to highlight in its
  place.

### States

- **Loading**: three independent messages across the fetch chain -- "Loading project…", "Loading
  Modeling Study…", "Loading model…" -- verified live via route-delayed responses on each request.
- **Error**: a structured API failure on the model-metadata fetch renders the real error message
  -- verified live via a mocked 500.
- **Unknown-model**: a 404 renders "This model could not be found." with a back link to the
  *owning study* (`/projects/{projectId}/studies/{studyId}`), preserving study context -- verified
  live against a real, non-existent UUID.
- **Unknown-project/unknown-study**: identical to prior increments' own handling, verified live.
- **Ownership mismatch**: a real model (seeded as a child of the model being viewed, but belonging
  to a *different* Modeling Study -- "Carbon allocation"), requested through the *other* study's
  own URL. Renders the identical "This model could not be found." message, verified live never to
  show the other study's model (asserted both on the API response body and live in the browser).
- **Lineage out-of-scope disclosure**: verified live on two axes -- a parent in a different study
  (`parent_out_of_scope`, never named) and a child in a different study
  (`children_out_of_scope_count`, never named, with the in-scope child still shown correctly).
- **No lineage recorded**: a model with neither parent nor children renders "No earlier version
  recorded." / "No later versions recorded." honestly, verified live.
- **Direct link, refresh, back/forward navigation**: verified live exactly as in prior increments.
- **Stale-response protection**: verified live by navigating to a slow-responding model and then
  immediately to a second, faster-responding model -- the final rendered page correctly showed the
  second model, never a flash of the first's stale data.

## Testing

- `tests/persistence/test_model.py`: five new tests for `get_model_for_subproject`/
  `list_child_models` (see "Backend: persistence layer" above).
- `tests/persistence/conftest.py`: added `make_model_id`, following `make_project_id`/
  `make_subproject_id`'s own established helper pattern (needed repeatedly across the new tests).
- `tests/api/test_model_detail.py` / `test_model_lineage.py` (new, 13 tests total): see "Backend:
  HTTP API" above.
- `frontend/src/lib/router.test.ts`: four new tests for the model-detail route pattern.
- Full backend suite: **392 passed** (373 prior + 19 new), `ruff check`/`ruff format --check`
  clean. Commands run (from the repository root, `.venv` active): `python -m pytest -q`,
  `ruff check .`, `ruff format --check .`.
- Frontend (from `frontend/`): `npm run typecheck` (clean), `npm run build` (clean; 51 modules
  transformed, up from 47 before this increment), `npm run test` (19/19 passing: 4 new router
  tests + the 11 router/staleGuard tests already established, unaffected).

## Live browser verification

Node, the backend (`uvicorn`, port 8000), and the frontend (`vite dev`, port 5173) were brought up
exactly as in prior increments' own sessions, reusing the same isolated, never-committed
`verify-tools/` scratch Playwright project.

A one-off scratch seed script (`seed_model_overview_verification.py`) seeded, inside one Modeling
Study ("ACC1 perturbation"): a four-model lineage chain (`MOD-000` draft → `MOD-001` "Curated
fatty acid model," the model opened → `MOD-002` a later revision), one isolated model with no
lineage, no version label, no artifact reference, and no notes (`MOD-003`), and -- in a
*different* Modeling Study of the same project ("Carbon allocation") -- a model whose own parent
is `MOD-001` (`MOD-900`), for the cross-study lineage-disclosure and ownership-mismatch checks.

**Database-identity correction (added by `docs/22_database_configuration_and_verification
_safety.md`).** This section originally claimed `uvicorn` ran with `APP_ENV=test`, implying it
was pointed at a disposable database. It was not: `APP_ENV=test` has no effect on which database
the application connects to, so this session actually ran against the real development database.
This screen's own navigation flow was re-verified against the actual test database
(`workbench_test`, confirmed disposable by `scripts/db_safety.py::require_disposable_database`
before seeding) and renders identically -- heading, subtitle, both lineage entries (earlier and
later version, each with the correct "Not captured" fields), and the cross-study
lineage-disclosure note all reproduced exactly. Only the database-identity claim was wrong.

A throwaway Playwright script (`verify_model_overview.mjs`) drove a real Chromium browser against
the real running servers. One script-ordering mistake was caught and fixed during this session
(checking the "Overview" tab's "Not captured" field count *after* already switching to the
"History" tab, so the Overview card had unmounted -- not an application bug; re-ordering the
check in the script confirmed the real count of 2). Every result below is the corrected script's
actual printed output or a screenshot it captured:

| Check | Observed result |
|---|---|
| Open a model via the accessible link | URL became `.../models/<uuid>`; heading "Curated fatty acid model" |
| Breadcrumb | "Projects / Yeast Fatty Acid Engineering / ACC1 perturbation / Curated fatty acid model" |
| Subtitle | "MOD-001 · v1.3 · Active" |
| Model information: source type / status | "Generated" / "Active," with the recorded-vs-readiness caption present |
| Artifact reference shown | the raw opaque string, verbatim |
| Action buttons disabled | Validate model / Export Antimony / Save new version: all `true` |
| Tabs | 6 disabled (`Compartments, Species, Reactions, Parameters, Antimony, Modules`); default active tab "Overview" |
| History tab click | active tab became "History"; both the parent ("Reduced pathway model") and child ("Updated fatty acid model") shown as real links |
| Clicking the parent link | navigated to the draft model's own overview; heading "Reduced pathway model" |
| Isolated model (no lineage) | Overview: 2 "Not captured" fields (artifact reference, notes); History: 2 "no ... recorded" lines |
| Cross-study child disclosure | the other study's model name never appeared anywhere on the page; "1 later version ... exists outside this Modeling Study (not shown)" shown instead |
| **Ownership mismatch** | opening the cross-study model through ACC1 perturbation's own study URL rendered "This model could not be found."; the other study's heading never appeared; back-link preserved study context (`/projects/<uuid>/studies/<uuid>`) |
| Unknown-model state | "This model could not be found." (against a real, non-existent UUID) |
| Direct link + refresh | both loaded "Updated fatty acid model" correctly |
| Sidebar active items | `[]` -- no item faked as active, per the deliberate deviation above |
| Sidebar "Study overview" | a real link, `href="/projects/<uuid>/studies/<uuid>"` |
| Sidebar "Current study" | "ACC1 perturbation" |
| Back navigation | returned to the Study screen; its Models table confirmed visible |
| Forward navigation | returned to the same model's detail URL |
| Loading state | "Loading model…" (via a route-delayed response) |
| Error state | "Couldn't load this model: Simulated failure for verification." (mocked 500) |
| Rapid navigation (stale-response protection) | navigated to the curated model (1s-delayed response) then immediately to the isolated model; final heading correctly "Expert Antimony reference," never stale curated-model data |
| Console/page errors | 6 console messages, all `Failed to load resource` lines directly caused by the intentionally-triggered 404/500 responses above; 0 uncaught page errors |

Eight screenshots were captured and reviewed directly; all render as expected with no visual
breakage. One screenshot (the sidebar check) was initially misread by eye as showing "History"
active instead of "Overview" -- re-verified twice with two independent, isolated Playwright checks
(`.model-tab.active` text content) immediately after, both confirming "Overview" is correctly the
only active tab on a fresh load; the original misreading was a visual artifact of the two tabs'
similar (both non-grey) text color at that screenshot's resolution, not a real bug.

**Layout vs. Figma (node `46:564`).** Compared directly against `get_design_context`'s/
`get_screenshot`'s own rendered reference for this node: application header, sidebar nav
(including the "CURRENT STUDY" block), breadcrumb, page heading, the tab row's structure and
order, and the "Model information" card's layout (heading, then fields, then action buttons) all
match structurally. The deliberate deviations are listed above. This remains a by-eye structural
comparison, not a pixel-diff.

## Remaining limitations

- `ModelModule` rows are durably persisted per-model without requiring a run (see the durability
  audit), but are not surfaced anywhere in this increment -- a reasonable candidate for a future
  "Modules" tab, deliberately deferred rather than built half-scoped.
- The six other Figma tabs (Compartments/Species/Reactions/Parameters/Antimony/Modules) and the
  standalone "All models"/"All datasets"/"All modules"/"Runs & Results" nav destinations remain
  entirely unbuilt -- all visibly disabled, never silently dropped.
- `ModelOverviewScreen` re-fetches the owning project and study on every `modelId` change, even
  when navigating between two models within the same study -- a known, minor inefficiency (not a
  correctness bug), consistent with the identical, already-documented tradeoff in
  `docs/18_modeling_study_increment.md`.
- As in prior increments: the pre-existing `npm audit` vulnerabilities in `frontend/`'s
  dependencies remain unaddressed (out of scope; not introduced or worsened here).
- "Layout matches Figma" is still a by-eye structural comparison against one rendered reference,
  not a pixel-diff.
- The live-verification script and its seed script are throwaway scratch tools, not part of the
  repository and not a regression test that runs on future changes -- only `router.test.ts`, the
  persistence tests, and the API tests are.
- `ModelOverviewScreen` does not retry automatically on error; recovering from a failed load
  requires a manual navigation (back then forward, or a refresh). Not requested by this
  increment's scope, so not added.
