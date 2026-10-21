# Read-Only "Modeling Study" Navigation

Builds directly on `docs/17_current_project_increment.md`'s "02 — Current Project" increment.
This increment makes Figma's own "03 — Modeling Study" screen (node `46:314`, "03 — ACC1
perturbation," file `4tLH4HX0rdgPxjpNB1aJOW`) real: opening a Modeling Study from the Current
Project screen, a study-detail route showing persisted metadata and its models, and strict
Study–Project ownership enforcement. No Study schema changes, no model workspace, no scientific
execution, no Figma edits.

## Backend: persistence layer

Two small, additive, read-only functions, following `list_subprojects`/`count_models_by_subproject`'s
own established conventions:

- `app/persistence/subproject.py::get_subproject_for_project(session, project_id, subproject_id)
  -> Subproject | None` -- the ownership check the task explicitly required. A subproject id that
  exists but belongs to a *different* project returns `None` here, identically to one that does
  not exist at all, so the API layer built on top of it can never leak a study from one project
  through a different project's URL.
- `app/persistence/model.py::list_models(session, subproject_id) -> list[Model]` -- every model
  belonging to one Modeling Study, ordered by name.

Both are covered by dedicated persistence tests (`tests/persistence/test_subproject.py`,
`tests/persistence/test_model.py`): `get_subproject_for_project` returns the row for its own
project, `None` for an unknown id, and -- the ownership case specifically -- `None` for a real
study id queried through a *different* project's id. `list_models` is empty for a study with none,
and returns only that study's own rows (never another study's), ordered by name.

## Backend: HTTP API

