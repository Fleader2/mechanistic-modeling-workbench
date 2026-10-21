# Module-Set First Increment: Draft, Inspect, Save, Reopen

Builds on `docs/20_module_set_domain_contract.md`'s design proposal and its four resolved
decisions (set identity spans model versions with one pinned version per set version; discarded
drafts are soft-marked and hidden, never executable; origin is tracked per version as
AUTOMATED/MANUAL/MIXED_EDITED, with per-member origin deferred; `ModelModule` is reused wherever
sound, with every dependency on `run_record_id` audited first). This increment makes the Figma
"06 — All Modules" catalog (node `60:756`) and its draft/save/reopen flow real for the one case
`docs/20` scoped to increment 1: an **unedited** draft built from an existing hierarchical run,
saved either as a brand-new module set or as the next version of an existing one. No manual
editing, no split/merge, no cross-model-version migration UI, no new execution workflows, no
partition comparison, no Figma edits.

## Dependency audit (done before writing any schema change, per this increment's own instruction)

Grepping every `ModelModule.run_record_id` reference found two call paths that would hard-fail if
that column were made nullable now:

- `model_module_orchestrator.request_module_simulation`, `module_boundary_orchestrator.
  derive_boundary_ports`, `module_calibration_orchestrator.request_module_calibration`, and
  `module_validation_orchestrator.request_module_validation` each do
  `get_run_record(session, module.run_record_id)` and `assert` the result is not `None` before
  calling `resolve_stage1_inputs` on it -- a `NULL` would raise `AssertionError`.
- `module_aggregation_orchestrator.build_module_aggregate` passes `module.run_record_id` straight
  into `ModuleAggregate.hierarchy_run_record_id`, a `NOT NULL` column -- a `NULL` would violate the
  database constraint.

