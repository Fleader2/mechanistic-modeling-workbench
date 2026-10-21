# 25. Downloadable Two-Tab Excel Template: time-series dataset import

## 0. What this increment is, and what it deliberately is not

A scientist can download a blank, two-tab `.xlsx` template, fill it in with a real time-series
experimental dataset, upload it, see a parsed preview with every validation finding disclosed,
save it explicitly, and reopen it later read-only -- exactly, without loss, including the
deliberately-unspecified gaps (units, sample identities, replicate assignments, most
experimental metadata) the task's own regression fixture leaves open.

**Deliberately excluded, per task instruction**: model-specific alias mapping (matching an
uploaded column name to an Antimony species), scientific execution of any kind, any measurement
format other than this one two-tab workbook shape, development-database cleanup, and any Figma
change. Uploading and saving a dataset never requires a model or a matching Antimony species
name -- nothing in this increment's own schema, persistence, API, or frontend code references
either.

## 1. Context: what already existed, and what did not

`docs/15_gui_backend_integration_audit.md` (this repository's own prior audit) had already
documented the Figma design's four-sheet Dataset/Samples/Measurements/Mapping upload wizard
(node `47:358`) and stated flatly: **"No corresponding backend entity exists at all"** for
upload, parsing, or storage of any kind (`docs/15` lines ~150-153, 204, 230, 235). This
increment's own two-tab, no-alias-mapping scope (per this task's own instruction) is a
deliberately reduced version of that four-sheet design -- alias/column mapping is explicitly a
later increment, not implemented or required here.

`app.models.dataset_reference.DatasetReference` already existed as a thin **catalog** entry --
its own module docstring already called it "a catalog entry *about* a dataset ... never the
dataset's own content," with `artifact_reference` explicitly documented as "opaque... never
parsed here." This increment reuses it exactly as that docstring anticipated: one
`DatasetReference` row (a new `dataset_type`, `"time_series_experimental_observation"`) per
saved import, automatically counted by the existing "Datasets" column on the Modeling Studies
table (`count_dataset_references_by_subproject`) -- no change needed there -- plus a new content
model holding everything `DatasetReference` itself deliberately does not.

**Reconciling "previously documented metadata requirements."** Agent 1's own
`ExperimentalContext`/`QuantitativeObservation` schema is the closest prior art for dataset
metadata in this whole system, but it models a *curated, already-structured* observation
(`organism_id` as an FK to a curated `Organism`, `biological_replicate_id`/
`technical_replicate_id`, `normalized_value`/`normalized_unit` after Agent 1's own pipeline has
run), not an *as-uploaded, possibly-incomplete* spreadsheet a scientist fills in by hand before
any curation happens. This increment's own `Metadata` tab deliberately uses free-text fields for
every one of these (organism as plain text, not an FK; no normalization step) -- the two schemas
describe different stages of the same information's life, not the same stage twice. Every field
this task's own instruction asked for (organism/cell type/strain, experiment/measurement type,
scientific objective, conditions/treatments, assay, provenance, processing/normalization, time
units, measurement-column units) has a direct field in the `Metadata` tab's own `METADATA_FIELDS`
(`app/time_series/contract.py`); none is invented beyond what was asked.

## 2. The workbook contract (`app.time_series.contract`)

One module (`app/time_series/contract.py`) is the single source of truth both the template
writer and the parser import from, so the two can never silently drift apart. `TEMPLATE_VERSION
= "1.0"` is written into every generated template and read back as a non-blocking finding if
missing/unrecognized -- never a reason to refuse an import, since v1 is the only version that
has ever existed.

**`Metadata` tab** -- a scalar `Field | Value | Guidance` table, in this fixed order:

| Field | Required | Notes |
|---|---|---|
| Template version | required | prefilled, "do not edit" |
| Dataset name | required | falls back to the uploaded filename, disclosed, if blank |
| Experimental date | required | a raw string -- never coerced into a date type (see §4) |
| Organism | required | free text |
| Cell type | optional | |
| Strain | optional | |
| Experiment type | required | |
| Measurement type | required | |
| Scientific objective | required | |
| Conditions / treatments summary | optional | free text; see the legend sub-table below |
| Assay | required | |
| Provenance | required | e.g. lab, instrument, collected by, source file |
| Processing / normalization | required | must say "raw / unprocessed" explicitly if true -- never left blank to mean that |
| Time unit | required if Data tab has any time values | |

Followed by two marker-delimited sub-tables, found by searching column A for a literal marker
string (`## Measurement column definitions`, `## Condition / treatment legend`) rather than a
fixed row number, so an extra blank row never breaks parsing:

- **Measurement column definitions**: `Column name (must match a Data tab column exactly) |
  Unit | Description` -- one row per Data-tab measurement column the scientist chooses to
  document. A Data-tab column with no matching row here is still imported, just flagged
  (`MEASUREMENT_COLUMN_UNIT_UNDECLARED`) -- its unit is genuinely unknown, never fabricated.
