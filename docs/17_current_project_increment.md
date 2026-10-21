# Read-Only "Current Project" Navigation

Builds directly on `docs/16_projects_api_first_increment.md`'s "01 — All Projects" increment.
This increment makes Figma's own "02 — Current Project" screen (node `46:203`, file
`4tLH4HX0rdgPxjpNB1aJOW`) real: opening a project from the All Projects table, a project-detail
route showing persisted metadata and its Modeling Studies, and accurate per-study model/dataset
counts. No Study schema changes, no scientific execution, no Figma edits.

## Backend: persistence layer

Two small, additive aggregate functions, following `count_subprojects_by_project`'s own
established convention (one `GROUP BY` query, never one query per row):

- `app/persistence/model.py::count_models_by_subproject(session) -> dict[UUID, int]` -- model
  count per subproject (the "Modeling Studies" table's "Models" column).
- `app/persistence/dataset_reference.py::count_dataset_references_by_subproject(session) ->
  dict[UUID, int]` -- dataset count per subproject (the "Datasets" column).

**Ownership confirmed before defining the dataset count** (the task's own explicit instruction):
`dataset_reference.subproject_id` is nullable (`docs/02_database_schema.md`, "Table:
dataset_reference") -- a dataset can be scoped to a project as a whole without belonging to any
specific study. `count_dataset_references_by_subproject` filters `WHERE subproject_id IS NOT
NULL` explicitly, so a project-wide dataset is never misattributed to one of that project's
studies. Verified both by a dedicated persistence test
(`test_count_dataset_references_by_subproject_ignores_project_only_rows`) and live in the
browser (see below): a seeded project-wide dataset reference correctly left every study's own
"Datasets" count unaffected.

`Model.subproject_id` and `DatasetReference.subproject_id`/`project_id` were already real,
non-nullable-where-relevant foreign keys (`app/models/model.py`,
`app/models/dataset_reference.py`) -- no schema change was needed, only the two read-only
aggregate queries above.

## Backend: HTTP API

One new nested route in the existing `app/api/v1/routes/projects.py` (not a new router module --
Modeling Studies are a sub-resource of one project, matching the schema's own
`project -> subproject` ownership):

- `GET /api/v1/projects/{project_id}/subprojects` -> `list[SubprojectListItem]` (id, title,
  objective, model_count, dataset_count), ordered by title. A 404 (the same structured envelope
  `get_one_project` already uses), never an empty list, for an unknown project id -- so a caller
  of this endpoint alone can still distinguish "this project has no studies" from "this project
  doesn't exist."

`app/schemas/subproject.py` (new) defines `SubprojectListItem`, following
`ProjectListItem`'s own precedent: it exposes only the subset of `Subproject` columns the Figma
table actually shows (Study / Scientific question / Models / Datasets), not every column
`Subproject` has (`task_type`/`status`/`notes` remain available for a future screen, not yet
built).

**"Scientific question" maps to the real `Subproject.objective` column** -- unlike the
project-level "Objective" field (still "Not captured"; `Project` has no such column, per
`docs/16`'s own finding), a Modeling Study's objective is a real, already-existing column. A
`null` objective (a study created without one) still renders "Not captured" honestly, not an
empty cell.

## Frontend

- `frontend/src/lib/router.ts` (new): a minimal, hand-rolled path router -- no router library
  exists in this project (matching the "no component library" precedent `docs/16` already set),
  and two routes do not justify adding one. `parseRoute(pathname): Route` is pure and
  framework-free specifically so it can be unit-tested without a DOM; `navigate`/`useRoute` are
  the thin `history.pushState`/`popstate` integration around it (`pushState` does not itself fire
  `popstate`, so `navigate` dispatches one manually -- the standard workaround), verified live in
  a real browser instead of by a unit test.
- `frontend/src/components/RouterLink.tsx` (new): a real `<a href>` that intercepts only a plain,
  unmodified left click for client-side navigation -- ctrl/cmd/shift/middle-click fall through to
  normal browser handling (open in new tab, etc.), and the link is keyboard-focusable and
  screen-reader-navigable without any extra ARIA. This is the "accessible link/button" the task
  asked for to open a project from the All Projects table (`ProjectsTable.tsx`'s title cell); a
  row's `onDoubleClick` also opens it, matching the screen's own copy ("Double-click its name to
  open it.").
- `frontend/src/components/ProjectDetailScreen.tsx` (new): the "02 — Current Project" screen.
  Fetches project metadata first, then (only on success) its Modeling Studies -- an unknown
  project id never fires the second request at all. Reuses the exact `createStaleGuard` module
  `docs/16` already built and unit-tested for the All Projects row-selection race, keyed by
  `projectId` this time, to protect against rapid navigation between two different projects'
  detail pages. The effect also resets both pieces of state to "loading" on every `projectId`
  change, independent of the race-guard: without that reset, the *previous* project's
  already-resolved table would otherwise stay on screen (a real "stale details" bug distinct
  from any request-ordering race) while the new project's data is still in flight.
- `frontend/src/components/ProjectInformationCard.tsx` / `ModelingStudiesTable.tsx` (new): the
  two cards Figma's screen shows. `MetadataField.tsx` (new) is `ProjectPreviewPanel`'s own
  previously-inline `PreviewField` component, extracted so both screens share the identical
  "Not captured" honesty treatment for the identical field set (Investigator, Start date,
  Project mode, Organism/strain, Scope/condition, Knowledge sources, Objective) rather than two
  copies drifting apart. A Modeling Study's own "Study" cell is deliberately **plain text, not a
  styled link** -- opening a study is out of scope this increment, and a link-styled but
  non-functional cell would mislead a user into expecting it to work (the same "disable
  honestly, never fake" principle `docs/16` already established for "Search projects").
- `frontend/src/components/Sidebar.tsx` (new, extracted from the previously-inline sidebar in
  `App.tsx`): route-aware. Shows only "All Projects" on the All Projects screen; once a project
  is open, also shows "Current Project" (active) and "Modeling Studies" (a separate, not-yet-built
  screen -- rendered as a non-interactive, `aria-disabled` item, never a dead link) plus a
  "PROJECT MODE" section with the open project's mode and organism/context summary. The loaded
  project is lifted from `ProjectDetailScreen` into `App.tsx` via a callback
  (`onProjectChange`), since the sidebar is a sibling, not a descendant, of that screen; the
  callback is called with `null` on every id change and on unmount, so the sidebar never shows a
  stale previous project's mode while a new one loads.
- `App.tsx` now renders based on `useRoute()` instead of a single hard-coded screen.

### States

- **Loading**: a distinct message for the project metadata fetch ("Loading project…") and,
  independently, the Modeling Studies fetch ("Loading Modeling Studies…") -- verified live, both
  via route-delayed responses.
- **Empty**: a project with zero Modeling Studies renders "No Modeling Studies yet." instead of
  an empty table -- verified live (EGFR Drug Response, seeded with none).
- **Error**: a structured API failure renders the real error message, never swallowed --
  verified live via a mocked 500 on the project-metadata endpoint.
- **Unknown-project**: a 404 on the project-metadata fetch renders a distinct "This project could
  not be found." message (not the generic error message) with a link back to All Projects --
  verified live against a real, non-existent UUID (a genuine 404 from the running backend, not a
  mock).
- **Direct link, refresh, back/forward navigation**: verified live -- opening a project's URL
  directly in a fresh browser tab works, reloading that same tab works (Vite's dev server's
  default SPA fallback serves `index.html` for the unmatched deep path; confirmed by observation,
  not assumed), and browser back/forward both correctly re-render the right screen via the
  router's `popstate` listener.

## Testing

- `tests/persistence/test_model.py` / `test_dataset_reference.py`: the two new count functions --
  empty, aggregates correctly per subproject, and (for the dataset count specifically) that a
  project-scoped-only row is never attributed to any subproject.
- `tests/api/test_project_subprojects.py` (new): empty list for a studyless project, correct
  counts and title ordering (including that a project-wide dataset never inflates a study's own
  count), a structured 404 (never an empty list) for an unknown project id, and a 422 for a
  malformed id.
- `frontend/src/lib/router.test.ts` (new): `parseRoute` -- root and `/projects` both resolve to
  the projects screen, `/projects/<id>` resolves with that id, a trailing slash is tolerated, a
  URL-encoded id is decoded, and an unrecognized path (including a nested, unsupported path under
  `/projects`) falls back to the projects screen. Uses Node's built-in `node:test`, the same
  zero-dependency approach `docs/16` already established -- `parseRoute` is pure and
  framework-free specifically so it can be tested this way; the browser-integration half
  (`navigate`/`useRoute`/actual direct-link/refresh/back-forward behavior) is covered by the live
  Playwright verification below instead, mirroring exactly how the prior increment's
  `staleGuard.ts` unit tests were paired with a live race-condition check.
- Full backend suite: **356 passed** (348 prior + 8 new: 4 persistence count tests + 4 API
  tests), `ruff check`/`ruff format --check` clean. Commands run:
  `python -m pytest -q`, `ruff check .`, `ruff format --check .` (from the repository root, `.venv`
  active).
- Frontend: `npm run typecheck` (clean), `npm run build` (clean; 44 modules transformed, up from
  37 before this increment), `npm run test` (11/11 passing: 7 new router tests + the 4 pre-existing
  `staleGuard` tests, unaffected by this increment).

## Live browser verification

Node, the backend (`uvicorn`, port 8000) and the frontend (`vite dev`, port 5173) were brought up
exactly as in `docs/16`'s own session. Four projects were seeded via a one-off scratch script
(not part of the repository): "Yeast Fatty Acid Engineering" with three Modeling Studies (one
with 3 models/4 datasets, one with 2 models/0 datasets, one with neither and no objective), plus
one dataset reference scoped only to the project itself (no `subproject_id`); "EGFR Drug
Response" with zero studies; and two more projects reused from `docs/16`'s own seed for the All
Projects screen's continued correctness.

**Database-identity correction (added by `docs/22_database_configuration_and_verification
_safety.md`).** This section originally claimed `uvicorn` was "pointed at the test database with
`APP_ENV=test`" and that seeding was "directly against the *test* database." Both claims were
wrong, for the same reason given in `docs/16`'s own correction above: `APP_ENV=test` does not
redirect the application to any database; only overriding `DATABASE_URL` does, and this session
did not do that, so it actually ran against the real development database. This screen's own
navigation flow was re-verified against the actual test database (`workbench_test`, confirmed
disposable by `scripts/db_safety.py::require_disposable_database` before seeding) and renders
identically -- heading, the three Modeling Studies rows, their model/dataset counts, and the
"Not captured" paths all reproduced exactly. Only the database-identity claim was wrong.

A throwaway Playwright script (`verify_current_project.mjs`, in the same isolated, never-committed
`verify-tools/` scratch project `docs/16` already set up -- not a new tool, reused as-is) drove a
real Chromium browser against the real running servers. Every observed result below is this
script's actual printed output or a screenshot it captured, not an assumption:

| Check | Observed result |
|---|---|
| Open a project via the accessible link | URL became `/projects/<uuid>`; heading "Yeast Fatty Acid Engineering" |
| Project information card | 5 fields "Not captured" (Investigator, Start date, Scope/condition, Knowledge sources, Objective); Organism/strain correctly showed "BY4741" |
| Modeling Studies rows | 3 rows |
| Model counts per row | `["3","2","0"]` |
| Dataset counts per row | `["4","0","0"]` -- the project-wide dataset correctly never inflated any row |
| Study table "Not captured" | 1 cell, for the study seeded without an objective |
| Sidebar active item | `["Current Project"]` |
| Sidebar project mode | "Microbial Metabolism" |
| Sidebar "Modeling Studies" | `aria-disabled="true"` |
| "Edit project" / "New Modeling Study" disabled | both `true` |
| Direct link + refresh | both loaded "Yeast Fatty Acid Engineering" correctly |
| Back navigation | returned to the All Projects table (confirmed present after allowing the in-app fetch to resolve -- a plain `goBack()` wait does not itself wait for an SPA's own internal fetch, since no real page load occurs) |
| Forward navigation | returned to the same project's detail URL |
| Unknown-project state | "This project could not be found." (against a real, non-existent UUID) |
| Empty Modeling Studies | "No Modeling Studies yet." (EGFR Drug Response) |
| Loading states | "Loading project…" and, independently, "Loading Modeling Studies…" |
| Error state | "Couldn't load this project: Simulated failure for verification." (mocked 500) |
| Rapid navigation (stale-response protection) | Navigated to Yeast (1s-delayed response) then immediately to EGFR; after both responses had time to resolve, the page showed "EGFR Drug Response" -- the slow, earlier Yeast response never overwrote the faster, later one |
| Console/page errors | 4 console messages, all `Failed to load resource` lines directly caused by the intentionally-triggered 404/500 responses above (standard Chromium devtools behavior for any non-2xx fetch, not a JS error); 0 uncaught page errors |

Ten screenshots were captured and reviewed directly; all ten render as expected with no visual
breakage.

**Layout vs. Figma (node `46:203`).** Compared directly against `get_design_context`'s own
rendered reference for this node: application header, sidebar nav with "Current Project"
highlighted and a "PROJECT MODE" block, breadcrumb, page heading and subtitle copy, the "Project
information" card's field layout (two rows of three fields, then Objective, then a button), and
the "Modeling Studies" table's four columns all match structurally. The one deliberate deviation:
a Modeling Study's name is plain text here, not Figma's link-styled text, for the "never a dead
link" reason given above. This remains a by-eye structural comparison, not a pixel-diff.

## Remaining limitations

- `SubprojectListItem` does not expose `task_type`/`status`/`notes` -- not needed by this
  screen's table, and not yet wired to any screen that would need them.
- The Modeling Study detail screen ("03 — Modeling Study," Figma node `103:727`) and the
  standalone "Modeling Studies" nav destination remain entirely unbuilt -- both are visibly
  disabled, never silently dropped, per this increment's own scope.
- As in `docs/16`: the two pre-existing `npm audit` vulnerabilities in `frontend/`'s dependencies
  remain unaddressed (out of scope; not introduced or worsened by this increment).
- "Layout matches Figma" is still a by-eye structural comparison against one rendered reference,
  not a pixel-diff.
- The live-verification script (`verify_current_project.mjs`) and its seed script are throwaway
  scratch tools, not part of the repository and not a regression test that runs on future
  changes -- only `router.test.ts`, the persistence tests, and the API tests are.
- `ProjectDetailScreen` does not retry automatically on error; recovering from a failed load
  requires a manual navigation (back then forward, or a refresh). Not requested by this
  increment's scope, so not added.
