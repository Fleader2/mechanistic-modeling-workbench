# 27. Model-Specific Alias Mapping

## 0. What this increment is

Lets a scientist select a saved time-series dataset and a model version, see every measurement
column's own source name/declared unit/sample values alongside its current mapping status, and
assign each column to an exact, real Antimony species identifier -- or explicitly skip it.
Every save is a new, immutable revision, with history and stale-edit protection. Source names
and measurements are never touched; structural columns (sample id/condition id/time/
replicates) are never mapping targets at all. Depends entirely on docs/26's own durable species
catalog, closed first and separately.

## 1. Scope boundaries, stated plainly

Excluded, per task instruction: scientific execution of any kind, reaction/observable mapping
(species only), any Figma change, and schema work unrelated to this feature. A measurement
column's own name (e.g. `[aRAStot]`) is preserved verbatim everywhere -- nothing in this
increment infers a species identity from a column's own spelling; a name match between a column
and a real species is never used to pre-select or auto-confirm an assignment (no "smart"
matching was implemented at all, deliberately -- the task's own instruction that a suggestion
"must not establish an assignment without confirmation" is satisfied simply by never offering
one yet, rather than building a suggestion feature this increment didn't need).

## 2. Three-way assignment status, and why

Every measurement column of a dataset gets exactly one row in every revision, with one of three
statuses, never a two-way boolean:

- **`ASSIGNED`** -- this column's data *is* the named real species. Always carries a verified
  `target_antimony_species_id`.
- **`SKIPPED`** -- a deliberate, explicit decision that this column has no species home. Never
  re-offered as if still undecided.
- **`UNRESOLVED`** -- the default for a column no one has decided about yet (task instruction:
  "allow incomplete mappings to be saved with explicit unresolved status"). A save is never
  blocked by having unresolved columns.

## 3. Revisions, not in-place edits

Every save creates a new `DatasetModelAliasMappingRevision` row -- a complete snapshot of every
measurement column's own status, never a sparse diff (a column the caller's own save request
didn't mention defaults to `UNRESOLVED` in the new revision, never silently carried forward
from the prior one as a side effect of omission). "Current" is simply the row with the highest
`revision_number` for a given (dataset, model) pair -- no separate pointer row exists or is
needed. **Stale-edit protection** mirrors the Module-Set Edited-Module Materialization
increment's own `expected_review_version` discipline exactly: a save names the revision number
it started editing from; if a newer revision already exists, the save is rejected (409) with
the real current revision number in the error context, never silently creating a revision that
discards a genuine concurrent edit.

Each revision also records exactly *which* `ModelSpeciesCatalog` row every target id in it was
validated against (`model_species_catalog_id`) -- reopening a historical revision shows it
against that exact catalog, never "whatever the model's catalog happens to be now" (today these
are always the same row, since a model's catalog is immutable and 1:1, but the revision's own
provenance does not depend on that continuing to hold).

## 4. Server-side validation -- nothing is ever trusted from the client alone

`save_mapping_revision` runs every check below before writing anything, and writes nothing
partially:

1. The target model's own `ModelSpeciesCatalog` must be `AVAILABLE` -- otherwise 409
   (`MappingSpeciesCatalogUnavailableError`). This is the direct, enforced consequence of
   docs/26: there is nothing real to validate a target id against otherwise, so no revision is
   ever created against an unavailable catalog.
2. `expected_revision_number` must match the real current revision number -- otherwise 409
   (`MappingRevisionStaleError`, §3).
3. Every assignment's own `column_name` must be a real measurement column of the dataset --
   never a structural column (`sample_id`/`condition_id`/`time`/replicates), which are simply
   never valid inputs here at all (enforced by construction: the only legal `column_name`
   values are the dataset's own `TimeSeriesMeasurementColumn` rows, which never include a
   structural column in the first place) -- otherwise 422 (`InvalidMappingColumnError`, naming
   every unknown column).
4. Every `ASSIGNED` assignment's own `target_antimony_species_id` must be a real member of the
   pinned catalog's own species set -- otherwise 422 (`InvalidMappingTargetError`, naming every
   invalid id). This is "validate assigned identifiers server-side," taken literally: the
   client-side picker only ever offers real options, but the server never trusts that it was
   actually used.
5. **Duplicate-target handling, defined explicitly**: two or more columns assigned to the
   identical target species in the same revision is rejected outright -- 422
   (`DuplicateMappingTargetError`, naming every conflicting target and its own conflicting
   column names) -- never silently combined, never silently keeping "the first one and
   dropping the rest." The frontend additionally disables an already-used target in every other
   column's own picker, so this is caught before a save is even attempted in the normal case;
   the server-side rejection is the actual enforcement, the UI guard is only a convenience.

## 5. Units: compatible, incompatible, unknown -- never a silent conversion

