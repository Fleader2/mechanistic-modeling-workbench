# 26. Model-Species Catalog Prerequisite

## 0. Why this increment exists on its own

The originally requested increment was model-specific alias mapping for imported time-series
datasets. Its own first instruction was to verify, before building anything, that "an
authoritative species catalog is durably available for the selected model version without
running a simulation" -- and, explicitly, to document the gap and a proposed solution rather
than build a misleading target picker if that prerequisite turned out to be missing.

It was missing. This increment closes that specific gap, on its own, before any alias-mapping
code is written (docs/27 covers that separately).

## 1. The gap, precisely

`app.models.model.Model`'s own docstring already says it plainly: "the actual executable
content lives nowhere durable yet -- it is Agent 2's transient, in-memory object, serialized
once per run as Antimony text + a JSON mirror." Confirmed directly this increment:
`app.orchestration.run_orchestrator.submit_subproject_run` -- the one function that updates a
`Model` row after a real build -- only ever copies the **opaque path string** of Agent 2's own
output file (`result.model_artifact_reference`) onto `Model.artifact_reference`. It never reads
that file's content back into the Workbench's own database. That file lives only in the
harness's own transient, gitignored `artifacts/runs/<run_id>/` directory (already documented
elsewhere, `app.models.run_record`'s own docstring, as regenerable/not durably kept). So before
this increment, "what species does Model X have" could only be answered by re-running
something, inferring from an unrelated module's own `ModuleExecutionSnapshot` (a different,
smaller composition entirely), or guessing from dataset column names -- the last two explicitly
forbidden by the alias-mapping task's own instructions, and the first explicitly excluded by
"without running a simulation."