Two new nested routes in the existing `app/api/v1/routes/projects.py` (not a new router module --
a Modeling Study is a sub-resource of one project, matching the schema's own `project ->
subproject -> model` ownership chain):

- `GET /api/v1/projects/{project_id}/subprojects/{subproject_id}` -> `SubprojectDetail` -- every
  column of one subproject. A 404 for an unknown project id, an unknown subproject id, *or* a
  subproject id that belongs to a different project -- all three cases are indistinguishable to
  the caller, by design: the API layer does not reveal "that study exists, just not here."
- `GET /api/v1/projects/{project_id}/subprojects/{subproject_id}/models` -> `list[ModelListItem]`
  -- every model belonging to that study, ordered by name. Same 404 semantics as above, never an
  empty list for an unknown/mismatched resource.

Both routes share two small private helpers added to the same module,
`_require_project`/`_require_modeling_study`, which raise the identical structured `ApiError` the
existing `get_one_project`/`list_project_modeling_studies` routes already use (not refactored into
those two existing, already-tested routes, to avoid touching working code unnecessarily).

`app/schemas/subproject.py` gained `SubprojectDetail`, following `ProjectDetail`'s own "every real
column" precedent. `app/schemas/model.py` (new) defines `ModelListItem`: `id`, `stable_identifier`,
`name`, `version_label`, `status` -- **only** the columns `Model` actually has.

**Deliberately not invented** (the task's own explicit instruction): Figma's "Models" table also
shows a "Construction" column (e.g. "Protein abundance," "Literature kinetics," "Curated model
v1.3") and a "Calibration / validation" column (e.g. "WT time course / ACC1 perturbation," "Not
assigned"). Neither has a backing column on `Model` (`app/models/model.py`'s real columns are
`stable_identifier`, `name`, `source_type`, `status`, `artifact_reference`, `parent_model_id`,
`version_label`, `notes`). These are free-text scientific-readiness/evidence-assignment claims, and
the task is explicit that those must never be invented -- so `ModelListItem` omits both columns
entirely, rather than filling them with a placeholder. Verified by a dedicated test assertion
(`test_list_modeling_study_models_returns_identity_version_and_status_ordered_by_name` asserts
`"construction"`/`"calibration"` are absent from the response body).

Test coverage: `tests/api/test_modeling_study_detail.py` and `tests/api/test_modeling_study_models.py`
(new) -- success, 404 for an unknown project id, 404 for an unknown study id, **404 for a real
study id belonging to a different project** (the ownership-mismatch case, asserted not to leak the
other project's study), and 422 for a malformed project or study id.

## Frontend

- `frontend/src/lib/router.ts`: extended with a third route, `{ screen: "study-detail"; projectId;
  studyId }`, matched by a new `/^\/projects\/([^/]+)\/studies\/([^/]+)\/?$/` pattern checked
  before the existing project-detail pattern. `router.test.ts`'s old "a nested, unsupported path
  under /projects falls back to the projects screen" test used
  `/projects/abc-123/studies/xyz` as its unsupported-path example -- that path is now a *valid*
  study-detail route, so the test was updated to use a genuinely unsupported path instead, and four
  new tests cover the study-detail pattern itself (basic match, trailing slash, URL-encoded ids,
  and a nested unsupported path *under* a study falling back correctly).
- `frontend/src/components/ModelingStudiesTable.tsx`: the "Study" cell is now a real, accessible
  `RouterLink` to `/projects/{projectId}/studies/{studyId}` (plus a row `onDoubleClick`), exactly
  mirroring `ProjectsTable`'s own title-link/double-click pattern. It was plain text before this
  increment (opening a study was out of scope then); this is the one place a prior increment's
  "disable honestly" choice was *reversed* because the underlying feature is now built, not a new
  deviation.
- `frontend/src/components/StudyDetailScreen.tsx` (new): the "03 — Modeling Study" screen. Fetches
  the owning **project** first (via the already-existing `getProject`) -- so an unknown/mismatched
  project never fires the study request at all, and so the breadcrumb/sidebar always have a real
  project title even on a cold direct link -- then the **study**, scoped to that project id via the
  new ownership-enforcing endpoint, then (only on the study's own success) its **models**. Reuses
  the identical `createStaleGuard` pattern `docs/17` already established, keyed here by the combined
  `projectId`/`studyId` pair.
- `frontend/src/components/StudyInformationCard.tsx` / `ModelsTable.tsx` (new): the two cards
  Figma's screen shows. See "Honest-disclosure deviations" below for what each intentionally omits
  and why. A model's name is plain text, not a styled link -- opening a model (the "model
  workspace") remains out of scope this increment, the identical "disable honestly, never fake"
  principle `docs/17` established for a Modeling Study's row before *this* increment made that
  link real.
- `frontend/src/components/Sidebar.tsx`: extended with a `study-detail` branch. Shows "Current
  Project" as a real link back (preserving project context), a new "Current study" label with the
  study's title (matching Figma's own "CURRENT STUDY" sidebar block, confirmed via
  `get_design_context`/`get_screenshot` on node `46:314`), "Study overview" (active, this screen),
  and Figma's own "All models" / "All datasets" / "All modules" / "Runs & Results" nav items --
  none of those screens exist yet, so each renders disabled (`aria-disabled="true"`, a
  `title="Not available in this increment"`), matching "Modeling Studies"'s own disabled-item
  precedent from `docs/17` rather than being silently omitted.
- `App.tsx`: added the `study-detail` route branch and a second lifted-state callback
  (`onStudyChange`, alongside the existing `onProjectChange`) so the sidebar -- a sibling, not a
  descendant, of `StudyDetailScreen` -- can show the "Current study" label without a duplicate
  fetch.
- `frontend/src/format.ts`: added `formatTaskType`/`formatWorkflowStatus`/`formatModelStatus`,
  mapping the real `SubprojectTaskType`/`WorkflowLifecycleStatus`/`ModelStatus` enum values
  (transcribed from `docs/02_database_schema.md`) to the same title-case labels `formatProjectType`
  already established.

### Honest-disclosure deviations from Figma (intentional, documented)

Figma's "Study information" card shows a 3-column row of fields whose *labels themselves vary by
project*: "Biological scope" / "Conditions" / "Success criterion" for the microbial-metabolism
example, but "Tissue / cell type" / "Condition / intervention" / "Seeds" for the regulatory-network
example. Neither set has a backing `Subproject` column, and -- unlike the project-level fields
`docs/16`'s `ProjectInformationCard` discloses as a fixed "Not captured" set (those labels are
domain-neutral and apply identically to every project) -- there is no single honest fixed label to
show here: which set would even apply is itself project-type-dependent information this schema does
not record. Inventing one arbitrarily would be exactly the kind of fabrication the task's own
instruction forbids. `StudyInformationCard` instead shows only the columns that are real:
`objective`, `task_type`, `status`, `notes`. This is a **deliberate scope decision**, not an
oversight; see the task's own "Treat richer Figma fields as design requirements awaiting schema
work."

Figma's page subtitle reads "Modeling Study ST-001 · Shared evidence for alternative mechanistic
models" -- the "ST-001" portion is a fabricated identifier; `Subproject` has no `stable_identifier`
column (unlike `Project`, which does). The implemented subtitle is "Modeling Study · {task type}"
(e.g. "Modeling Study · Build model") instead -- a real, derived fact, never an invented id.

### States

- **Loading**: three independent messages -- "Loading project…", then "Loading Modeling Study…",
  then "Loading models…" -- verified live via route-delayed responses on each of the three
  requests in turn.
- **Empty**: a study with zero models renders "No models yet." instead of an empty table --
  verified live ("Reference reconstruction," seeded with none).
- **Error**: a structured API failure on the study-metadata fetch renders the real error message,
  never swallowed -- verified live via a mocked 500.
- **Unknown-study**: a 404 on the study-metadata fetch renders a distinct "This Modeling Study could
  not be found." message, with a back link to the *owning project* (`/projects/{projectId}`, not a
  generic "All Projects" link) -- preserving project context exactly as the task required. Verified
  live against a real, non-existent UUID.
- **Unknown-project**: identical to `docs/17`'s own project-detail handling -- "This project could
  not be found." -- verified live, and (since the project fetch runs first) the study/model
  requests are never fired at all for an unknown project.
- **Ownership mismatch**: a real study id (Erlotinib response's own "Erlotinib response" study),
  requested through a *different*, real project's id (Yeast Fatty Acid Engineering). Renders the
  identical "This Modeling Study could not be found." message -- verified live that the response
  never contains any trace of the other project's study (asserted both on the API response body in
  `tests/api/test_modeling_study_detail.py`/`test_modeling_study_models.py` and live in the browser
  by asserting the wrong heading never appears).
- **Direct link, refresh, back/forward navigation**: verified live exactly as in `docs/17`.
- **Stale-response protection**: verified live by navigating to a slow-responding study and then
  immediately to a second, faster-responding study (via manual `pushState`/`popstate`, the same
  technique `docs/17` used) -- the final rendered page correctly showed the second study, never a
  flash of the first, slower one's stale data.

## Testing

- `tests/persistence/test_subproject.py`: three new tests for `get_subproject_for_project` --
  found for its own project, `None` for an unknown id, `None` for the ownership-mismatch case.
- `tests/persistence/test_model.py`: two new tests for `list_models` -- empty, and ordered/
  scoped-to-one-study-only.
- `tests/api/test_modeling_study_detail.py` / `test_modeling_study_models.py` (new): success,
  404 for an unknown project, 404 for an unknown study, 404 for the ownership-mismatch case
  (asserted not to leak the other project's data), and 422 for a malformed id, for both endpoints.
- `frontend/src/lib/router.test.ts`: four new tests for the study-detail route pattern (plus one
  existing test updated, since its old "unsupported path" example became a valid route -- see
  above).
- Full backend suite: **373 passed** (356 prior + 17 new), `ruff check`/`ruff format --check` clean.
  Commands run (from the repository root, `.venv` active):
  `python -m pytest -q`, `ruff check .`, `ruff format --check .`.
- Frontend (from `frontend/`): `npm run typecheck` (clean), `npm run build` (clean; 47 modules
  transformed, up from 44 before this increment), `npm run test` (15/15 passing: 11 new/updated
  router tests + the 4 pre-existing `staleGuard` tests, unaffected by this increment).

## Live browser verification

Node, the backend (`uvicorn`, port 8000), and the frontend (`vite dev`, port 5173) were brought up
exactly as in `docs/16`/`docs/17`'s own sessions, reusing the same isolated, never-committed
`verify-tools/` scratch Playwright project (Chromium already installed from the prior session's
manual extraction; no reinstall needed).

A one-off scratch seed script (`seed_modeling_study_verification.py`, not part of the repository)
seeded: "Yeast Fatty Acid Engineering" with an "ACC1 perturbation" study (objective, notes, three
models -- two with version labels and an `ACTIVE` status, one deliberately with no version label
and a `DRAFT` status) and a "Reference reconstruction" study (deliberately no objective/notes,
zero models); and "EGFR Drug Response" with an "Erlotinib response" study (the
ownership-mismatch target).

**Database-identity correction (added by `docs/22_database_configuration_and_verification
_safety.md`).** This section originally claimed `uvicorn` ran with `APP_ENV=test` and that
seeding was "safe because the test database is reset by the next `pytest` run" -- implying it
ran against a disposable database. It did not: `APP_ENV=test` has no effect on which database
the application connects to, so this session actually ran against the real development database.
This screen's own navigation flow was re-verified against the actual test database
(`workbench_test`, confirmed disposable by `scripts/db_safety.py::require_disposable_database`
before seeding) and renders identically -- heading, breadcrumb, the three model rows with their
exact version/status values, and the ownership-mismatch 404 all reproduced exactly. Only the
database-identity claim was wrong.

A throwaway Playwright script (`verify_modeling_study.mjs`, in the same scratch `verify-tools/`
project) drove a real Chromium browser against the real running servers. Every observed result
below is this script's actual printed output or a screenshot it captured, not an assumption:

| Check | Observed result |
|---|---|
| Open a study via the accessible link | URL became `/projects/<uuid>/studies/<uuid>`; heading "ACC1 perturbation" |
| Breadcrumb | "Projects / Yeast Fatty Acid Engineering / ACC1 perturbation" |
| Study information: task type / status | "Build model" / "Active" |
| Study information: objective | the real seeded sentence, not "Not captured" |
| "Edit Study" disabled | `true` |
| Model rows | 3 |
| Model names | `["Curated fatty acid model","Expert Antimony reference","Reduced pathway model"]` |
| Model versions | `["v1.3","v1.0","Not captured"]` -- the one model seeded without a version label correctly shows "Not captured," never a blank cell |
| Model statuses | `["Active","Active","Draft"]` |
| "New Model" disabled | `true` |
| Sidebar active item | `["Study overview"]` |
| Sidebar disabled items | `["All models","All datasets","All modules","Runs & Results"]` |
| Sidebar "Current study" | "ACC1 perturbation" |
| Sidebar "Current Project" link | `href="/projects/<uuid>"` -- a real link back, not a dead label |
| Sidebar project mode | "Microbial Metabolism" |
| Empty models state | "No models yet." (Reference reconstruction) |
| Empty study's "Not captured" fields | 2 (Objective, Notes) |
| Direct link + refresh | both loaded "ACC1 perturbation" correctly |
| Back navigation | returned to the Current Project screen; its Modeling Studies table confirmed visible |
| Forward navigation | returned to the same study's detail URL |
| Unknown-study state | "This Modeling Study could not be found." with a back link to `/projects/<uuid>` (the owning project, not a generic All-Projects link) |
| Unknown-project state | "This project could not be found." |
| **Ownership mismatch** | Erlotinib response's study id, requested through Yeast's project id, rendered "This Modeling Study could not be found." -- its own heading never appeared anywhere on the page |
| Loading states | "Loading project…", "Loading Modeling Study…", "Loading models…" (each independently, via a route-delayed response on each of the three requests) |
| Error state | "Couldn't load this Modeling Study: Simulated failure for verification." (mocked 500 on the study endpoint) |
| Rapid navigation (stale-response protection) | Navigated to ACC1 perturbation (1s-delayed response) then immediately to Reference reconstruction; the final rendered heading was "Reference reconstruction" -- the slower, earlier response never overwrote the faster, later one |
| Console/page errors | 8 console messages, all `Failed to load resource` lines directly caused by the intentionally-triggered 404/500 responses above (the unknown-study, unknown-project, ownership-mismatch, and error checks); 0 uncaught page errors |

Seven screenshots were captured and reviewed directly; all render as expected with no visual
breakage, including the sidebar's new "CURRENT STUDY" block.

**Layout vs. Figma (node `46:314`).** Compared directly against `get_design_context`'s/
`get_screenshot`'s own rendered reference for this node: application header, sidebar nav with
"Current Project" (a link), the new "CURRENT STUDY" block, "Study overview" highlighted, the four
disabled nav items, and "PROJECT MODE"; breadcrumb; page heading and subtitle; the "Study
information" card's structure (heading, then fields, then an action button); and the "Models"
table's row structure all match structurally. Deliberate deviations, both already explained above:
the "Study information" card's per-project-type rich fields are omitted rather than invented, and
the page subtitle never shows a fabricated study identifier. The "Models" table also omits Figma's
"Construction"/"Calibration validation" columns entirely rather than inventing them, per the task's
own explicit instruction. This remains a by-eye structural comparison, not a pixel-diff.

## Remaining limitations

- `ModelListItem` omits `source_type`, `artifact_reference`, `parent_model_id`, and `notes` -- not
  shown by this screen's table, and not yet wired to any screen that would need them (a future
  model-detail screen).
- The model workspace ("opening" a model) and the standalone "All models" / "All datasets" / "All
  modules" / "Runs & Results" nav destinations remain entirely unbuilt -- all are visibly disabled,
  never silently dropped, per this increment's own scope.
- `StudyDetailScreen` re-fetches the owning project on *every* `studyId` change, even when
  navigating between two studies within the same project (it does not receive the already-loaded
  project from a parent/sibling screen). This is a minor, known inefficiency, not a correctness bug
  -- it keeps the screen fully self-contained for direct links/refresh, and the task's scope is
  read-only correctness, not performance. It also means the sidebar's "PROJECT MODE"/"Current
  study" blocks briefly flash to blank on every `studyId` change before repopulating with the
  (usually identical) data, visible only as a brief flash, not a user-facing bug.
- As in `docs/16`/`docs/17`: the pre-existing `npm audit` vulnerabilities in `frontend/`'s
  dependencies remain unaddressed (out of scope; not introduced or worsened by this increment).
- "Layout matches Figma" is still a by-eye structural comparison against one rendered reference,
  not a pixel-diff.
- The live-verification script (`verify_modeling_study.mjs`) and its seed script are throwaway
  scratch tools, not part of the repository and not a regression test that runs on future changes
  -- only `router.test.ts`, the persistence tests, and the API tests are.
- `StudyDetailScreen` does not retry automatically on error; recovering from a failed load requires
  a manual navigation (back then forward, or a refresh). Not requested by this increment's scope,
  so not added.