`app.units.compare_units` (already built, Structured Units increment) is reused unchanged.
Its own four-way `UnitComparisonStatus` (`COMPATIBLE`/`INCOMPATIBLE`/`MALFORMED`/`MISSING`) is
collapsed to the three-way distinction task instructions actually asked for
(`AliasMappingUnitFinding`: `COMPATIBLE`/`INCOMPATIBLE`/`UNKNOWN`, with `MALFORMED`/`MISSING`
both folding into `UNKNOWN` -- both genuinely mean "cannot tell," and the full, un-collapsed
`compare_units` result is retained verbatim alongside, never discarded, for anyone who needs
the finer distinction). No value is ever converted, silently or otherwise -- `unit_finding` is
a disclosed fact about the comparison, nothing here ever rescales a measurement.

**Verified honestly, not merely asserted**: today, every real `unit_finding` is `UNKNOWN`,
because species units are never captured (docs/26 §10 -- `SpeciesSpecification` has no unit
field at all) and this specific regression fixture's own columns declare no unit either. This
was confirmed directly in the real browser walkthrough (§8) rather than assumed, and the
comparison logic itself is still fully implemented and unit-tested with fabricated units
(`tests/persistence/test_dataset_model_alias_mapping.py`'s own coverage exercises the real
`compare_units` call) so it is already correct for whenever either side's own data changes.

## 6. Schema (migration `0018_dataset_model_alias_mapping`)

Two new enums (`alias_mapping_assignment_status`, `alias_mapping_unit_finding`) and two new
tables:

- **`dataset_model_alias_mapping_revision`** -- one row per save, `ON DELETE RESTRICT` from
  `time_series_dataset`/`model`/`model_species_catalog` (every one of the three is an
  independently-meaningful record this revision's own provenance depends on, never silently
  orphaned).
- **`dataset_model_alias_mapping_assignment`** -- one row per measurement column, per revision.
  `ON DELETE CASCADE` from the revision (pure decomposition).

Immutable once created: no persistence function in this repository ever issues an `UPDATE`
against either table.

## 7. API surface

Four routes, all ownership-scoped under one Modeling Study's own dataset and model (404 for an
unknown dataset/model, or either belonging to a different study):

| Method | Path | Behavior |
|---|---|---|
| GET | `.../datasets/time-series/{dataset_id}/alias-mapping/{model_id}` | the current revision, or an all-`UNRESOLVED`/revision-0 state if never saved; includes the model's own catalog status/species and every column's own source identity |
| POST | `.../datasets/time-series/{dataset_id}/alias-mapping/{model_id}` | save a new revision (§4); 201 |
| GET | `.../alias-mapping/{model_id}/revisions` | every revision ever saved, newest first |
| GET | `.../alias-mapping/{model_id}/revisions/{revision_number}` | reopen one specific, historical revision, exactly as saved |

## 8. Test evidence

622 backend tests passed total (597 pre-existing + 25 new), `ruff check` clean, frontend
`tsc --noEmit` + `vite build` + 36 `node --test` tests (32 pre-existing + 4 new router tests)
all clean:

