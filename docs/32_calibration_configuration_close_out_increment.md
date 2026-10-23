# 32. Calibration Configuration Close-Out Increment

Closes the two remaining configuration gaps `docs/31_joint_calibration_configuration
_prerequisites_increment.md` §2.3/§6 disclosed rather than closed: a real uncertainty/
weighting contract (previously `UNWEIGHTED`/`DECLARED_SIGMA`, the latter backed only by
curator-declared free text with nothing to validate it against), and a migration-compatibility
audit of the in-place edit that same document's own §5 flagged as a general hazard. Preserves
the 3-screen workflow and the Agent4-owned, whole-model-only architecture
(`docs/29_joint_calibration_workflow_design.md`) unchanged. Execution remains disabled, with
the same named reason, regardless of how thoroughly uncertainty/weighting is now configured —
**this document is entirely about configuration completeness, never about execution
capability, and nowhere does it narrow that distinction.** No simulation or optimization code
was added anywhere in this increment.

## 1. The minimal error/weighting contract

### 1.1 The intended joint objective this configures

Grounded in the ordinary weighted-least-squares objective a future execution capability would
need, never implemented here:

```
objective = sum over CALIBRATION-role experiments e, outputs o, observations i of
    relative_output_weight(e, o) * uncertainty_scaling(e, o, i) * (model(t_i) - data(e, o, i))^2
```

where `uncertainty_scaling` is `1` under `UNWEIGHTED` or `1 / sigma(e, o, i)**2` under
`INVERSE_VARIANCE`, and `sigma` is read from whichever `uncertainty_source` that output
declares. `HELD_OUT_VALIDATION`-role experiments are never part of this sum at all (docs/29's
existing role distinction) and their own weighting declarations are correspondingly excluded
from every finding this increment adds (`app.persistence.calibration
._uncertainty_weighting_findings`, scoped to `CalibrationExperimentRole.CALIBRATION` only).

Two deliberately independent knobs, stated explicitly rather than folded into one:

- **`CalibrationObjectiveWeighting`** (per experiment) — `UNWEIGHTED` (ordinary least squares,
  a real named policy, never a silent default) or `INVERSE_VARIANCE` (residuals scaled by
  `1/sigma**2`, using each output's own declared source). Supersedes the first revision's
  `DECLARED_SIGMA` (free-text-only, nothing to validate).
- **`CalibrationExperimentOutputWeighting`** (per experiment × output/measurement-column) — an
  explicit `uncertainty_source` (`MEASURED` / `USER_ASSUMED` / `UNKNOWN`), the uncertainty
  value itself when applicable, and a `relative_output_weight` (default `1`) that is an
  independent, curator-chosen importance multiplier, never a proxy for uncertainty.

### 1.2 Distinguishing measured, assumed, unknown, and the weighting policy

`CalibrationUncertaintySource` (`app/models/enums.py`) is a real, three-valued, explicitly
disclosed state, never a boolean:

- **`MEASURED`** — a real, already-computed, per-row value read from the experiment's own
  pinned dataset at execution time (never copied in here — see §1.3). Legal only when that
  dataset actually declares a `TimeSeriesMeasurementUncertaintyColumn` for this exact output;
  `app.persistence.calibration.set_experiment_output_weighting` raises `ValueError` otherwise,
  confirmed against the real, already-persisted dataset, never assumed.
- **`USER_ASSUMED`** — a single curator-typed constant (`assumed_sigma_value`/
  `assumed_sigma_unit`) applied to every observation of this output in this experiment. Task
  instructions: "do not invent sigma, or silently infer it from replicates" — there is no code
  path anywhere in this increment that derives a sigma value from replicate spread or any other
  computation; it is either read from the workbook's own declared column (`MEASURED`) or typed
  by a human (`USER_ASSUMED`), with no third, inferred source.
- **`UNKNOWN`** — no uncertainty information exists for this output, stated explicitly rather
  than left blank or defaulted. Never silently treated as if uncertainty were known: choosing
  `INVERSE_VARIANCE` while any covered output stays `UNKNOWN` is a blocking review finding
  (§1.5), and an `UNWEIGHTED` experiment with a *known* source on some output is disclosed as a
  non-blocking warning (§1.5) specifically so an unweighted fit is never mistaken for one that
  already accounts for known measurement uncertainty (task instructions, this exact phrase).

### 1.3 Observation-level uncertainty, supplied through the two-tab workbook

A new, wholly optional Metadata-tab sub-table, "Measurement uncertainty definitions"
(`app.time_series.contract.MEASUREMENT_UNCERTAINTY_COLUMNS_SECTION_MARKER`), mirrors the
existing "Independent variable definitions" sub-table's own mechanism exactly: one row per
declaration, `(uncertainty_column_name, measurement_column_name, statistic_kind, unit,
description)`. A Data-tab column named in this sub-table is excluded from ordinary
measurement-column processing (identically to an independent-variable column) and its own
**per-row** values are captured into `DataRow.measurement_uncertainty`, **keyed by the
measurement column it describes**, never by its own column name — so persistence and the API
never need to know which Data-tab column actually carried the value, and every uncertainty
value is identified by the exact same `(row, measurement column)` pair the measurement itself
is (same row index, same `sample_id`/`condition_id`/`time`, since it is a column on that
identical `TimeSeriesDatasetRow`) — never a single value declared once "for the column as a
whole" unless a scientist genuinely intends that, which is exactly what the separate,
explicitly-named `USER_ASSUMED` output-level path (§1.4) is for, never this one.

`statistic_kind` is **required** -- a declaration whose own statistic cell is blank or
unrecognized never becomes a usable column at all (`MEASUREMENT_UNCERTAINTY_COLUMN_STATISTIC_
KIND_UNRECOGNIZED`, disclosed, non-blocking): a standard deviation, a variance, and a standard
error are three materially different numbers for the identical underlying spread
(`variance = sd**2`; `standard_error = sd / sqrt(n)`), and nothing in this contract ever
guesses which one a column is (task instructions: "distinguish standard deviation from
variance or standard error rather than treating them interchangeably"). Recognized tokens
(case-insensitive): `SD`/`std`/`stdev`/`standard deviation`, `variance`/`var`,
`SE`/`SEM`/`standard error`/`standard error of the mean`
(`app.time_series.contract.UNCERTAINTY_STATISTIC_KIND_TOKENS`). No conversion between the
three is ever performed anywhere in this codebase -- converting a standard error into the
standard deviation an inverse-variance weight is actually defined in terms of would need a
sample size this contract does not capture, and fabricating one would violate the same "never
invent" discipline the rest of this contract is built on; see §6 for this disclosed limitation.

Validated, never silently dropped or misapplied:

- A target naming a column that is not actually a real measurement column of this workbook ->
  `MEASUREMENT_UNCERTAINTY_COLUMN_TARGET_NOT_FOUND` (non-blocking, disclosed).
- Two uncertainty columns naming the same target -> the first declared wins, the second is
  `DUPLICATE_MEASUREMENT_UNCERTAINTY_TARGET` (disclosed, never silently summed/averaged/
  overwritten).
- A column declared both an independent variable and an uncertainty column ->
  `COLUMN_DECLARED_BOTH_INDEPENDENT_VARIABLE_AND_UNCERTAINTY`, independent-variable wins
  (declared first, docs/31), disclosed.
- A negative uncertainty cell -> preserved exactly as reported (never flipped or discarded) and
  disclosed via `NEGATIVE_UNCERTAINTY_VALUE` — a workbook can contain a scientist's own honest
  mistake; this increment reports it, never silently "fixes" it. (A zero, negative, or missing
  value, for an observation that *does* have a real measurement, additionally becomes a
  **blocking** finding the moment that output is actually declared `MEASURED` under
  `INVERSE_VARIANCE` — see §1.5's own `MEASURED_UNCERTAINTY_NOT_STRICTLY_POSITIVE`; the
  workbook-level disclosure here is non-blocking because importing/saving a dataset must never
  depend on how it will later be used for calibration.)
- A cell whose text is literally `"inf"`/`"-inf"`/`"nan"`/`"infinity"` (Python's own `float()`
  parses every one of those without error) -> classified `UNRECOGNIZED`, never `MEASURED` --
  fixed at the single shared root, `app.time_series.parser._classify_cell_value` (via
  `math.isfinite`), so no non-finite value can ever enter *any* measurement, independent-
  variable, or uncertainty cell (task instructions: "requires ... finite uncertainty values").
- A declared sub-table absent entirely -> every workbook parses byte-identical to before this
  increment existed (the identical "purely additive" discipline every prior sub-table in this
  contract already establishes) — confirmed by
  `tests/unit/test_time_series_workbook.py::TestMeasurementUncertaintyColumns
  ::test_a_workbook_with_no_uncertainty_declarations_is_unchanged`.

New durable storage mirrors the existing independent-variable-column precedent exactly:
`TimeSeriesMeasurementUncertaintyColumn` (sibling of `TimeSeriesIndependentVariableColumn`,
plus a required `statistic_kind` column) and `TimeSeriesDatasetRow.measurement_uncertainty`
(sibling of `.independent_variables`, same `'{}'`-default-for-every-prior-row discipline).

### 1.4 Output-level configuration, and validation

`set_experiment_output_weighting` (`app.persistence.calibration`) is an upsert on
`(calibration_experiment_id, output_column_name)` — one declared setting per output, never a
growing, orphan-and-replace list. Validated, every rejection a real `ValueError` surfaced as a
422, never a silent clamp:

- **Applicability** — `output_column_name` must be a real `TimeSeriesMeasurementColumn` of the
  experiment's own pinned dataset; an unreal name is rejected outright.
- **Conflicting sources** — `MEASURED`/`UNKNOWN` may never also carry an
  `assumed_sigma_value`/`assumed_sigma_unit`/`assumed_sigma_statistic_kind` (an instruction
  that says "use the measured per-row values" while also supplying a constant override is
  ambiguous, never silently resolved in either direction); `USER_ASSUMED` requires a value and
  a statistic kind.
- **Values** — `assumed_sigma_value` and `relative_output_weight` must each be **strictly
  positive and finite** -- checked by one shared guard, `_require_finite_positive`, which
  tests `.is_finite()` *before* any ordering comparison. This matters because `Decimal` happily
  parses the literal strings `"Infinity"`/`"NaN"` with no error: an ordinary `<= 0` check alone
  would let `Decimal("Infinity")` straight through (`Infinity > 0` is `True`, so a naive
  positivity-only check would have silently accepted it, even though `1/Infinity**2 = 0`,
  silently zeroing out that very observation's own contribution to the objective) and would
  itself raise an unrelated, unhandled `decimal.InvalidOperation` on `Decimal("NaN") <= 0`
  (comparisons involving `NaN` are undefined and Python's `decimal` module raises rather than
  returning `False`) -- a 500, not a disclosed 422. Checking finiteness first, in one place,
  before any comparison, avoids both failure modes for both fields at once (task instructions:
  "requires strictly positive, finite uncertainty values; zero must not produce infinite
  weight"). Down-weighting an output to zero/negative is never expressed through
  `relative_output_weight` either way — remove the row, or change the experiment's own
  `CalibrationExperimentRole`, instead.
- **Statistic kind** — `USER_ASSUMED` requires `assumed_sigma_statistic_kind` (standard
  deviation / variance / standard error); never left implicit, mirroring §1.3's identical
  workbook-level requirement.
- **Units** — when both `assumed_sigma_unit` and the output's own declared measurement unit
  are present, they are checked for dimensional compatibility via the existing
  `app.units.compare_units` (the same utility `EXACT_AFFINE_LINK` unit checking already uses);
  a genuinely incompatible pair (e.g. assuming a time-unit sigma for a concentration output) is
  rejected, never silently accepted.
- **Provenance** — an optional `provenance_note` (e.g. "CV% from the core facility's own assay
  validation," "assumed 10% from literature") is recorded verbatim, disclosed, never parsed or
  validated as a number — exactly the same "curator-declared text, never fabricated as a parsed
  value" discipline the first revision's own `weighting_notes` already established, now at the
  correct per-output granularity in addition to the experiment-level general notes field
  (`weighting_notes`, unchanged, retained for overall context that is not output-specific).

For display, `OutputWeightingItem.effective_statistic_kind` resolves which statistic an
output's own uncertainty actually is regardless of source — mirroring
`assumed_sigma_statistic_kind` for `USER_ASSUMED`, looked up from the dataset's own declared
`TimeSeriesMeasurementUncertaintyColumn.statistic_kind` for `MEASURED` (never duplicated onto
the weighting row itself, so a dataset's own declaration stays the single source of truth),
`None` for `UNKNOWN`.

### 1.5 Interaction and double-weighting disclosure

`relative_output_weight` (curator-chosen importance) and uncertainty-based scaling
(`1/sigma**2` under `INVERSE_VARIANCE`) are deliberately independent factors that **multiply**
(§1.1's own formula) — never conflated into one number, and never silently combined without
disclosure. Three new review findings
(`app.persistence.calibration._uncertainty_weighting_findings`, exercised by
`tests/persistence/test_calibration.py::TestUncertaintyWeightingFindings`):

- **`INVERSE_VARIANCE_WEIGHTING_REQUIRES_KNOWN_UNCERTAINTY`** (`ERROR`, blocks
  `complete_review`) — an `INVERSE_VARIANCE` experiment with any covered output still `UNKNOWN`.
- **`OUTPUT_WEIGHT_AND_UNCERTAINTY_SCALING_BOTH_APPLY`** (`INFO`) — an output combines a
  non-default `relative_output_weight` with `INVERSE_VARIANCE` scaling from a *known* source:
  both legitimately apply and multiply; this is the direct answer to "specify how dataset/
  output weights and uncertainty scaling interact; prevent accidental double-weighting" (task
  instructions) — disclosure, not a block, since deliberately combining both is a real, valid
  choice.
- **`UNWEIGHTED_POLICY_IGNORES_DECLARED_UNCERTAINTY`** (`WARNING`) — an output has a declared,
  known uncertainty source, but the experiment's own policy is `UNWEIGHTED`, so it is never
  actually used — the direct answer to "do not ... equate an unweighted fit with known
  measurement uncertainty" (task instructions, same phrase as §1.2).
- **`MEASURED_UNCERTAINTY_NOT_STRICTLY_POSITIVE`** (`ERROR`, blocks `complete_review`) — a
  `MEASURED` output under `INVERSE_VARIANCE` has at least one observation (a dataset row whose
  own *measurement* is present) whose paired uncertainty value is zero, negative, or itself
  absent. `set_experiment_output_weighting` can only validate at the *metadata* level (does
  the dataset declare an uncertainty column at all) when a `MEASURED` source is chosen — the
  real per-row values live in the dataset's own immutable rows and are read directly, by
  `_measured_uncertainty_nonpositive_row_count`, at every review. This is the direct, workbook-
  sourced counterpart to §1.4's own `USER_ASSUMED`-time check: "zero must not produce infinite
  weight" (task instructions) applies identically regardless of which of the two sources a
  zero would otherwise have slipped through from.

Configuration-completeness findings (this section) and execution capability remain the
identical, wholly separate check docs/29 §5 rule 5 already establishes:
`execution_capability()` still unconditionally returns `available=False` with the named
`WHOLE_MODEL_EXECUTION` reason, regardless of how an experiment's weighting resolves — an
`INVERSE_VARIANCE` job that reaches `REVIEWED` with zero `ERROR` findings is still not
executable, and nothing in this increment narrows that disclosure.

### 1.6 Backward compatibility

Every existing workbook (no "Measurement uncertainty definitions" sub-table) parses and
persists byte-identical to before (§1.3). Every existing `CalibrationExperiment` row
(`objective_weighting=UNWEIGHTED`, no `CalibrationExperimentOutputWeighting` rows) reads back
unchanged: absence is read identically to an explicit `UNKNOWN` source with
`relative_output_weight=1`, never a reason a row "cannot exist" (task instructions' own
recurring theme, reapplied here). The superseded `DECLARED_SIGMA` enum label is never produced
by this codebase again but is intentionally left defined in the database's own Postgres enum
type (§2) rather than removed.

## 2. Migration compatibility

### 2.1 Audit of the `0019_calibration_configuration.py` in-place edit docs/31 §5 flagged

docs/31 §5 disclosed, as a general hazard, that `0019_calibration_configuration.py` had been
edited in place after already being *applied* to `workbench_test` in an earlier session —
caught only because `alembic_version` claimed a schema the database did not actually have, and
resolved then by dropping and recreating that one disposable database. This increment's own
task explicitly asks for that incident's resolution to be audited, not re-asserted.

**Evidence gathered this increment**:

- `git log --all --oneline -- migrations/versions/0019_calibration_configuration.py` (and the
  identical check against `0020_calibration_prerequisites.py`) returns **nothing** — neither
  file has ever been committed, on any branch, in this repository. `git status` confirms both
  are still untracked (`??`). Neither was ever pushed, shared, or merged; both exist only in
  this uncommitted working tree.
- The one database either file was ever *applied* to, `workbench_test`, is the project's own
  confirmed-disposable test database (never the subject of this task's "do not reset the dev
  database" instruction), and has since been dropped and recreated to a clean, fully-migrated
  baseline multiple times across both docs/31's own session and this one.
- The development database (`workbench`) was queried directly, by this increment, before and
  after every migration operation performed; its `alembic_version` reads
  `0001_initial_workbench_schema` throughout this entire increment, confirming it was never
  pointed to by any migration command and never advanced past the pre-existing baseline.

**Conclusion**: entirely local and unreleased, by every available measure (never committed,
never shared, and the one database it ever touched has already been fully reset past that
state). No historical definition needs restoring and no corrective migration is required for
`0019`/`0020` themselves — there is no "historical, shared definition" to restore *to*.

**Resolution adopted for this increment specifically, going forward**: rather than edit `0019`
or `0020` in place a third time (which would repeat the exact risk just audited, even though
each edit so far has individually been judged "safe" by the identical "never committed"
reasoning), every new table/column/enum value this increment needs goes into a new, purely
additive migration, `0021_calibration_uncertainty.py`. This is the more conservative, more
easily-verified choice: it makes "what changed in this increment" independently diffable
without re-reading `0019`/`0020` for changes, and it means the upgrade-compatibility testing in
§2.2 below exercises a *real* multi-migration upgrade path (`0018` -> `0019` -> `0020` ->
`0021`) exactly as a reviewer merging this work later would experience it, rather than a
fresh-looking `0019` that quietly contains three increments' worth of accumulated edits.

**A follow-up note on `0021` itself**: during the pre-commit correctness review (§1.3/§1.4's
`statistic_kind` and finite-value additions), `0021_calibration_uncertainty.py` was itself
edited in place to add the new enum and the two new columns, rather than layered into a
further `0022`. This is consistent with, not an exception to, the discipline above:
`0021` is itself still entirely uncommitted (confirmed the same way as `0019`/`0020`, via
`git log --all`) and had, at the time of that edit, only ever been applied to this
increment's own disposable `workbench_test`/verification databases, each dropped and
recreated before and after. The distinction this document's §2.1 draws is never "a migration
may be edited in place because no one would notice" — it is "a migration may be edited in
place only while it remains genuinely unreleased, and only by first confirming that with
evidence, every time," which was done again here before editing.

One consequence of "additive only": `CalibrationObjectiveWeighting`'s Postgres enum type
(`calibration_objective_weighting`, created in `0019`) cannot have its `DECLARED_SIGMA` label
safely removed by an additive migration — Postgres has no `ALTER TYPE ... DROP VALUE`, and
recreating the type would not be additive. `0021` instead does
`ALTER TYPE calibration_objective_weighting ADD VALUE IF NOT EXISTS 'INVERSE_VARIANCE'` (the
one safe way to extend a Postgres enum, verified not to require being outside a transaction on
the Postgres 18 server this project runs against) and leaves `DECLARED_SIGMA` physically
defined but permanently unused — disclosed in both the migration's own docstring and
`CalibrationObjectiveWeighting`'s own docstring, never silently hidden.

### 2.2 Upgrade-compatibility testing performed

Per this increment's own explicit instruction, **recreating `workbench_test` is not treated as
proof of upgrade compatibility** — `workbench_test` was used only for the ordinary test suite
and live-browser verification (§3), never cited as migration evidence. Two separate,
purpose-built, confirmed-disposable databases were created, used once, and dropped:

- **`workbench_fresh_install_test`** — `alembic upgrade head` against a genuinely empty
  database. Ran cleanly through all 21 migrations in order (`0001` through
  `0021_calibration_uncertainty`); confirmed afterward by direct query: `alembic_version` reads
  `0021_calibration_uncertainty`, `calibration_objective_weighting` contains both `UNWEIGHTED`
  and `INVERSE_VARIANCE`, both new tables exist.
- **`workbench_migration_upgrade_test`** — the actual "upgrade from the preceding supported
  schema with representative existing records" test. `alembic upgrade
  0018_dataset_model_alias_mapping` first (the schema immediately preceding this whole
  calibration body of work); a real `Project`/`Subproject`/`Model` and a real
  `TimeSeriesDataset`/`TimeSeriesMeasurementColumn`/three `TimeSeriesDatasetRow` rows were
  inserted directly against that exact pre-calibration schema (raw SQL matching the literal
  0018-era column set — deliberately not through today's ORM models, which already assume
  columns that do not exist at that revision); then `alembic upgrade head` (`0019` -> `0020` ->
  `0021`) on top of that real data. All 15 checks passed:
  - every pre-existing `project`/`subproject`/`model` row's own title/name survived unchanged;
  - the pre-existing dataset's row count and its `measurements` JSON were byte-identical before
    and after the upgrade;
  - the two new, additive `time_series_dataset_row` columns (`independent_variables`,
    `measurement_uncertainty`) both defaulted to `'{}'` for every pre-existing row;
  - both new tables exist, and `calibration_objective_weighting` gained `INVERSE_VARIANCE`
    while keeping `UNWEIGHTED`;
  - both new tables' foreign keys reject a reference to a nonexistent parent row, and
    `time_series_measurement_uncertainty_column`'s own unique constraint rejects a duplicate
    `(dataset_id, column_name)` — constraints actually enforced, not merely declared.

  One real defect surfaced by this exercise, fixed before it could reach any database:
  `0021`'s first-drafted revision id, `0021_calibration_uncertainty_weighting`, is 38
  characters — alembic's own `alembic_version.version_num` column is `VARCHAR(32)`, so the
  upgrade failed with a `StringDataRightTruncation` error on the final version-bump `UPDATE`.
  Because that `UPDATE` runs inside the same single transaction as every migration before it in
  one `alembic upgrade` invocation, the failure rolled the *entire* multi-migration upgrade back
  cleanly (confirmed: the target database was left with zero tables, not a half-applied
  schema) — a genuinely safe failure mode, but only by luck of transactional DDL, not by design.
  The revision id was shortened to `0021_calibration_uncertainty` (29 characters) and the
  upgrade re-run successfully. This 32-character ceiling is otherwise undocumented anywhere in
  this repository's own migration tooling and is worth a reviewer's attention on any future
  migration with a long, descriptive slug.

Both verification databases were dropped immediately after use. `workbench_test` was reset to a
clean, fully-migrated baseline both before and after this increment's own live-browser
verification (§3), and the development database (`workbench`) was never pointed to by
`DATABASE_URL` at any point in this increment, confirmed by direct query before and after every
migration operation (§2.1).

**Re-run after the pre-commit `statistic_kind`/finite-value additions to `0021`** (§2.1's own
follow-up note), on two freshly recreated disposable databases: the fresh-install path again
applied all 21 migrations cleanly; the upgrade-from-0018-with-data path again inserted real
pre-existing `Project`/`Subproject`/`Model`/`TimeSeriesDataset` rows directly against the
literal 0018-era schema, then upgraded to head. All 8 checks passed, including two new ones
specific to this round's own additions: `uncertainty_statistic_kind` gained all three values
and the dataset-level `statistic_kind` column's `NOT NULL` constraint is actually enforced (a
direct `INSERT` omitting it was rejected) — not merely declared in the migration and trusted.
Both databases were dropped immediately after.

## 3. Live-browser verification

Against the real Vite dev server + FastAPI backend, on `workbench_test` (reset to a clean
migrated baseline both before and after). Seeded by a standalone script that runs the **real
orchestrator** (`run_orchestrator.submit_subproject_run`) against the harness's own synthetic
Agent1–5 fixture — a genuinely compiled Antimony model (`species catalog status: AVAILABLE`,
e.g. `s_S1_cyto`) — plus a dataset with a real, declared "Measurement uncertainty definitions"
sub-table (`[response]__sd` describing `[response]`, both with unit `AU`). Driven by Playwright
against a real Chrome instance; every scenario below passed:

- **The blocking finding fires correctly**: with the experiment's own objective weighting set
  to `INVERSE_VARIANCE` and no output weighting declared yet, Screen 3 showed
  `INVERSE_VARIANCE_WEIGHTING_REQUIRES_KNOWN_UNCERTAINTY` and "Complete review" was not yet
  attempted (the finding is `ERROR`-severity, confirmed by the API layer's own existing
  behavior of rejecting `complete_review` while any `ERROR` finding exists).
- **Declaring `MEASURED` clears it**: selecting output `[response]`, uncertainty source
  `MEASURED` (only enabled in the UI because this dataset's own `outputs_with_measured
  _uncertainty` actually lists it), and "Save output weighting" made the blocking finding
  disappear from Screen 3 on the very next load — confirmed both by the rendered page text and
  by the backend's own access log (`PUT .../output-weightings` -> `200`, zero `404`/`422`
  anywhere in the session's log once the real fix in §4 was in place).
- **"Complete review" succeeds and captures the output weighting**: Revision 1's own snapshot
  JSON (rendered via "View snapshot") contains `"output_weightings"` with
  `"uncertainty_source": "MEASURED"` for `[response]`.
- **Revision immutability extends to output weighting**: a further edit (a second parameter
  role) dropped the job back to `DRAFT`; a second "Complete review" captured Revision 2.
  Revision 1's own `output_weightings` block, re-read after Revision 2 existed, was
  byte-identical to the first time it was viewed.
- **Reopening from scratch**: navigating away to the calibration-jobs list and back in (a
  brand-new page load, not a cached client-side state) showed the declared `MEASURED` output
  weighting exactly as saved.

Screen 2 renders a new "Per-output uncertainty & relative weight" section (declared-weightings
table plus an add/update form) directly beneath "Objective weighting / error assumption",
matching this document's own §1 design; Screen 3's existing per-experiment summary line gained
one sub-bullet per declared output weighting (e.g. `[response]: MEASURED`) — purely additive,
no change to the existing findings/execution-capability sections' own shape.

**Disclosed scope of this live-browser pass**: the walkthrough above predates the pre-commit
correctness review's own additions (§1.3's required `statistic_kind`, §1.4's finite/positive
guard, §1.5's `MEASURED_UNCERTAINTY_NOT_STRICTLY_POSITIVE`), and was not re-run through an
actual browser for those additions, because the session this increment's work was continued
in started fresh without the first session's own seeded data or Playwright scripts available
to reuse. Those additions *were*, however, verified against the real FastAPI server (a plain
`httpx.Client`, not the shared-session test client) on a freshly reset `workbench_test`,
exercising the exact same HTTP surface the browser's own `fetch` calls use — 15 checks, all
passing: a 422 (never a 500) for `USER_ASSUMED` missing its statistic kind, for
`assumed_sigma_value="Infinity"`, for `"NaN"`, for `"0"`, and for `relative_output_weight=
"NaN"`; a valid declaration round-tripping `effective_statistic_kind`; and, end-to-end against
a dataset whose own declared SD column has a real, reported zero, `MEASURED_UNCERTAINTY_NOT_
STRICTLY_POSITIVE` firing as a blocking finding that stops `complete_review`. The backend's
own access log for that session shows zero `500`s across 17×`200`/12×`201`/1×`409`/11×`422` --
the `409` is an edit-version-conflict from a script retry, not a server error. What was *not*
re-exercised is the UI layer rendering those same requests (the select-driven form pattern is
unchanged from the already-verified walkthrough above, and is separately covered by `tsc`/
`vite build`/the frontend test suite) — that remains a disclosed gap in *rendered-browser*
coverage specifically, never implied to be covered by either verification pass above.

## 4. A real, pre-existing infrastructure bug this verification caught

The first attempt at the "declare `MEASURED`" scenario above failed with a browser-console CORS
error (`blocked by CORS policy: ... preflight request doesn't pass access control check`) on
the new `PUT .../output-weightings` route. `app/main.py`'s own `CORSMiddleware` configuration
read `allow_methods=["GET", "POST", "PATCH"]` — **`PUT` and `DELETE` were never included**, a
gap entirely unrelated to anything this increment added on its own merits.

This is the exact class of bug `tests/api/test_module_set_durability.py::TestCorsPreflight`
already exists to catch for `POST` (its own docstring cites `docs/21`'s identical incident:
`allow_methods=["GET"]` silently blocking every `POST` route, caught only by real cross-origin
browser verification, never by the ordinary API test suite, because its shared-session
`client`/`db_session` fixtures can never observe a real CORS preflight). The missing `PUT`/
`DELETE` entries mean every existing "Remove" button in this application (arms, experiments,
variable bindings, parameter roles — all `DELETE`) was silently broken in a real cross-origin
browser the entire time, never caught before because no prior live-browser verification in this
project's history happened to click a "Remove" button cross-origin.

**Fixed**: `allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"]`. **Regression-tested**:
`tests/api/test_calibration_durability.py::TestCorsPreflightAllowsPutAndDelete` adds the same
real-`OPTIONS`-preflight check `TestCorsPreflight` already established, for both a `DELETE`
route (remove arm) and the new `PUT` route (output weightings) — the exact mechanism that would
have caught this without needing a browser at all.

## 5. Test coverage added

- `tests/unit/test_time_series_workbook.py::TestMeasurementUncertaintyColumns` — 16 tests:
  byte-identical-when-absent, exclusion from measurement columns, real-zero preservation,
  unrecognized-cell disclosure, negative-value disclosure, missing-target disclosure,
  nonexistent-target disclosure, duplicate-target-first-wins, orphan-declaration disclosure,
  the independent-variable-vs-uncertainty declaration conflict, a blank or unrecognized
  statistic-kind declaration (each separately, both disclosed and unused), variance/standard-
  error token recognition, and a non-finite (`"inf"`/`"nan"`) cell in either a measurement or
  an uncertainty column being classified `UNRECOGNIZED`, never `MEASURED`.
- `tests/persistence/test_calibration.py` — `TestOutputWeighting` (14 tests: every validation
  rule in §1.4 including the finite/positive guard and the required statistic kind,
  upsert-not-duplicate, remove-reverts-to-default) and `TestUncertaintyWeightingFindings` (7
  tests: every finding in §1.5 including `MEASURED_UNCERTAINTY_NOT_STRICTLY_POSITIVE`'s own
  zero-value and all-positive cases, plus held-out-validation exclusion); one revision-
  immutability test added to the existing `TestJobRevisions` class.
- `tests/api/test_calibration.py::TestOutputWeightingEndpoint` — 3 tests: round-trip
  (asserting `effective_statistic_kind` resolves correctly), unreal-output 422, remove.
- `tests/api/test_calibration_durability.py` — one independent-session persistence-and-
  revision test (`TestOutputWeightingSurvivesAnIndependentSession`, through a genuinely
  separate `Session`/request, never a shared test transaction, asserting
  `effective_statistic_kind` resolves correctly from a brand-new request) and two
  CORS-preflight regression tests (§4).

**A test-helper bug caught along the way**: the first-drafted test for "a blank statistic-kind
declaration is disclosed and unused" initially failed, because `tests/time_series_helpers
.py::declare_measurement_uncertainty` wrote its declarations with openpyxl's
`cell(row=..., column=..., value=None)` — which is a no-op against a cell the blank template
*already* populates with its own example-row content (every sub-table's first declared row
coincides with the template's own example row), so a test trying to leave a field genuinely
blank silently inherited the template's own example value instead. This is the identical
gotcha `populate_data_tab`'s own header-clearing logic already documents and works around
(direct attribute assignment, not the `cell(...)` call); the same fix was applied to
`declare_measurement_uncertainty`. The bug was in test scaffolding only, caught by the test
itself failing for the right reason (an unexpectedly *usable* column), never shipped as a
false-positive pass.

Full suite results (`workbench_test`, confirmed-disposable, reset to a clean migrated baseline
before and after, with no other process touching it concurrently): backend **729 passed, 0
failed**; frontend **57 passed**; `tsc --noEmit` clean; `vite build` succeeds; `ruff check`
clean on every changed/new file. Two unrelated full-suite runs, each performed while this
increment's own manual live-browser verification (§3) was concurrently seeding and querying
the identical `workbench_test` database, produced spurious failures entirely explained by that
self-inflicted database contention (one run: two `tests/orchestration/test_run_orchestrator.py`
failures that passed standalone; a second, worse-timed run: 27 failures/12 errors across
unrelated orchestrator files) — neither is a real regression, and both resolved to a fully
clean run once the suite was the only thing using `workbench_test`. Documented here as a
process lesson, not a code defect: this increment's own manual DB verification and the
automated test suite must never run against the same database at the same time.

## 6. Remaining limitations, disclosed rather than papered over

- **No execution capability** — unchanged from docs/30 §6/docs/31 §6; `request_model
  _calibration` still does not exist, and §1's entire contract describes a joint objective that
  is never actually computed anywhere in this codebase.
- **No per-output weighting across a multi-arm job's own cross-arm linking** — this increment's
  scope is one experiment's own output-level configuration; `docs/30`'s cross-arm parameter-
  role linking semantics (`EXACT_EQUALITY`/`EXACT_AFFINE_LINK`/`SOFT_PRIOR_LINK`) are untouched
  and have no interaction with uncertainty/weighting modeled here.
- **`relative_output_weight` has no cross-experiment normalization** — each experiment's own
  outputs are weighted relative to each other and to that same experiment's uncertainty
  scaling, but nothing in this increment normalizes weights *across* different experiments or
  arms (e.g. so that no single experiment with many outputs dominates a multi-experiment fit
  purely by output count); this would be a real, separate design question for whenever
  execution actually exists, not a gap in configuration as such.
- **The Postgres `calibration_objective_weighting` enum permanently carries an unused
  `DECLARED_SIGMA` label** (§2.1) — an accepted, disclosed consequence of Postgres having no
  safe way to remove a single enum value without recreating the type, not an oversight.
- **The 32-character `alembic_version.version_num` ceiling (§2.2) is specific to this project's
  own alembic setup and was not generalized into a lint rule or pre-commit check** — a future
  long migration slug could reproduce the identical failure; flagging it here is this
  increment's own mitigation, not a structural fix.
- **No conversion between standard deviation, variance, and standard error** (§1.3) — this
  increment captures and discloses which of the three a value is, but never converts between
  them. A `STANDARD_ERROR`-kind value is never rescaled into the standard deviation an
  inverse-variance weight is actually defined in terms of, because that conversion needs a
  sample size (`n`) this contract does not capture anywhere (no replicate count exists as a
  structured field on `TimeSeriesDatasetRow`); fabricating one would be exactly the kind of
  invention this whole contract exists to prevent. A future execution capability consuming a
  `STANDARD_ERROR`/`VARIANCE` value must either require `STANDARD_DEVIATION` specifically or
  add real sample-size capture first — a decision deliberately left open here, not made by
  default.

## 7. Scope discipline

Migrations, models, schemas, and routes are limited to the uncertainty/weighting entities §1
describes and the one infrastructure fix §4 required to make them actually usable from a real
browser. No simulation, optimization, or execution code was added. The pre-existing
`CalibrationExperiment.weighting_notes` field, the existing three-screen layout, the existing
independent-variable-binding mechanism (docs/31), the existing parameter-catalog validation
(docs/31), and the existing revision-immutability mechanism (docs/31) are all extended, never
replaced or restructured. Screen 2's required inputs and Screen 3's summary-only nature are
unchanged from docs/30 §3/docs/31 §3 — every new input on Screen 2 is optional, and Screen 3
gained only additional summary text, never a new required action.