**Resolution**: this increment does not touch `ModelModule.run_record_id` at all. Because it only
ever *references* pre-existing `ModelModule` rows (never creates new ones -- see "Save never
creates a new `ModelModule`" below), every row this increment adds points at a `ModelModule` whose
`run_record_id` is exactly what it always was. The schema change stays deferred to whichever future
increment builds manual editing. Separately, `submit_hierarchical_run`'s `model_id` is nullable, so
draft creation explicitly rejects (422, never a crash) any run with no associated model.

## Backend: schema

New enums in `app/models/enums.py`: `ModuleSetOriginMethod` (`AUTOMATED`/`MANUAL`/`MIXED_EDITED`)
and `ModuleSetDraftStatus` (`OPEN`/`DISCARDED`/`SAVED`).

New file `app/models/module_set.py`, five tables, migration `migrations/versions/0013_module_set.py`
(verified via `tests/database/test_migrations.py`'s downgrade-to-base/upgrade-to-head round trip;
touches no existing table or column):

- **`ModuleSet`**: a stable identity (`stable_identifier`, e.g. "MS-001") that a module set's
  versions all share.
- **`ModuleSetVersion`**: one immutable version, pinned to one `Model` (`model_id`, `NOT NULL`),
  with `origin_method`, an optional `generation_run_record_id`/`base_version_id` chain, and
  `saved_at`/`saved_by`. Unique on `(module_set_id, version)`.
- **`ModuleSetMember`**: one row per module in a version. Always resolves to a real,
  pre-existing `ModelModule` via `model_module_id` (`NOT NULL`, RESTRICT) -- no separate
  identity/hierarchy/name columns, since hierarchy and name are derived from the referenced
  `ModelModule` directly and nothing is ever edited in this increment.
- **`ModuleSetDraft`**: a working, mutable row -- `status` (`OPEN`/`DISCARDED`/`SAVED`),
  `base_run_record_id` or `base_version_id` (what it was built from), and `resulting_version_id`
  once saved. A partial unique index enforces at most one `OPEN` draft per `module_set_id`.
- **`ModuleSetDraftMember`**: the draft's own copy of each member, same shape as
  `ModuleSetMember`.

`ModuleLineageEdge` (cross-version module continuity) is deferred -- not created by this
migration, per `docs/20` §2.1's final resolution.

## Backend: persistence and API

`app/persistence/module_set.py` -- `create_draft_from_run` (validates run ownership,
`stage=HARNESS`, `status=SUCCEEDED`, `model_id is not None`, and that the run has modules, then
copies every module into `ModuleSetDraftMember` rows), `discard_draft` (soft-marks `DISCARDED`,
raising `ModuleSetDraftAlreadyResolved` on an already-resolved draft), `save_draft` (mode
`"new_set"` or `"new_version"`; validates set name / existing-set ownership / model-pin match;
allocates the next version number; copies `ModuleSetDraftMember` rows into `ModuleSetMember` rows
-- **never creates a new `ModelModule` row**; marks the draft `SAVED`), plus ownership-scoped
getters/listers. `app/persistence/run_record.py` gained
`list_hierarchical_runs_for_subproject` (HARNESS/SUCCEEDED/has-a-model, newest first) and
`app/persistence/model_module.py` gained `count_model_modules_by_run`.

Nine routes added to `app/api/v1/routes/projects.py`: list draftable hierarchical runs; create,
list, inspect, discard, and save a draft; list module sets; reopen a version; and boundary-port
inspection for both a draft member and a saved-version member. Duplicate-save returns
`409 CONFLICT` with `{status, resulting_version_id}` in the error context so the frontend can link
straight to what already exists instead of just failing.

**Save never creates a new `ModelModule`.** Every `ModuleSetMember`/`ModuleSetDraftMember` row
always references a `ModelModule` that already exists from hierarchy-search materialization.
Historical `ModelModule` rows, their boundary-port decisions, and `RunRecord`s are never mutated
by any module-set operation -- verified directly in `tests/persistence/test_module_set.py`'s
immutability tests (module/port/run rows read identical before and after a save; `v1` unchanged
after `v2` is saved; a reopened version's JSON is byte-identical across repeated reads).

## Frontend

Three new screens, one shared table component:

- **`ModuleSetsListScreen`** (Figma "06 — All Modules," node `60:756`) -- the catalog: existing
  module sets (linking to each one's latest version) and draftable hierarchical runs (a "Create
  module set draft" button per run).
- **`ModuleSetDraftScreen`** -- an `OPEN` draft's hierarchy/boundary-port table plus three actions
  (save as new set / save new set version / discard), each with an inline confirm-or-cancel form.
  A `SAVED` or `DISCARDED` draft instead shows a status message (linking to the saved version, for
  `SAVED`). The inline-form approach is a deliberate simplification of Figma's separate
  save-confirmation screens -- same information, fewer navigations, named here rather than left
  silently different from the mock.
- **`ModuleSetVersionScreen`** (Figma "Module set saved," node `112:766`) -- read-only reopen view.
  No edit, re-save, or delete action anywhere on this screen.
- **`ModuleHierarchyTable`** -- shared by both screens. Renders members by depth then module id
  (never an invented name), with a lazy-loaded, per-member boundary-port panel whose columns are
  explicitly split into structural facts (species, direction) and execution-specific decisions
  (treatment, resolution, initial value, decided by) -- the same structural/execution boundary
  distinction `docs/20` establishes for the domain model.

Sidebar: "All modules" is the one previously-disabled item this increment makes real, linking to
the catalog and staying marked active across the draft and saved-version screens too. "All
models" stays disabled (hardcoded, since no model-list screen exists yet) -- unlike the Figma
prototype, which highlights "All models" as the active section on a model page, this workbench
continues the explicit precedent from `docs/19` of never marking an unbuilt destination active.

## Two bugs found only by live-browser verification, both fixed

Unit and API tests (which share one SQLAlchemy session between request and assertion inside a
test transaction) could not have caught either of these; both only surfaced once requests crossed
real, independent request/response cycles against a running server.

1. **CORS blocked every POST.** `app/main.py` hardcoded `allow_methods=["GET"]` from when this
   API was read-only-only (`docs/16`-`19`). The first POST route in this app's history (create
   draft) failed preflight with `Disallowed CORS method` before a single byte of application code
   ran. Fixed to `allow_methods=["GET", "POST"]`; the stale "Read-only HTTP API" line in the same
   file's `DESCRIPTION` was corrected alongside it.
2. **The three mutating routes never committed.** `create_module_set_draft`,
   `discard_module_set_draft`, and `save_module_set_draft` called their persistence functions and
   returned, but never called `session.commit()`. `get_session()`'s own docstring says committing
   is "the responsibility of the caller performing the write" -- correct for every *read* route,
   which never writes, but this is the first set of *write* routes this API has ever had, and
   nothing enforced the convention for them. Each request's session was rolled back on close, so a
   created draft 404'd on the very next request. Fixed by adding `session.commit()` after each
   successful mutation, confirmed live: draft creation, discard, and save are now durable across
   independent requests.

Both are now also covered in the automated suite -- not just fixed, but regression-tested, with
each test proven to fail against the original bug before the fix and pass after:
`tests/api/test_module_set_durability.py`. See
`docs/22_database_configuration_and_verification_safety.md`.

## A pre-existing operational finding, unrelated to this increment's own code

While seeding data for live verification, the seed script's first run crashed against what turned
out to be the **real development database** (`workbench`), not a disposable test database --
`APP_ENV=test` does not redirect the application to any database; only overriding `DATABASE_URL`
itself does. This affected every prior increment's own "`APP_ENV=test` uvicorn" live-verification
session too (`docs/16`-`19`), not just this one. The full root-cause, the resulting audit of
`workbench`'s actual state, the independent-session/CORS-preflight regression tests this gap
exposed, the re-verification of `docs/16`-`19`'s own navigation flows against the real test
database, and the proposed (not yet applied) cleanup are all in
`docs/22_database_configuration_and_verification_safety.md` -- written as its own follow-up
increment once the user flagged this finding, rather than folded in here.

## Validation

- **Backend**: `APP_ENV=test python -m pytest -q` -- 439 passed (47 new: 23 in
  `tests/persistence/test_module_set.py` covering draft creation/ownership/rejection, discard,
  save new-set/new-version, duplicate-save protection, immutability, and ownership isolation; 3
  new in `test_run_record.py`; 2 new in `test_model_module.py`; 3 in
  `tests/api/test_hierarchical_runs.py`; ~17 in `tests/api/test_module_sets.py`). `ruff check .`
  and `ruff format --check .` both clean.
- **Frontend**: `npm run typecheck`, `npm run build` (55 modules), and `npm run test` (25 passed,
  7 new router tests for the three new routes) all clean.
- **Live browser walkthrough** (Playwright against `uvicorn` on port 8000, `DATABASE_URL`
  overridden to `workbench_test`, and `vite` dev server on port 5173; seed data: two runs against
  one model, `model_a`, with 3 and 2 modules, one run against a second model, `model_b`, with 1
  module, and one run with no associated model): catalog shows "No module sets yet." plus exactly
  the 3 draftable runs (the model-less run correctly excluded); creating a draft from the 3-module
  run navigates to it and renders all 3 members; inspecting a member shows both structural
  (species/direction) and decided (treatment/resolution/initial value/decided-by) boundary-port
  fields correctly, including the seeded undecided port rendering "Not captured" for both value
  fields; saving as a new set produces `MS-001 "Expert partition" v1` with the immutability note,
  and reopening it in a fresh page renders byte-for-byte the same heading and member count;
  re-saving the same already-`SAVED` draft returns `409 CONFLICT` with `resulting_version_id` in
  context; saving a second draft as a new version of `MS-001` produces `v2`, after which `v1`'s own
  members (re-fetched) are still exactly 3; attempting to save a draft from the `model_b` run as a
  new version of `MS-001` (a different pinned model) returns `422` whose message names
  "revalidation"; discarding a fresh draft returns it to the catalog. No console errors or
  uncaught page errors other than the two expected failed-fetch logs from the deliberate
  409/422 checks.

## Remaining limitations (deferred, not built here)

Manual editing of a draft's members, split/merge, the `ModelModule.run_record_id` schema change,
per-member origin tracking, `ModuleLineageEdge` (cross-version module continuity), a
cross-model-version revalidation UI, and partition comparison all remain exactly as `docs/20`
scoped them out of increment 1.
