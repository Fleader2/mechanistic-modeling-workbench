# Read-Only Projects API and "01 — All Projects" Screen

See `docs/15_gui_backend_integration_audit.md` §7 ("Recommended First Implementation
Increment"), whose scope this increment implements almost exactly, with the differences noted
below.

## Goal

Make the Figma file's own stated entry point -- "01 — All Projects" (node `46:112`, file
`4tLH4HX0rdgPxjpNB1aJOW`) -- real and functional end to end, read-only: list projects with an
efficiently-computed study count, select a row to preview its metadata, and honestly disclose
every field the current schema cannot populate. No scientific logic changes; no project
creation/editing; no other Figma section.

## Backend: persistence layer

Two small, additive functions, following this repository's existing `list_*`-free convention
exactly as the audit found it (`get_*`/`persist_*` only, until now):

- `app/persistence/project.py::list_projects(session) -> list[Project]` -- every project,
  ordered by title for a stable, predictable table. No count included (kept separate so a
  caller that does not need counts never pays for the extra aggregate query).
- `app/persistence/subproject.py::list_subprojects(session, project_id) -> list[Subproject]`
  and `count_subprojects_by_project(session) -> dict[UUID, int]` -- the latter is the "efficient
  aggregate study counts" requirement: one `GROUP BY` query across every project's subprojects,
  never one `COUNT` query per project row. A project with zero subprojects is simply absent
  from the returned mapping; the API layer applies `.get(project_id, 0)`.

## Backend: HTTP API

A new `app/api/` package, a FastAPI app factory (`app/main.py`), and `app/schemas/` --
following Agent 1's own real, already-started precedent (`agent1-biochemical-curator/app/api/`,
`app/schemas/`), not a speculative one: the error envelope shape
(`{"detail": {"code", "message", "context"}}`), the `ApiError`/exception-handler pattern, and
the `SessionDep` dependency are deliberately the same shape as Agent 1's, so a future shared
frontend client treats both APIs uniformly.

- `GET /api/v1/projects` -> `list[ProjectListItem]` (id, stable_identifier, title, project_type,
  biological_context_summary, study_count).
- `GET /api/v1/projects/{id}` -> `ProjectDetail` (every `Project` column) or a structured 404
  (never a 500) for an unknown id.
- `GET /api/v1/health` -> liveness only.

**Deviation from the audit's suggested file layout:** the audit's §7 listed
`app/api/v1/schemas/project.py`. Once Agent 1's actual API code was read (not just its own
completion report), its schemas live at the top level (`app/schemas/`), not nested under
`app/api/`. This increment follows the real, verified precedent instead of the audit's earlier
guess.