**No `Model`-creation path other than a real whole-model build exists today.** `persist_model`
is the sole creation function (no API route calls it; it's invoked only by
`run_orchestrator.submit_subproject_run`'s own caller, test fixtures, and ad-hoc scripts), and
is never updated in place (its own docstring: "never updates an existing row" -- lineage is
always a new row via `parent_model_id`). This matters for §6 below.

## 2. The harder question: does Agent 2's structural network even match the real model?

Verified directly, empirically, before designing anything -- per the task's own explicit
instruction not to assume identical membership:

Ran Agent 2's real pipeline on the Harness's own synthetic fixture (whole model, not a reduced
module). Agent 2's `FullNetwork.species` reported exactly 4 canonical species
(`compound-S1::in::compartment-1` ... `S4`), each with an `antimony_symbol_map` entry
(`s_S1_cyto` ... `s_S4_cyto`). Loaded the real, generated `antimony_text` through Agent 3's own
`app.agent3.loader.load_antimony_model` (the identical mechanism Agent 3 itself already uses,
confirmed by reading `app.agent3.perturbation`'s own existing resolution logic) and queried the
real, compiled `roadrunner` model directly: all 4 symbols matched exactly, as real floating
species, with the real compartment symbol (`c_cyto`) -- genuinely different from the canonical
compartment id (`compartment-1`), confirming compartment identity needs its own handling (§4).

**For a whole model, membership matched exactly in this test.** But the general claim --
"Agent 2's own structural network is not guaranteed to have identical membership with the
compiled model" -- already has a real, previously-observed counter-example in this same
session's own prior work: Agent 3's own perturbation-target resolution
(`app.agent3.perturbation`) already discloses a finding
(`perturbation-target-unresolved:...`) for exactly this situation on a **reduced module**'s own
standalone Antimony (a species that is a module's own output boundary, with no further
consuming reaction inside that one module, can legitimately become a `BOUNDARY` species in the
compiled model rather than `FLOATING` -- or, in a different module shape, simply not survive
compilation as a reachable/referenced symbol at all). This increment's own catalog is scoped to
whole-model builds only (never a module's reduced Antimony), where the empirical test found
exact agreement -- but the capture logic below still never *assumes* that agreement; it
verifies it, every time, against the real compiled model, and discloses (never silently drops)
any canonical species that does not survive.

## 3. The human-facing identifier

Confirmed directly (and reinforced by explicit correction mid-implementation): the one field a
human ever sees or selects as "the species" is the real, compiled **Antimony symbol**
(`ModelSpecies.antimony_species_id`) -- human-readable whenever Agent 2's own naming module had
a curated biological name to derive it from (its own docstring's example: `acetyl_CoA_cytosol`;
the synthetic test fixture's own generic names, e.g. `s_S1_cyto`, happened to be plainer only
because the *test data* has generic names, not because the mechanism differs for real curated
data). `ModelSpecies.canonical_species_id` (Agent 2's own internal structural id, e.g.
`compound-S1::in::compartment-1`) is retained purely as internal provenance/traceability and is
never surfaced as if it were itself a valid mapping target anywhere in this codebase.

## 4. Compartment context

`antimony_symbol_map` exposes no compartment category at all (confirmed by reading
`app.agent2.pipeline._antimony_symbol_map`: "Only the three categories a downstream consumer
actually needs ... compartments/events/observables are never referenced"). Compartment
display therefore deliberately uses the **canonical** compartment id/name (Agent 2's own
`FullNetwork.compartments`), never an Antimony-compartment-symbol translation -- which doesn't
exist as a traceable mapping anyway, and isn't needed: Agent 2's own `FullNetwork` already
validates every species' compartment reference internally (its own docstring: "every species'
compartment exists"), so the canonical id is already reliable. This increment's own capture
logic still re-validates this defensively (§6) rather than trusting that guarantee blindly.

## 5. Schema (migration `0017_model_species_catalog`)

Two new enums (`model_species_catalog_status`: `AVAILABLE`/`UNAVAILABLE`;
`model_species_kind`: `FLOATING`/`BOUNDARY`) and three new tables:

- **`model_species_catalog`** -- one row per `Model`, 1:1, `ON DELETE CASCADE` from `model`
  (this table has no independent existence apart from describing that one Model -- unlike
  `time_series_dataset`'s own `RESTRICT` relationship to `dataset_reference`, which *is* an
  independently-meaningful record). **No row at all for a given `model_id` means "capture was
  never attempted"** -- read identically to an explicit `UNAVAILABLE` row by every caller
  (`get_model_species_catalog`), never silently treated as a valid, empty catalog. Every row
  (success or failure) is pinned to the specific `run_record` that produced/attempted it
  (`ON DELETE RESTRICT` -- mirrors the identical precedent `model_module`/`module_set` already
  set for a `run_record` reference that must never be silently orphaned). Carries
  `unavailable_reason` (always set when `UNAVAILABLE`), the durably-retained Antimony source
  artifact's own reference/checksum, and two disclosure lists
  (`unresolved_canonical_species_ids`/`unmapped_canonical_species_ids`, JSON-encoded, always
  `"[]"` rather than `null` when empty -- "no anomalies" and "not yet checked" must never be
  confused).
- **`model_species`** -- one row per real, *verified* species (§2/§3 above). `ON DELETE
  CASCADE` from `model_species_catalog` (pure decomposition).
- **`model_compartment`** -- the same real compartments as their own validated set (§4,
  `species_count` per compartment). `ON DELETE CASCADE` from `model_species_catalog`.

Immutable once created: no persistence function in this repository ever issues an `UPDATE`
against any of the three tables.

## 6. Capture logic (`app.orchestration.model_species_catalog_orchestrator`)

Wired into `run_orchestrator.submit_subproject_run`'s own success path, immediately after it
sets `Model.artifact_reference` for a real whole-model build. Never raises -- a capture failure
is always disclosed as an explicit `UNAVAILABLE` row, never an aborted build (task instruction:
"a capture failure must not leave the model falsely marked mapping-ready"):

1. Repeat-safe short-circuit: if a catalog already exists for this `model_id`, return it
   unchanged -- no re-capture, no re-invocation of anything.
2. Read/parse Agent 2's own build-output JSON (the same local path already in hand as
   `model_artifact_reference`) -- a missing/unreadable/malformed file is `UNAVAILABLE`, caught
   defensively, never an exception.
3. Missing `antimony_text` in that output is `UNAVAILABLE`.
4. Durably retain the real Antimony text via `app.storage.save_model_antimony_text`
   (content-addressed, the identical convention the Downloadable Two-Tab Excel Template
   increment already established, generalized here as `app.storage.save_blob`) -- **before**
   invoking the harness, so the source artifact is retained even if verification itself fails.
5. Invoke the new harness contract (§7) to get the real, compiled model's own floating/boundary
   species ids and compartment ids. A harness-client error, or `load_succeeded=False` (the
   Antimony text didn't even compile), is `UNAVAILABLE` with the real reason -- never a valid
   empty catalog (an unloadable model has nothing real to catalog at all).
6. For every canonical species in Agent 2's own structural network: look up its
   `antimony_symbol_map` entry. No entry at all -> disclosed in `unmapped_canonical_species_ids`,
   skipped. An entry that does not appear among the real, compiled model's own species ->
   disclosed in `unresolved_canonical_species_ids`, skipped. Otherwise -> captured, with
   `kind` set from which real set (`FLOATING`/`BOUNDARY`) the symbol was actually found in --
   never inferred from Agent 2's own structural `constant`/`boundary_condition` flags, which
   describe intent, not the compiled model's own actual classification.
7. Defensive validation, each triggering `UNAVAILABLE` rather than silently proceeding: a
   captured species whose own `compartment_id` is not found among Agent 2's own reported
   compartments (a referential-integrity anomaly Agent 2's own construction should already
   prevent, re-checked anyway); two canonical species resolving to the identical real Antimony
   id (never silently combined into one row).
8. Persist one atomic, repeat-safe write (`persist_model_species_catalog`) -- `AVAILABLE` with
   every captured species/compartment, or `UNAVAILABLE` with a specific reason.

## 7. The new Workbench <-> Harness contract

A genuinely minimal, single-purpose addition, mirroring every other contract family in this
project exactly (`WorkbenchModelAntimonyVerificationRequest`/`Result` in the Harness's own
`workbench_contracts.py`; `ModelAntimonyVerificationRequest`/`Result` in this repository's own
`app.contracts.model_antimony_verification`; `scripts/run_workbench_model_antimony
_verification_request.py` as the canonical entrypoint). Takes `antimony_text` directly (never
an Agent 1/2 input -- Agent 2 is never invoked by this contract at all, since the Workbench
already has the text from its own prior build) and routes it through a new, minimal Agent 3
runner (`run_agent3_inspect_antimony_model.py`) that calls Agent 3's own, already-committed
`load_antimony_model` and reports `getFloatingSpeciesIds`/`getBoundarySpeciesIds`/
`getCompartmentIds` verbatim. A compilation failure is reported as data
(`load_succeeded: false`), never an infrastructure error -- this script's whole purpose is to
report whether the model loads, so a load failure is nonetheless a complete, successful
inspection.

## 8. Test evidence

**Harness repository**: 246 passed total (238 pre-existing + 8 new,
`tests/harness/test_workbench_model_antimony_verification_contract.py`) -- contract
round-trip, pre-execution rejections, a real valid-Antimony load (reporting real floating
species), a real boundary-species case (floating vs. boundary correctly distinguished), a real
malformed-Antimony case (`load_succeeded=False` with the real compiler error message,
`status=SUCCEEDED` since this is not an infrastructure failure), and replay-by-`run_id`.

**This repository**: 597 passed total (577 pre-existing + 20 new), `ruff check` clean:

- `tests/orchestration/test_model_species_catalog_orchestrator.py` (13 tests, harness client
  mocked via `monkeypatch`) -- a successful capture with full species/compartment detail; a
  boundary-species case; every defensive-failure path (missing `antimony_text`, missing output
  file, harness-client error, real load failure, a canonical species not surviving into the
  real model, a canonical species with no symbol-map entry at all, an unknown compartment
  reference, two species mapped to the identical real id); repeat-safety (a second call never
  re-invokes the harness); and one real, independent-session durability proof (a capture
  commits in one session and is read back, unchanged, from a brand-new session opened after
  the first is fully closed).
- `tests/persistence/test_model_species_catalog.py` (7 tests) -- `AVAILABLE`/`UNAVAILABLE`
  creation, the `None`-species-vs-`[]`-species rejection (task instruction: distinguish
  "never attempted" from "verified, genuinely empty"), `UNAVAILABLE` requiring a reason,
  repeat-safe reuse never overwriting an already-captured row.
- `tests/orchestration/test_end_to_end_persistence.py`'s own existing `real_run_id` fixture
  (a real, unmocked, whole-pipeline harness invocation) now also exercises this increment's
  entire capture path for real -- confirmed directly (§9) rather than only inferred from the
  mocked tests above. Fixing this test module's own cleanup helper (`_delete_recursively`,
  which deleted `run_record` rows before this increment's own `RESTRICT`-referencing
  `model_species_catalog` rows) was this increment's one genuine regression, caught and fixed
  by this same full-suite run -- not shipped unnoticed.

**A real, pre-existing-pattern bug was also found and fixed in this increment's own new
code**, before any of the above tests could pass: `ModelSpeciesCatalog.species`/`.compartments`
lacked `passive_deletes=True`, so a direct `session.delete(catalog)` made SQLAlchemy try to
`UPDATE` each child's own (`NOT NULL`) foreign key to `NULL` before deleting it, rather than
trusting the database's own `ON DELETE CASCADE` -- violating the `NOT NULL` constraint. Fixed
by adding `passive_deletes=True` to both relationships. (The identical latent pattern already
exists, unfixed, on `TimeSeriesDataset`'s own relationships -- never exercised there because no
existing test ever calls `session.delete()` on that table; left alone here as genuinely
unrelated schema work, per this task's own explicit exclusion.)

## 9. Real, end-to-end verification

Ran the real whole-model build described in §2 a second time, through the actual
`run_orchestrator.submit_subproject_run` entrypoint (not a lower-level pipeline call), against
`workbench_test` (confirmed disposable via `scripts/db_safety.py::require_disposable_database`
before any write; the real `workbench` database was never started, connected to, or referenced).
Confirmed directly, by reading the resulting row back:

- `catalog.status == AVAILABLE`, zero unresolved/unmapped species.
- All 4 species captured with the real Antimony ids (`s_S1_cyto`...`s_S4_cyto`), correct
  canonical traceability ids, correct compartment context (`compartment-1`/`cyto`), correct
  `kind=FLOATING`, `unit=None` (honest -- see §10).
- One compartment row (`compartment-1`/`cyto`/`L`), `species_count=4`.
- The real Antimony text durably retained on disk at
  `artifacts/models/<sha256>.antimony`, confirmed to actually exist and match its own recorded
  checksum.

`workbench_test` was reset to a clean baseline afterward; the scratch artifacts directory this
manual verification created was removed (not committed -- `artifacts/` is `.gitignore`d, per
the prior increment's own fix).

## 10. Limitations, stated plainly

- **Species units are always `None`.** Agent 2's own `SpeciesSpecification` carries no unit
  field at all (confirmed by inspection) -- there is nothing authoritative to capture. The
  `unit` column exists for forward-compatibility only; every row is honestly unknown today,
  never guessed.
- **Scoped to whole-model builds only.** A module-scoped simulation/calibration/validation run
  never triggers catalog capture -- `run_orchestrator.submit_subproject_run` is specifically the
  whole-pipeline entrypoint; every module-scoped orchestrator is a separate code path this
  increment does not touch.
- **No capture for a `Model` row created any other way.** Since `persist_model` is the sole
  creation function and is never called anywhere except in response to a real build (or by a
  test/script that does not go through `run_orchestrator` at all), any such row simply has no
  catalog -- `get_model_species_catalog` returns `None`, read identically to `UNAVAILABLE` by
  every caller. No backfill, no retroactive capture, no guessing is ever attempted for an
  existing model whose original harness output may no longer even exist -- exactly the task's
  own instruction ("allow capture only from surviving artifacts whose association with that
  exact model version can be verified. Otherwise disclose 'species catalog unavailable'").
- **A module's own, structurally different composition is never substituted.** This was a
  live, explicit design constraint throughout (§2), not an afterthought: a module's
  `ModuleExecutionSnapshot` is never read by this increment's own capture logic, under any
  circumstance.
- **No API or frontend surface yet.** This increment is the durable-data prerequisite only;
  docs/27 (model-specific alias mapping) is the first consumer that reads this catalog through
  an API route.

## 11. Final repository state

Both repositories are left **uncommitted**, per explicit instruction. `agent-integration-harness`
carries the new runner/orchestration-module/entrypoint/contract-types/test file described in
§7-8. `mechanistic-modeling-workbench` carries the migration, models, persistence, orchestration
(including the `run_orchestrator.py` wiring and its own updated module docstring),
`app.contracts.model_antimony_verification`, the generalized `app.storage.save_blob` (with
`save_dataset_workbook` refactored to call it, no behavior change), the new test files in §8,
and the one-line cleanup-ordering fix to `tests/orchestration/test_end_to_end_persistence.py`.
`agent2-antimony-builder` is untouched -- Agent 2 needed no changes at all for this increment.
