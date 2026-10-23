# 31. Joint Calibration Workflow — Configuration-Prerequisites Increment

> **This document's own §2.3 error/weighting gap, and the general migration-editing hazard
> §5 disclosed, are both resolved by
> `docs/32_calibration_configuration_close_out_increment.md`**: a real, structured minimal
> error/weighting contract (superseding `DECLARED_SIGMA`), and an audited, evidence-backed
> resolution of the §5 hazard (entirely local and unreleased; this increment's own new schema
> goes into a fresh, additive migration rather than a further in-place edit). This document is
> left otherwise unchanged as the historical record of what this specific increment shipped.

Completes the remaining whole-model calibration *configuration* prerequisites identified as
open gaps in `docs/30_joint_calibration_configuration_increment.md` §2/§6, before any execution
capability is attempted. Preserves the 3-screen workflow and the Agent4-owned, whole-model-only
architecture (`docs/29_joint_calibration_workflow_design.md`) unchanged. Execution remains
disabled, with the same named reason, for every job regardless of configuration completeness —
**this document is entirely about configuration completeness, never about execution
capability**, and nowhere does it narrow that distinction.

## 1. Three audit items, corrected

### 1.1 Differing experimental conditions must never block saving (docs/29 §5 rule 5)

**Before**: `INCOMPATIBLE_EXPERIMENTS_MERGED` (genuine condition/binding/mapping disagreement
between two experiments sharing an arm) was an `ERROR`-severity finding, which `complete_review`
rejects — meaning two experiments with differing conditions could never reach `REVIEWED`, even
though nothing about *saving* that configuration is actually unsupported; only *jointly
executing* them as if they were one trajectory is.

**Fixed**: downgraded to `WARNING` (`app/persistence/calibration.py`, `_compatibility_findings_
for_arm`), with a rewritten message explaining this is about today's narrow trajectory-sharing
shortcut, never a reason to block saving. The `len(conditions) > 1` ambiguous-dataset branch was
already `INFO` and is unchanged. Verified: `tests/persistence/test_calibration.py::TestFindings::
test_differing_conditions_are_a_warning_never_a_blocking_error` constructs exactly this
configuration and asserts `complete_review` succeeds with the finding still present (not
silenced, just non-blocking) — confirmed live in §4.

### 1.2 Immutable saved configuration revisions