No existing file's behavior changes. `pyproject.toml` gains `fastapi`, `uvicorn[standard]`
(runtime) and `httpx` (dev, required by FastAPI's `TestClient`).

## Honest display of missing metadata

Figma's preview panel (node `46:112`) shows seven fields: Investigator, Start date, Project
mode, Organism / strain, Scope / condition, Knowledge sources, Objective. `Project`
(`app/models/project.py`) has a real column backing exactly one of those (`project_type` ->
"Project mode"). The frontend renders the rest as an explicit, visually distinct "Not captured"
placeholder rather than inventing a value:

- **Investigator**, **Scope / condition**, **Knowledge sources**, **Objective** -- no column
  exists on `Project` for any of these at all (consistent with the audit's own P0/P1 findings:
  no auth/ownership model yet, and "Objective" is actually a `Subproject` field in the schema,
  not a `Project` one).
- **Start date** -- deliberately never backed by `created_at`. `created_at` records when the
  Workbench row was inserted, not when the scientific study began; the task instructions for
  this increment were explicit that conflating the two would be inventing a value, not
  disclosing one. No dedicated start-date column exists yet.
- **Organism / strain** -- the closest real column, `strain_genotype_notes`, is used; when it is
  `null` the same "Not captured" placeholder renders (this is a real column with a real null,
  not a missing-field case, but the display treatment is identical and equally honest).
- The table's **"Organism / system"** column uses the separate `biological_context_summary`
  column -- the closer match for that broader label; `strain_genotype_notes` is reserved for the
  narrower preview-panel field. Both are plain nullable `Text` columns today (no structured
  organism/strain split exists in the schema), so this mapping is a judgment call, not a
  guarantee that the two Figma labels and the two columns are semantically identical.

## Out of scope (left disabled, not silently dropped)

Per the task's own instruction to "clearly disable or mark actions outside this increment as
unavailable" rather than omit them:

- **"Search projects"** -- rendered, `disabled`, with an explanatory note. The audit had already
  flagged that Figma itself defines no destination/behavior for this button.
- **Opening a project** (Figma's "double-click its name to open it") -- the table renders the
  Figma copy describing this gesture (visual fidelity) immediately followed by a static note
  that it is not wired up this increment; no double-click handler exists, so nothing silently
  no-ops.
- **"Create a new project"** -- the full panel (mode radios, "Create Project" button) renders
  matching Figma's layout, every control `disabled`, with an explanatory note. Creation remains
  Phase 1's deferred remaining half, exactly as the audit recommended (the mode-selector
  inconsistency and "Project details" field ambiguity flagged in the audit's §1 still need
  design input before that form can be built honestly).

## Frontend

A new `frontend/` directory at the repository root: a minimal Vite + React + TypeScript
scaffold (no component library, hand-written CSS matched by eye against the Figma screenshot
captured for this increment -- this is the first frontend code anywhere in this repository, so
there was no existing design-token system to reuse). App shell (header + sidebar) matches the
Figma file's persistent chrome; `ProjectsListScreen` is the only real screen.

State handling covers all four required states independently for the list and the row-selection
detail fetch: loading, error (network/API failure, message surfaced, never swallowed), empty
(zero projects), and -- for the detail panel specifically -- no-selection (before any row is
clicked).

## Testing

- `tests/persistence/test_project.py` / `test_subproject.py`: `list_projects`,
  `list_subprojects`, `count_subprojects_by_project` -- empty, single, multiple, correct
  ordering, and (for the count) that a zero-study project is correctly absent rather than
  present with `0`.
- `tests/api/test_projects.py`, run with a FastAPI `TestClient` against a real seeded test
  database: empty list, multiple projects with correct per-project study counts and ordering,
  full detail-by-id, a structured 404 for an unknown id (never a 500), and a structured 422 for
  a malformed id.
- `tests/conftest.py` gained `app`/`client` fixtures. The FastAPI `get_session` dependency is
  overridden to yield the test's own `db_session` (a generator-function override, not a bare
  iterator -- FastAPI's dependency resolution only unwraps a generator *function*), so seed data
  flushed-but-never-committed within a test is visible to API calls made in that same test,
  while the existing per-test rollback still guarantees nothing persists past it.
- Full suite: 345 passed (334 pre-existing + 11 new), zero regressions. `ruff check`/
  `ruff format --check` clean.

## Validation (follow-up session)

A later session completed the validation the section below originally flagged as outstanding:
the frontend was actually built, type-checked, tested, and exercised in a real Chromium browser
against the real FastAPI backend. Everything in this section is a report of commands actually
run and their actual observed output, not a restatement of intent.

**Environment.** No Node.js, npm, or Docker existed on the machine at the start of this session
(confirmed via `which node npm npx nvm volta fnm` and `which docker`, all empty/127). Homebrew
was available, so Node was installed with it: `brew install node` -> Node `v26.12.0`, npm
`11.20.0`. This is the "exact environment requirement" the original increment could not satisfy
on its own: a Homebrew (or equivalent) install of Node is required to build/typecheck/test this
frontend; nothing in the frontend itself needs anything more exotic than that.

**Frontend build and checks**, run from `frontend/` after `npm install` (66 packages, later +3
for `@types/node`):

- `npm run typecheck` (`tsc --noEmit`) -- clean, zero errors.
- `npm run build` (`tsc --noEmit && vite build`) -- clean; produced `dist/` (`index.html`,
  ~3.75 kB CSS, ~148.8 kB JS, 37 modules transformed).
- `npm run test` (`node --test src/**/*.test.ts`, Node's built-in test runner -- deliberately no
  new test-framework dependency) -- 4/4 passing.
- `npm audit` reported 2 pre-existing vulnerabilities (1 moderate, 1 high) in third-party
  dependencies. Not investigated or remediated: dependency hardening was not in scope for this
  validation pass, and fixing it unasked would itself have been scope expansion. Disclosed here
  rather than silently fixed or silently omitted.
- The original scripts (`tsc -b && vite build`, `tsc -b --noEmit`) do not work with this
  project's single, non-`composite` `tsconfig.json` (`tsc -b` is project-reference build mode);
  they were corrected to plain `tsc --noEmit` forms. This is a fix to a script that was never
  actually run before, not a behavior change.

**Stale-response fix.** Reasoning through "rapid row changes do not display stale details"
surfaced a real, previously-unverified bug: `ProjectsListScreen`'s row-click handler fetched
project detail on every click with no guard against out-of-order resolution, so a slow-resolving
earlier click could overwrite a faster-resolving later click's panel. Fixed with a small,
dependency-free `frontend/src/lib/staleGuard.ts` ("latest request wins") wired into
`ProjectsListScreen.handleSelect`, and covered by `frontend/src/lib/staleGuard.test.ts` (4 cases,
Node's built-in `node:test`, run via `npm run test` above). The fix is also confirmed live in a
real browser -- see the race-condition check below.

**CORS.** The frontend (Vite, port 5173) and backend (Uvicorn, port 8000) are different origins,
so a proxy-free browser `fetch` from the frontend would be blocked by the browser regardless of
backend correctness. Added `CORSMiddleware` in `app/main.py`, configured via a new
`cors_allow_origins` setting (`app/config/settings.py`, defaulting to the Vite dev server's own
default origins, overridable via a `CORS_ALLOW_ORIGINS` env var). A dev-only Vite proxy was
considered and rejected: CORS is needed regardless of dev-vs-prod topology (a separately-deployed
frontend in production still needs it), while a proxy only solves the local case. Covered by a
new `tests/api/test_cors.py` (3 cases: allowed origin gets the header, an unconfigured origin
gets no header, and an OPTIONS preflight succeeds for an allowed origin).

**Backend re-run** (required because `app/main.py` and `app/config/settings.py` changed), from
the repository root with `.venv` active:

- `python -m pytest -q` -> **348 passed** (the 345 reported above + 3 new CORS tests), 1 warning
  (a pre-existing, unrelated `httpx`/`starlette.testclient` deprecation warning, not introduced
  by this session).
- `ruff check .` -> "All checks passed!"
- `ruff format --check .` -> "146 files already formatted."

**Live verification data.** Four projects were seeded, matching the Figma mockup's example data
for recognizability: `PRJ-001` Yeast Fatty Acid Engineering (4 studies), `PRJ-002` EGFR Drug
Response (3), `PRJ-003` Central Carbon Reconstruction (2), and `PRJ-004` Unlabeled New Project (0
studies, no `biological_context_summary`, deliberately included to exercise the zero-count and
"Not captured" paths). The script itself was not added to the repository.

**Database-identity correction (added by `docs/22_database_configuration_and_verification
_safety.md`).** This section originally claimed the seed script ran "against the *test* database
(`TEST_DATABASE_URL`, with `APP_ENV=test`)" and that nothing was written to the real development
database. That claim was wrong: `APP_ENV=test` has no effect anywhere on which database the
application connects to -- only overriding `DATABASE_URL` itself does -- so this session's
`uvicorn`/seed script actually ran against the real development database (`workbench`), not a
disposable one. `docs/22` has the full root-cause explanation, the resulting audit of
`workbench`'s state, and a guard (`scripts/db_safety.py::require_disposable_database`) that now
makes this mistake impossible to repeat silently. The application behavior this section
describes was re-verified against the actual test database (`workbench_test`, confirmed
disposable by that guard before seeding) and renders identically -- every row in the table below
was reproduced exactly. Only this section's database-identity claim was wrong; nothing about the
frontend or backend behavior it documents needed correcting.

**Browser verification.** No browser-automation tool was available to Claude directly in this
session, and the one Figma tool that can capture a live localhost page writes into the Figma
file itself, which the task explicitly forbade. Instead, Playwright + Chromium were installed as
an isolated, throwaway tool in its own scratch npm project (`verify-tools/`, never part of
`frontend/`'s own dependency tree, never committed), and driven against the real, running
`uvicorn` (port 8000, seeded test DB) and `vite dev` (port 5173) servers. Every bullet in the
task's verification checklist was exercised and its actual output captured:

| Check | Observed result |
|---|---|
| Row count / listing | 4 rows rendered |
| Study counts (table order) | `["2","3","0","4"]` -- Central Carbon, EGFR, Unlabeled, Yeast (alphabetical by title, matching `list_projects`'s `ORDER BY title`) |
| Row selection / preview metadata | Selecting "Yeast Fatty Acid Engineering" shows `"Selected project · Yeast Fatty Acid Engineering · PRJ-001"` |
| "Not captured" (detail panel) | 5 fields shown as `Not captured` for the seeded Yeast project (Investigator, Start date, Scope/condition, Knowledge sources, Objective) -- matches the schema gap documented above |
| "Not captured" (table) | 1 cell, for `PRJ-004`'s Organism/system |
| Out-of-scope actions disabled | "Search projects" disabled: `true`; "Create Project" disabled: `true`; all `project-mode` radios disabled: `true` |
| Empty state | Route-intercepted `/api/v1/projects` -> `[]`; rendered message: `"No projects yet."` |
| Error state | Route-intercepted `/api/v1/projects` -> HTTP 500 with the structured error envelope; rendered message: `"Couldn't load projects: Simulated failure for verification."` |
| Loading state (list) | Route-delayed response; rendered message observed before the response landed: `"Loading projects…"` |
| Loading state (detail) | Same technique on `/api/v1/projects/{id}`; rendered message observed via screenshot before the delayed response landed: `"Loading project details…"` |
| Rapid row changes / stale data | Yeast's detail response delayed 1s; clicked Yeast then immediately EGFR; after waiting past both responses' resolution, the panel read `"Selected project · EGFR Drug Response · PRJ-002"` -- the fast, later click won, the slow, earlier one never overwrote it |
| Console/page errors | 0 console errors, 0 uncaught page errors across every scenario above |

Eight screenshots were captured during this run and reviewed directly (initial load, row
selected, missing-metadata row selected, empty, error, loading, detail-loading, and the
rapid-row-change result). All eight render as expected with no visual breakage.

**Layout vs. Figma (node `46:112`).** The rendered app was compared directly against the Figma
screenshot captured for this node: header, sidebar nav, breadcrumb, "Projects" heading and
subhead copy, "Search projects" button placement, table column order (Project / Mode / Organism
system / Studies), the preview panel's three-column field layout below the table, and the
"Create a new project" card (mode radios + "Create Project" button) all match structurally. The
only differences are the italic scope-limiting notes this increment deliberately adds ("Opening a
project and searching projects aren't available in this increment.", "Project creation isn't
available in this increment.") -- intentional disclosure text per this increment's own design,
not a layout defect. This remains a by-eye structural comparison against one static screenshot,
not a pixel-diff.

**Environment quirks worth recording**, in case a future session repeats this setup:

- Vite's dev server binds to `localhost`, which resolves to `::1` on this machine, not
  `127.0.0.1`; `curl http://127.0.0.1:5173/` fails to connect while `curl http://localhost:5173/`
  succeeds. Not a bug in the app.
- `npx playwright install chromium` hung indefinitely during extraction on this machine (observed
  twice, including once left running for several hours with the process accumulating under 2
  seconds of CPU time total -- a genuine stall, not slow progress). The download itself completed
  normally; the hang was in Playwright's pure-JS `extract-zip`/`yauzl`-based unzip step, which
  this environment's app-bundle symlinks seem to stall indefinitely rather than produce an error.
  Worked around by extracting the already-downloaded zip manually with macOS's `ditto -x -k`
  (which succeeds in seconds and handles the bundle's symlinks correctly) into
  `~/Library/Caches/ms-playwright/chromium-<rev>/`, `chmod 755` on the `Chromium` executable, and
  writing an empty `INSTALLATION_COMPLETE` marker file in that directory so Playwright's registry
  recognizes the browser as already installed. `verify-tools/` (the throwaway Playwright project)
  and the `uvicorn`/`vite` dev servers started for this verification were all stopped at the end
  of the session; none of it is part of the repository.

## Remaining limitations

- The `ProjectDetail`/`ProjectListItem` schemas expose every real `Project` column (including
  `description`, `notes`, `status`, `agent1_organism_id`), but the preview panel only surfaces
  the subset Figma's own fixed panel layout shows. The rest are already available over the API
  for a future screen.
- The two `npm audit` vulnerabilities noted above (1 moderate, 1 high, in `frontend/`'s existing
  dependencies) remain unaddressed -- observed, not fixed, as noted.
- "Layout matches Figma" above is still a by-eye structural comparison against a single static
  screenshot captured in an earlier session, not a pixel-diff and not a re-fetch of the Figma
  node to confirm the design hasn't changed since that screenshot was taken.
- The detail-loading state's exact rendered copy was observed via screenshot during this session
  but is not independently asserted by an automated test; only the stale-response-guard behavior
  has a dedicated unit test (`staleGuard.test.ts`). The Playwright script that exercised every
  other state in this table is a throwaway verification tool (`verify-tools/`, not part of the
  repository), not a regression test that runs on future changes.