- **Condition / treatment legend** (optional, only relevant if the Data tab uses a
  `condition_id` column): `Condition ID | Description`.

**`Data` tab** -- wide format. Five structural (non-measurement) columns, matched
case-insensitively and trimmed, every one of which except `time` may be entirely absent (task
instruction: "where applicable" -- never fabricated if absent): `sample_id`, `condition_id`,
`biological_replicate`, `technical_replicate`, `time`. Every other header is a user-defined
measurement column, preserved **verbatim** -- including square-bracket names like
`[aRAStot]`, never decomposed or reinterpreted (task instruction: do not infer composite
observables from a column's own spelling).

## 3. Malformed vs. incomplete: the one distinction this whole increment is built around

`app.time_series.parser.parse_workbook` makes exactly one structural decision, and never a
second one disguised as the first (task instruction: "distinguish malformed workbooks that
cannot be imported from incomplete scientific metadata that can be saved with unresolved
findings"):

- **Malformed** (raises `WorkbookMalformedError`, carrying every such problem found, not just
  the first -- nothing is ever partially saved): the file cannot be opened as a `.xlsx` at all,
  a required sheet (`Metadata`/`Data`) is missing, the `Data` tab has no header row, no `time`
  column, zero measurement columns, or a duplicate column header (structural or measurement).
- **Parseable, possibly scientifically incomplete** (a non-blocking `Finding` on the returned
  `ParsedWorkbook`, never a reason to refuse the save): a blank required metadata field, an
  undeclared measurement-column unit, an unrecognized cell value, an all-missing data row, an
  unrecognized/missing template version.

**Value classification** (`_classify_cell_value`) is the one place "missing," "recorded as not
applicable," "recorded as unknown," and "a real, reported zero" are told apart --
`MeasurementValueStatus` (`app/models/enums.py`): `MEASURED` / `MISSING` / `NOT_APPLICABLE` /
`UNKNOWN` / `UNRECOGNIZED`. A boolean cell is guarded separately from numeric coercion (Python's
`isinstance(True, int)` is `True`, which would otherwise silently turn a stray `TRUE`/`FALSE`
cell into `1.0`/`0.0`) and classified `UNRECOGNIZED` instead, with a disclosed finding.
`"na"`/`"n/a"`/`"not applicable"` (case-insensitive) → `NOT_APPLICABLE`; `"unknown"`/`"unk"` →
`UNKNOWN`; anything else non-numeric and non-blank → `UNRECOGNIZED`, with the raw text disclosed
in its own finding, never silently dropped.

## 4. Schema (migration `0016_time_series_dataset`)

One new enum (`measurement_value_status`, the `MeasurementValueStatus` vocabulary) and three
new tables:

- **`time_series_dataset`** -- one row per saved import, **1:1 with a `dataset_reference` row**
  (`ON DELETE RESTRICT`, the same precedent `module_execution_snapshot` already set for "has its
  own lineage," never the "no independent existence" `CASCADE` precedent). Every structured
  `Metadata`-tab field is nullable -- a blank field is an honest, disclosed gap, never
  fabricated, never a reason this row cannot exist. `experimental_date` is a raw string, never a
  `Date` column, since enforcing a parseable format would mean either fabricating one or
  rejecting an honest, ambiguous entry. `validation_findings` is the exact findings list computed
  at save time, persisted verbatim, so a later reopen shows what was actually found *then*,
  never silently re-derived against a parser that may have since changed. Immutable: no
  `updated_at` column, and no persistence function in this repository ever issues an `UPDATE`
  against any of these three tables.
- **`time_series_measurement_column`** -- one row per Data-tab measurement column, `CASCADE`
  from `time_series_dataset` (pure decomposition, no independent existence). Original header
  text and left-to-right `display_order` both preserved exactly.
- **`time_series_dataset_row`** -- one row per Data-tab data row, `CASCADE` from
  `time_series_dataset`. `measurements` is a JSON string (this repository's own established
  `Text`-holding-JSON convention, matching `module_execution_snapshot.snapshot_payload` -- never
  a native JSONB column) mapping each column's own exact name to `{"status", "value", "raw"}`.

## 5. Storage (`app.storage`)

A new, minimal local-filesystem store: content-addressed by sha256
(`<artifacts_dir>/datasets/<sha256>.xlsx`), one valid implementation of the pre-existing
`artifact_reference`-as-opaque-string contract -- swapping it for object storage later needs no
schema change. This is the one piece of this increment's own duplicate-save protection that
lives outside the database: `persist_time_series_dataset` re-saving byte-identical content is a
no-op at the storage layer, and `persist_dataset_reference`'s own pre-existing
`(project_id, name, artifact_reference)` dedup key then reuses the existing catalog row (and,
transitively, the one `TimeSeriesDataset` its own unique `dataset_reference_id` constraint
permits) rather than creating a duplicate.

`persist_time_series_dataset` always **re-parses the raw workbook bytes itself** -- it never
trusts a caller-supplied, already-parsed structure as the source of truth for what gets saved,
the same discipline `submit_module_set_simulation` already applies to a pinned snapshot.

## 6. API surface

Six routes added to `app/api/v1/routes/projects.py`, all scoped under one Modeling Study
(ownership-checked, 404 for an unknown project/study or a dataset belonging to a different
study):

| Method | Path | Behavior |
|---|---|---|
| GET | `.../datasets/time-series/template` | the blank `.xlsx`, identical regardless of project/study |
| POST | `.../datasets/time-series/preview` | parses and returns everything it would import plus every finding; **persists nothing** |
| POST | `.../datasets/time-series` | re-parses and durably saves; 201 |
| GET | `.../datasets/time-series` | every saved dataset for this study, newest first |
| GET | `.../datasets/time-series/{id}` | reopen one, read-only, exactly as saved |

A malformed workbook is a **422** (never a 500, never a partial result) from both `preview` and
the save route, with every structural finding in the error context. Saving a workbook with
unresolved *scientific*-metadata findings is explicitly allowed -- only a malformed workbook is
ever rejected; an incomplete one is a real, honestly-labeled record, not an error.

## 7. Frontend

`TimeSeriesDatasetsListScreen.tsx` (template download, file picker, parsed preview with
findings, explicit save, saved-dataset list) and `TimeSeriesDatasetDetailScreen.tsx`
(read-only reopen) -- new route
`/projects/:id/studies/:id/datasets/time-series[/:id]`, and the Sidebar's own "All datasets"
item (disabled since the Module-Set increment) finally wired to something real, mirroring that
increment's own "All modules" precedent exactly. Nothing on either screen references a model or
an Antimony species name.

## 8. Test evidence

577 backend tests passed total (535 pre-existing + 42 new), `ruff check` clean, frontend
`tsc --noEmit` + `vite build` + 32 `node --test` tests (27 pre-existing + 5 new router tests)
all clean:

- `tests/unit/test_time_series_workbook.py` (23 tests) -- template shape, every malformed-
  workbook case, every value-classification case (including the boolean-cell guard and the
  real-zero-vs-missing regression), measurement-column declaration matching, condition-legend
  parsing, and the supplied regression fixture's own exact round-trip (every column/value, the
  real reported zero at `t=120` for `[pMEKtot]` preserved as `MEASURED`/`0.0` rather than
  collapsed to missing, and every blank required metadata field disclosed as its own finding).
- `tests/persistence/test_time_series_dataset.py` (7 tests) -- full persistence round-trip,
  the catalog-entry link and its "Datasets" count, the filename-fallback disclosure, re-saving
  identical content reusing the existing row, and a malformed workbook persisting nothing at
  all (not even a catalog row).
- `tests/api/test_time_series_dataset.py` (12 tests) -- the full HTTP surface: template/preview/
  save/list/reopen, 422-not-500 for both a structurally malformed workbook and completely
  unreadable bytes, re-saving identical content, an unknown dataset id or cross-study access
  both 404ing.
- `tests/api/test_time_series_dataset_durability.py` (3 tests, following
  `test_module_set_execution_durability.py`'s own independent-session pattern) -- a save is
  visible from a second, independent request/session, plus CORS preflight for both new POST
  routes.

**A real bug was found and fixed during this review, before committing**: `migrations/versions/
0016_time_series_dataset.py` originally declared the `assay` column as `sa.String()` while
`app/models/time_series_dataset.py` mapped it as `Text` -- functionally identical in PostgreSQL
(both unbounded), but inconsistent; the migration was corrected to `sa.Text()` to match.
Separately, `tests/conftest.py`'s own session-scoped `test_environment` fixture set
`DATABASE_URL`/`APP_ENV` for the whole test session but never redirected `ARTIFACTS_DIR` --
meaning every test run durably wrote real, content-addressed `.xlsx` blobs straight into this
repository's own working directory rather than a disposable location (confirmed directly: a real
test run left two real `.xlsx` files under this repo's own `artifacts/datasets/`). Fixed by
redirecting `ARTIFACTS_DIR` to a `tmp_path_factory`-created session-scoped temp directory in that
same fixture, and `artifacts/` was added to `.gitignore` (it held no entry there at all before
this review, so a saved workbook would otherwise have been one `git add -A` away from being
committed as a binary blob). Re-ran the full suite after both fixes: still 577 passed, and the
repository's own `artifacts/` directory is no longer created by a test run at all.

## 9. Real rendered-browser verification

Playwright was installed as a disposable, uncommitted dev-only tool (outside the repository
entirely, in a scratch directory -- never a project dependency), reusing the same install from
an earlier increment's own browser verification this session. `workbench_test` was reset to a
clean baseline, confirmed disposable via `scripts/db_safety.py::require_disposable_database`,
before any write; the real development database (`workbench`) was never started, connected to,
or referenced.

Driven entirely through clicks/file-picks in the actual rendered page (never a direct HTTP
call):

1. The "All datasets" screen loads empty ("No datasets saved yet.").
2. "Download template" downloads a real two-tab `.xlsx` (confirmed non-empty bytes received by
   the browser's own download event).
3. The downloaded template, populated with the task's own exact regression fixture (`Time,
   [aRAStot],[pMEKtot],[pYERKtot],[pTpYErk],[pBRAFtot]` / five rows, metadata left entirely
   blank -- "retain those gaps honestly") via the file picker, parses and renders a preview.
4. Validation findings are shown, including the disclosed blank-metadata gaps (e.g. "Organism"
   left blank) -- never fabricated.
5. The data table renders all five measurement column headers verbatim (including the bracketed
   names) and five rows; row 2 (`t=120`)'s `[pMEKtot]` cell renders exactly `"0"` -- the real,
   reported zero, never `MISSING` and never silently blank.
6. Explicit save (with a `saved_by` value) succeeds.
7. The saved dataset appears in the list with the correct row/column counts.
8. Reopening it (read-only) shows every measurement column and the `saved_by` value, unchanged.
9. Reloading the reopened page shows the identical saved content -- nothing is re-parsed or
   re-run on reopen.
10. A malformed workbook (the blank template, with zero measurement columns) is uploaded through
    the same file picker: rejected with a clear, specific message ("The Data tab has no
    measurement columns -- nothing to import."), no "Save dataset" button is ever offered, and
    the saved-dataset count is unchanged by the rejected attempt -- confirmed by reloading and
    re-counting, not merely by the absence of a success message.

`workbench_test` was reset to a clean baseline again afterward.

## 10. Limitations, stated plainly

- **No alias/species mapping** -- deliberately excluded per task instruction; a measurement
  column's own name (e.g. `[aRAStot]`) is preserved verbatim and carries no relationship to any
  model or Antimony species anywhere in this increment's code.
- **No scientific execution of any kind** touches a saved dataset -- it is purely imported,
  previewed, and reopened.
- **Single workbook format only.** No CSV, no other spreadsheet layout, no multi-file upload --
  future measurement-type increments are expected to ship their own matching template/importer
  pair, per this task's own closing instruction, rather than generalizing this one.
- **`experimental_date` is an unvalidated free-text field.** This is deliberate (see §4), but it
  means no downstream code can sort or compare dates reliably without first imposing a format --
  not attempted here.
- **The reopened "original filename" is the dataset's own effective display name, not
  necessarily the literal uploaded filename.** When a scientist leaves "Dataset name" blank, the
  effective name (shown on reopen as both the catalog name and the "original filename") falls
  back to the uploaded filename at save time -- but if "Dataset name" *was* filled in and differs
  from the literal uploaded filename, that literal filename itself is not separately retained.
  A minor, known simplification, not a data-loss bug: every measurement value, column, and
  metadata field is retained exactly; only the literal upload filename, when it differs from the
  effective name, is not.
- **No update or delete.** A saved dataset is immutable and permanent (by design, matching "read
  only reopening" -- re-uploading different content always creates a new, separate dataset,
  never overwrites one).
- **No per-user authentication.** `saved_by` is free text, matching every other "who did this"
  field in this codebase (`ModuleBoundaryPort.decided_by`, etc.) -- a known, pre-existing,
  system-wide limitation, not new here.

## 11. Final repository state

`mechanistic-modeling-workbench` is left **uncommitted**, per explicit instruction. New: the
migration, models, persistence, `app/storage.py`, `app/time_series/{contract,template,parser}
.py`, API routes/schemas, two frontend screens, routing/sidebar wiring, and the five new test
files listed in §8, plus `openpyxl`/`python-multipart` added to `pyproject.toml`. Modified:
`app/models/enums.py` (`MeasurementValueStatus`), `app/models/__init__.py`, `app/config/
settings.py` (`artifacts_dir`), `app/api/v1/routes/projects.py`, `tests/conftest.py` (the
`ARTIFACTS_DIR` test-isolation fix, §8), `.gitignore` (`artifacts/`), and the frontend router/
sidebar/`App.tsx`/`types.ts`/`client.ts`/`app.css` files needed to wire up the new screens. No
other repository (`agent-integration-harness`, `agent2-antimony-builder`) is touched at all --
this increment has no Harness/Agent 2/3/4/5 involvement whatsoever.