- `tests/persistence/test_dataset_model_alias_mapping.py` (10 tests) -- a full valid save
  (every column present, defaults to `UNRESOLVED`), a real unit finding (honestly `UNKNOWN`
  against the regression fixture's own undeclared units), revision history/reopen across two
  saves, a stale `expected_revision_number` rejected, an unknown column rejected, an invalid
  target rejected, two columns to the identical target rejected (never combined), an
  unavailable catalog rejected, and -- directly addressing "preserve source names/measurements
  unchanged" -- a save proven to leave the dataset's own rows/columns byte-identical before and
  after.
- `tests/api/test_dataset_model_alias_mapping.py` (11 tests) -- the full HTTP surface mirrored
  at the API layer: never-saved state, an unavailable catalog disclosed with an empty picker,
  a valid save and its exact round-trip on reopen, the same four rejection cases as above each
  surfaced as the correct status code with a structured error context, and revision history/
  reopen through the real routes.
- `tests/api/test_dataset_model_alias_mapping_durability.py` (4 tests, independent-session
  discipline) -- a save survives a brand-new session/request opened after the first fully
  closes; ownership isolation (a dataset or a model from a different study is unreachable, each
  its own test); CORS preflight for the new save route.

## 9. Real, end-to-end browser verification

A real whole-model build (the identical synthetic fixture used throughout docs/26, run through
the actual `run_orchestrator.submit_subproject_run` entrypoint) produced a genuinely captured,
`AVAILABLE` species catalog (4 real species: `s_S1_cyto`...`s_S4_cyto`), and the task's own
regression fixture was saved as a real time-series dataset, both against `workbench_test`
(confirmed disposable via `scripts/db_safety.py::require_disposable_database` before any
write; the real `workbench` database was never started, connected to, or referenced).
Playwright (the same disposable, uncommitted dev-only install from the prior two increments)
then drove the actual rendered `AliasMappingScreen` through clicks/selects alone:

1. The screen loads at revision 0, every one of the dataset's own 5 real measurement columns
   listed by its exact, verbatim name.
2. Setting `[aRAStot]`'s decision to "Assign to species" reveals a picker containing all 4 real,
   verified catalog species (never a structural/canonical id) -- `s_S1_cyto` chosen.
3. `[pMEKtot]` is explicitly set to "Skip."
4. "Save mapping" succeeds; the screen now shows revision 1.
5. The saved assignment's own unit finding renders as `UNKNOWN` -- the real, honest outcome
   (§5), not a stubbed one.
6. Reloading the page shows the identical revision 1, with `[aRAStot]` still `ASSIGNED` to
   `s_S1_cyto` -- nothing is lost, nothing is re-derived.
7. Attempting to assign a third column to the already-used `s_S1_cyto` shows that option
   disabled in its own picker -- the frontend's own duplicate-target guard, confirmed live.
8. Revision history lists revision 1 with its own correct assigned/skipped/unresolved counts;
   clicking "View" reopens it read-only, showing the exact saved assignment.

All services were stopped and `workbench_test` was reset to a clean baseline afterward.

## 10. Two distinctions this increment preserves, stated explicitly

- **The stored identifier is always the exact Antimony symbol, never a friendly label.**
  `target_antimony_species_id` (model: `DatasetModelAliasMappingAssignment.target_antimony_species_id`,
  API: `AliasMappingAssignmentItem.target_antimony_species_id`) is the only value ever written,
  validated, or compared for duplicates (§4). `ModelSpecies.display_name` (docs/26) is carried
  through the read schema as `AliasMappingSpeciesOption.display_name` for a future friendlier
  picker, but today the screen renders the real `antimony_species_id` itself in the picker and
  in every saved/historical row -- there is no friendly label competing with the identifier for
  display today, so none can be confused with it. If a friendly label is ever surfaced in the
  picker, it must remain visibly distinguishable from `antimony_species_id` (e.g. shown
  alongside it, never substituted for it), since `display_name` is unverified free text from
  the Agent 2 assembly while `antimony_species_id` is the one value cross-checked against the
  compiled model (docs/26 §2).
- **A complete mapping establishes correspondence, not analysis readiness.** Every column
  reaching `ASSIGNED` or `SKIPPED` (no column left `UNRESOLVED`) means every measurement
  column has a decided species home or an explicit "no species home" -- nothing more. It does
  not mean the dataset is ready for calibration or simulation: unit compatibility is a
  separately disclosed, never-blocking fact (§5, and today always `UNKNOWN`); experimental
  conditions, replicate handling, and any other analysis-specific input are entirely out of
  this increment's scope and are never checked, implied, or gated on by mapping completeness.
  Nothing in the API or schema (`AliasMappingDetail`, `AliasMappingRevisionSummary`) reports or
  implies an "analysis ready" state -- only `assigned_count`/`skipped_count`/`unresolved_count`,
  which describe correspondence coverage alone.

## 11. Limitations, stated plainly

- **No column-name-based suggestion exists at all.** Not a half-built or disabled feature --
  genuinely not implemented, per §1's own scope decision. A future increment could add one,
  provided it still requires explicit confirmation before establishing an assignment (task
  instruction, honored here by omission rather than by a confirmation step on a feature that
  doesn't exist).
- **Every real unit finding is `UNKNOWN` today**, a direct, honest consequence of docs/26 §10
  (species carry no unit at all yet) -- not a bug in this increment's own comparison logic,
  which is implemented and tested correctly for whenever that changes.
- **"Changing model versions requires explicit mapping revalidation"** is satisfied structurally
  rather than by a dedicated workflow: a different `model_id` is simply a different (dataset,
  model) pair with its own independent revision history starting at 0 -- there is no
  "carry forward" of a mapping from one model to another at all, so revalidation is not an
  optional step a scientist could skip; picking a different model always starts from scratch.
- **No reaction/observable mapping** -- species only, per task instruction.
- **No bulk/CSV import of a mapping** -- every assignment is made one column at a time through
  the screen's own picker.
- **No per-user authentication** -- `saved_by` is free text, the same pre-existing, system-wide
  limitation every other "who did this" field in this codebase already has.

## 12. Final repository state

`mechanistic-modeling-workbench` is left **uncommitted**, per explicit instruction. New: the
migration, models, persistence, schemas, the new API routes added to `app/api/v1/routes/
projects.py`, the frontend `AliasMappingScreen.tsx` plus its routing/navigation wiring (a new
"Map to a model" section on the time-series dataset detail screen) and the three new test
files in §8. No other repository is touched -- this increment, like docs/26's own capture
logic, has no Harness/Agent 2/3/4/5 code change at all; it only reads data docs/26 already
made durable.