**Before**: nothing captured a job's configuration at any point in time; "Complete review" only
flipped a status column. A later draft edit (docs/29 §5 rule: "any edit drops review back to
DRAFT") had nothing durable to compare itself against, and there was no way to answer "what did
this configuration look like when it was last reviewed?"

**Fixed**: new, insert-only `CalibrationJobRevision` (`app/models/calibration.py`) — one row per
successful `complete_review` call, holding a plain-dict JSON snapshot
(`_build_snapshot_payload`) of every arm/experiment/variable-binding/parameter-role and the
findings computed at that exact moment. `complete_review`'s own return signature grew from
`(job, findings)` to `(job, findings, revision)`; two new read-only routes
(`GET .../calibration-jobs/{id}/revisions`, `GET .../revisions/{revision_number}`). Verified:
`tests/persistence/test_calibration.py::TestJobRevisions::test_a_later_edit_never_changes_an_
earlier_captured_revision` and the independent-session
`tests/api/test_calibration_durability.py::TestJobRevisionsSurviveAnIndependentSession` both
create revision 1, make a further edit (dropping the job back to `DRAFT`), re-review (revision
2), and assert revision 1's own JSON is byte-identical before and after — confirmed live in §4
with a real two-revision job and its two independently viewable snapshots.

### 1.3 A newer alias-mapping revision must never invalidate a pin to an unchanged older one

Audited against the already-existing docs/30 mechanism and found **already structurally
correct, not a new gap**: `ExperimentItem.mapping_is_stale` (`app/schemas/calibration.py`) is
computed fresh on every read by comparing the experiment's own pinned revision number against
whatever is actually current for that `(dataset, model)` pair — it is `True` only when a pin
exists **and** a strictly newer revision now exists; an experiment that was never pinned reads
`mapping_is_stale=False` regardless of what the dataset's own mapping history looks like, and a
pin to the single, unchanged current revision never goes stale no matter how much time passes.
Adoption is always explicit — `set_experiment_mapping`/the "Re-pin to the current mapping"
button — never automatic, and dependent findings (`compute_findings`) are always recomputed
fresh from current state, never cached from pin time. No code change was required; this
increment adds the first direct test of the behavior
(`tests/persistence/test_calibration.py::TestArmsAndExperiments`, both auto-pin tests) and
confirms it live (§4's "stale-mapping re-pin" scenario).

## 2. Three new configuration capabilities, implemented

### 2.1 Authoritative whole-model parameter catalog (docs/30 §2 item 3, §6)

The gap docs/30 disclosed and left unresolved: no durable, real-model-derived parameter catalog
existed, so every `calibration_parameter_role.parameter_name` was curator-declared free text,
explicitly marked `catalog_validated: false` and never checked against anything real.

**Mechanism** (mirrors `ModelSpeciesCatalog` exactly, confirmed by direct harness inspection
before writing any code — never assumed):
- `rr.model.getGlobalParameterIds()`/`getGlobalParameterValues()` (already exercised by the
  existing Agent3 inspection step) enumerate every global parameter with no independent/derived
  distinction on their own.
- The derived/independent distinction is **not** available from roadrunner's own Python API
  (`rr.model.getAssignmentRuleIds()` is SWIG-broken from Python, confirmed by direct
  reproduction) — the reliable mechanism is `rr.getCurrentSBML()` → `libsbml.readSBMLFromString`
  → iterate `model.getRule(i)`, check `.isAssignment()`, read `.getVariable()`. `libsbml` is
  already an installed roadrunner dependency, so no new dependency was added.
- `agent-integration-harness`: `run_agent3_inspect_antimony_model.py` gained
  `_assignment_rule_derived_parameter_ids(rr)` (defensive, returns `[]` on any failure — a
  parameter-catalog anomaly never aborts the species-catalog half of the same build); both
  `global_parameter_ids` and `assignment_rule_derived_parameter_ids` now flow through
  `model_antimony_verification.py` → `WorkbenchModelAntimonyVerificationResult`
  (`workbench_contracts.py`, two new defaulted fields, both directions) →
  `run_workbench_model_antimony_verification_request.py`. New harness test:
  `test_an_independent_parameter_is_distinguished_from_an_assignment_rule_derived_one` — full
  harness suite re-run clean (**247 passed**, zero regressions) after this change.
- Workbench mirrors the same two fields onto `app.contracts.model_antimony_verification`.
- New domain, 1:1 with `Model` exactly like its sibling: `ModelParameterCatalog`/`ModelParameter`
  (`app/models/model_parameter_catalog.py`), `ModelParameterCatalogStatus`
  (`AVAILABLE`/`UNAVAILABLE`, deliberately its own enum type, never reusing
  `ModelSpeciesCatalogStatus`) and `ModelParameterKind` (`INDEPENDENT`/`DERIVED`)
  (`app/models/enums.py`). Persistence `app/persistence/model_parameter_catalog.py`
  (`persist_model_parameter_catalog`/`get_model_parameter_catalog`) is a line-for-line mirror of
  `persist_model_species_catalog` — atomic, repeat-safe, `AVAILABLE` with `parameters=[]` is a
  genuinely different claim from `UNAVAILABLE`, exactly like the species catalog's own
  `None`-vs-`[]` distinction.
- `app/orchestration/model_species_catalog_orchestrator.py` was rewritten to capture **both**
  catalogs from the same harness round trip — no second subprocess call. A species-specific
  anomaly never blocks parameter capture and vice versa (`_capture_species`/`_capture_parameters`
  are independent, each always ending in a committed row); the shared early-failure paths (file
  unreadable, harness invocation exception, `not result.load_succeeded`) mark both `UNAVAILABLE`
  with an identical, honest reason. `capture_model_species_catalog`'s own public signature is
  unchanged for backward compatibility with `run_orchestrator.py`.
- Agent2's own structural handoff already carries everything needed: `_parameter_dict`'s
  `parameter_id`/`unit`/`lower_bound`/`upper_bound`/`value` (decimal strings), and
  `antimony_symbol_map["parameters"]` mapping canonical id → real compiled Antimony symbol —
  confirmed by direct inspection of `agent2-antimony-builder`'s own pipeline before using it,
  never assumed to exist.
- **Server-side validation, wired into every place a parameter name is declared**
  (`app/persistence/calibration.py`, `_validate_target_against_catalogs`): checks the species
  catalog (if relevant to that binding's `model_meaning`) then the parameter catalog, in that
  order; raises on a confirmed-absent name or a confirmed-`DERIVED` parameter (never a legal
  independent target); returns `False` (curator-declared, unvalidated) only when **no** relevant
  catalog is `AVAILABLE` at all. `add_parameter_role` now sets
  `CalibrationParameterRole.catalog_validated` honestly from this check for every covering arm
  (and, for a link role, the reference arm too) — `True` only when validated `True` for every
  one of them, **never silently re-checked against a catalog captured later** (docs/29 §5 rule
  3's own "revalidation, never deletion" principle applied to catalog arrival, not just alias-
  mapping arrival).
- **Never infers a parameter from the species catalog or from names** — confirmed by
  construction: the only two catalogs a binding/role is ever checked against are the real
  species catalog and the real parameter catalog, selected by the binding's own declared
  `model_meaning`/role kind, never by string-matching a name against anything.

### 2.2 Independent-variable bindings (docs/30 §2 item 1, §6 "dose/arbitrary independent
variables are not yet capturable")

**Dataset-import side** (mirrors the existing measurement-column mechanism exactly, the two-tab
workbook contract's own stated precedent for adding a declared sub-table):
- `app/time_series/contract.py`: new `"## Independent variable definitions"` Metadata sub-table
  marker/header, same three-column shape (`column_name`/`unit`/`description`) as the existing
  measurement-column table.
- `app/time_series/parser.py`: `IndependentVariableColumnDefinition`; a Data-tab column named in
  this new sub-table is excluded from `measurement_column_headers` and instead becomes an
  `independent_variable_columns` entry, with its own `independent_variables` dict per row
  (identical `_classify_cell_value`/disclosure pattern as measurements, worded "independent
  variable column"). **Byte-identical to every prior import** when the new sub-table is absent
  — confirmed by the existing 33-test workbook suite passing unchanged, plus four new tests
  (`tests/unit/test_time_series_workbook.py::TestIndependentVariableColumns`) covering: no-
  declarations-unchanged, a declared column excluded from measurements, a real zero preserved
  and disclosed, and an orphan declaration disclosed.
- `app/models/time_series_dataset.py`: new `TimeSeriesIndependentVariableColumn` (CASCADE,
  mirrors `TimeSeriesMeasurementColumn` minus `declared_in_metadata` — a row here only exists
  *because* it was declared, there is no "undeclared independent variable" state); new
  `TimeSeriesDatasetRow.independent_variables` column, defaulted `'{}'` so every row saved
  before this increment reads back byte-identical to before. Persistence/schemas updated to
  match.

**Calibration side** — `CalibrationExperimentScenarioOverride` (docs/30's own name) renamed to
`CalibrationExperimentVariableBinding`, with a genuinely richer shape than "scenario override"
ever captured:
- `model_meaning`: `INITIAL_VALUE` / `PARAMETER_OVERRIDE` / `INTERVENTION` — explicit model
  meaning (docs/30's own `target_kind` conflated "initial condition" with "intervention"; this
  increment separates them, since a dose column binds as an intervention, not an initial value).
- `value_source`: `CONSTANT` (a single curator-typed value, `constant_value`/`constant_unit`) or
  `DATASET_COLUMN` (`source_column_name`, naming a real, declared independent-variable column of
  that experiment's own pinned dataset) — **preserves the original per-row data and units**,
  never collapsing a multi-row dose/time column to one constant.
- Server-side validation (`add_variable_binding`): `INITIAL_VALUE`/`INTERVENTION` check the
  species catalog, `PARAMETER_OVERRIDE`/`INTERVENTION` check the parameter catalog (the same
  `_validate_target_against_catalogs` helper §2.1 describes); `DATASET_COLUMN` additionally
  requires `source_column_name` to be a real entry in
  `experiment.time_series_dataset.independent_variable_columns`.
- `ExperimentItem.available_dataset_columns` (API) surfaces exactly which column names are
  legal for a `DATASET_COLUMN` binding on that experiment, read from the dataset's own declared
  columns — never guessed.

### 2.3 Error/weighting assumptions

Audited against docs/29 §1's own enumerated gap and docs/30 §6's disclosure
(`CalibrationObjectiveWeighting.DECLARED_SIGMA` backed only by free-text `weighting_notes`):
**no change was made here**. `TimeSeriesDatasetRow` still has no structured per-observation sigma
column, and building one is dataset-import-contract scope exactly like §2.2's own column
addition — but unlike dose/time (which this document's own task explicitly named as the
multi-condition case to implement), no structured per-observation uncertainty value exists
anywhere in this codebase's import pipeline to capture here, and fabricating a column format
with no real upstream source to populate it from would be exactly the kind of invention these
instructions forbid. The existing `UNWEIGHTED`/`DECLARED_SIGMA` distinction, with
`weighting_notes` honestly labeled as curator-declared free text and never a parsed value, is
reused unchanged. This gap is reconfirmed disclosed, not silently dropped (see §6).

## 3. The three screens — what changed, what did not

Screen 2's required inputs and Screen 3's summary-only nature are unchanged from docs/30 §3.
What actually changed on-screen:

- **Screen 2, "Initial conditions, interventions & experiment-specific settings"**: the
  override form is now a binding form — model-meaning select, component-id input, value-source
  select (constant vs. a dropdown of this experiment's own declared dataset columns), and the
  matching value inputs. The independent-variables disclosure above it now names the real
  declared columns on this dataset (previously: "not yet capturable").
- **Screen 2, "Parameter roles"**: a new "Catalog" column shows `validated` vs.
  `curator-declared` per role, and the section's own subtitle explains the real validation rule
  instead of docs/30's "never validated" disclosure.
- **Screen 3, "Review & readiness"**: a new "Revisions" panel lists every captured revision
  (number, arm/finding counts, captured-at) with a "View snapshot" action per revision — purely
  additive, no change to the existing findings/execution-capability sections.

## 4. Live-browser verification

Against the real Vite dev server + FastAPI backend, on the confirmed-disposable `workbench_test`
database (reset to a clean migrated baseline both before and after this verification). Seeded by
a standalone script that runs the **real orchestrator** (`run_orchestrator.submit_subproject_run`)
against the harness's own synthetic Agent1–5 fixture — a genuine compiled Antimony model, never
a fabricated catalog — and a real multi-condition dose/time dataset (two conditions,
`low_dose`/`high_dose`, each its own time course, with a declared `dose_uM` independent-variable
column). All scenarios ran via Playwright driving a real Chrome instance and **all passed**:

- **Catalog capture against the real compiled model**: the orchestrator run produced
  `species catalog status: AVAILABLE` (4 real species, e.g. `s_S1_cyto`) and
  `parameter catalog status: AVAILABLE` (3 real independent parameters, e.g. `p_k_S1_to_S2`) —
  confirmed by direct query against the durable rows after the harness subprocess exited and the
  session closed, never read from in-memory state.
- **Auto-pin at experiment creation**: with a mapping revision already current for
  `(dataset, model)`, adding the experiment auto-pinned it immediately (`"Auto-pinned to
  revision 1 at experiment creation? True"`).
- **Stale-mapping detection and explicit re-pin (audit item 3)**: saving a genuinely newer
  mapping revision for the same `(dataset, model)` pair, without touching the pinned experiment,
  made the UI show "a newer revision now exists" (`"Mapping shown stale before re-pin? True"`);
  clicking "Re-pin to the current mapping" resolved it (`"Mapping shown stale after re-pin?
  False"`) — the experiment row itself, and every other unrelated choice in the job, left
  exactly in place.
- **A real `DATASET_COLUMN` intervention binding**: `model_meaning=INTERVENTION`,
  `target_component_id=s_S1_cyto` (a real species), `value_source=DATASET_COLUMN`,
  `source_column_name=dose_uM` — rendered correctly in the bindings table
  (`"column: dose_uM"`) and round-tripped byte-identical through the immutable revision snapshot
  (§ below).
- **A catalog-validated parameter role**: `p_k_S1_to_S2` (a real, `INDEPENDENT` parameter)
  declared `MODEL_SPECIFIC` showed `catalog_validated: true` both in the live table and in the
  captured revision's own JSON.
- **Differing conditions never block saving, and are a warning, never an error**: the
  multi-condition dataset's own `INFO`-level condition-count disclosure reached `REVIEWED` with
  zero `ERROR` findings; the `INCOMPATIBLE_EXPERIMENTS_MERGED` downgrade is exercised directly
  by `tests/persistence/test_calibration.py::test_differing_conditions_are_a_warning_never_a_
  blocking_error`, asserting both the `WARNING` severity and that `complete_review` still
  succeeds with that finding present.
- **Revision immutability across two successive reviews**: "Complete review" captured Revision
  1 (one parameter role, the `DATASET_COLUMN` binding present in its snapshot). A further edit
  on Screen 2 (a second parameter role, `p_k_S2_to_S3`, also real and `INDEPENDENT`) dropped the
  job back to `DRAFT`; "Complete review" again captured Revision 2 (two parameter roles).
  Re-opening Revision 1's own "View snapshot" **after** Revision 2 existed showed exactly one
  parameter role, `source_column_name: "dose_uM"` unchanged, and every field byte-identical to
  the first time it was viewed — confirmed both by the script's own JSON-equality assertion and
  by visual inspection of the rendered page (both revisions listed, newest first, each
  independently viewable).

Every HTTP request this verification made returned 200/201 (confirmed from the backend's own
access log, read directly, not inferred from the browser). One console 404 was observed and
traced to the dev server requesting a favicon that does not exist — unrelated to any API call,
confirmed by the backend log containing zero 404 responses for the entire session.

The dev servers used for this verification were stopped afterward, and `workbench_test` was
reset to a clean migrated baseline (dropped and recreated, then re-migrated) both before this
verification began and after it finished — unlike docs/30, which left its own seeded state in
place; this increment's own seeding script runs a real harness subprocess each time and is cheap
to re-run, so leaving stale state behind had no offsetting benefit. The development database
(`workbench`) was never pointed to by `DATABASE_URL` at any point in this increment and remains
at its original `0001_initial_workbench_schema` baseline, confirmed by direct query before and
after every migration operation in this increment.

## 5. A migration-safety note for this increment specifically

`migrations/versions/0019_calibration_configuration.py` (docs/30's own migration) was edited
**in place** to its final, correct shape for this increment — renamed enum, new enum, renamed
table with new columns, a new `catalog_validated` column, a new `calibration_job_revision`
table — rather than layered as a separate rename/alter migration, because 0019 had never been
committed or pushed anywhere in this line of uncommitted work. This is **not** a general
license to edit migrations: 0019 had, however, already been *applied* to `workbench_test` in an
earlier session, and alembic identifies a migration by its revision id string, not its file
content — editing an already-applied revision's file in place leaves the database holding the
old schema while `alembic_version` claims the new revision id is current, a silent, dangerous
mismatch. This was caught during this increment (`workbench_test` still had the old
`calibration_experiment_scenario_override` table despite `alembic_version` reading
`0020_calibration_prerequisites`) and resolved the only safe way for a disposable test database:
dropping and recreating `workbench_test` entirely, then re-running every migration from scratch.
Migrations 0001–0018 (the already-shipped baseline) were never touched; the new independent-
variable-column and parameter-catalog tables went into a new, purely additive migration
(`0020_calibration_prerequisites.py`) precisely because that baseline is off-limits.

## 6. Remaining limitations, disclosed rather than papered over

- **No execution capability** — unchanged from docs/30 §6; `request_model_calibration` still
  does not exist, and nothing in this increment moves that line.
- **No per-observation declared-error (sigma) capture** (§2.3) — `TimeSeriesDatasetRow` has no
  sigma column; `DECLARED_SIGMA` is still backed by curator-declared free text, honestly
  labeled. Unlike dose/time, no real upstream source to populate a structured value from exists
  yet in this codebase's import pipeline.
- **The compatibility check's condition comparison is still an approximation** (docs/30 §6,
  unchanged) — a per-dataset `condition_id` set comparison, not a per-observation one; this
  increment's own severity downgrade (§1.1) makes that approximation's own consequence strictly
  less severe (a warning, never a block) but does not make the comparison itself any finer-
  grained.
- **`ModelRelationship`/cross-arm parameter-role linking were not touched** — this increment's
  entire scope is single-arm configuration completeness (catalogs, bindings, revisions); nothing
  about docs/30's own multi-arm linking semantics changed.
- **The new "Independent variable definitions" Metadata sub-table has no dedicated template-
  generation test beyond round-trip parsing** — `app/time_series/template.py`'s own generated
  workbook was verified by loading it back through `declare_independent_variables` in every new
  test, but no separate "the generated template literally contains this sub-table's header row"
  assertion was added, mirroring the existing measurement-column section's own test coverage
  shape (which also relies on round-trip, not template-byte inspection).

## 7. Scope discipline

Migrations, models, schemas, and routes are limited to the configuration entities this document
and docs/29/30 describe. The harness-side change (`agent-integration-harness`) is the narrowly-
required extension to surface a derived/independent distinction already latent in a real
compiled model's own SBML, confirmed necessary by direct inspection before writing it, and its
own full test suite was re-run clean (247 passed) after the change. No simulation or
optimization code was written anywhere. No Figma file was touched. The development database
(`workbench`) was never altered. Nothing in this increment, or in `agent-integration-harness`,
was committed or pushed.
