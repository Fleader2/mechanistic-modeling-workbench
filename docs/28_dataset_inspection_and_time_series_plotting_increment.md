# 28. Read-Only Dataset Inspection and Time-Series Plotting

## 0. What this increment is

Extends the saved time-series dataset detail screen (docs/25) with a clear, structured view
of everything already persisted about a dataset -- measurement-column definitions, units,
declaration status, default unit-compatibility panels, sample/condition/replicate identifiers,
and the exact validation findings -- plus a genuinely interactive time-course plot: column and
condition selection, tooltips, a legend, and a data table that corresponds to whatever is
currently plotted. Nothing here edits a dataset, runs a simulation, aggregates statistics, or
overlays a model prediction; the only new "logic" is deciding what to render from data this
repository already persists exactly as docs/25 described.

## 1. Scope boundaries, stated plainly

Excluded, per task instruction: dataset editing, scientific execution of any kind, statistical
aggregation (no averaging/interpolation/smoothing/normalization anywhere in this increment),
model-prediction overlays, and schema work unrelated to this feature -- this increment adds
**no migration at all**; every fact it displays was already durable before this increment
started. The only backend change is a small, pure, computed response field (§3) and a one-line
exception-handling fix in `app.units` found along the way (§4) -- neither touches the database.

## 2. No new API routes

Every fact this screen now shows was already reachable from the existing, read-only
`GET .../datasets/time-series/{id}` response (docs/25) plus the existing alias-mapping routes
(docs/27, reused unchanged for the "when a mapping is selected" overlay) -- no new route, no
new request type, no new ownership check to write, since the existing routes' own
`_require_project`/`_require_modeling_study`/`_require_time_series_dataset` checks already
cover everything this screen reads.

## 3. The one computed addition: default unit-compatibility panels

`app.time_series.panels.group_columns_into_panels` (pure, no I/O) groups a dataset's own
measurement columns into default display panels, reusing `app.units.compare_units` -- the
project's one source of truth for unit comparison -- rather than any bespoke string matching
(task instruction: "use existing units machinery"). Two columns share a panel only when doing
so requires no implicit rescale of either one's own real values:

- Identical declared unit strings (trimmed, case-folded) -- including **both columns leaving
  their own unit undeclared**, which is treated as one shared "unit not declared" bucket, not
  fragmented per column (there is no positive evidence any two undeclared-unit columns are
  actually incompatible, and this is the common case -- see §8's plain-fixture result).
- A genuine unit alias with `compare_units`' own `conversion_factor` of exactly `1.0` (e.g.
  `"second"` vs. `"sec"`) -- no rescale is ever required to combine them.

Everything else -- dimensionally incompatible units, a parse failure on either side, one
column declared and the other not, or a **compatible-but-differently-scaled** pair (`mM` vs.
`uM`) -- is kept on separate panels by default, since combining a thousand-fold-apart pair on
one shared axis without disclosing a rescale would be exactly the "silently convert units"
task instructions forbid. This is computed fresh on every response (`TimeSeriesWorkbookPreview
.unit_panels`, a new `TimeSeriesUnitPanelGroup` list) -- never persisted, never a reason to
re-derive anything else about the dataset.

Covered by `tests/unit/test_time_series_panels.py` (11 tests: identical/case-insensitive
units, shared "undeclared" bucket, declared-never-merges-with-undeclared, dimensionally
incompatible, malformed, compatible-but-rescaled kept separate, a true 1x alias merged,
display-order preservation, every column accounted for exactly once).

**Reconfirmed against a later, separate correction request** ("dimensional compatibility
alone is insufficient for a shared numeric axis ... separate mM from uM, and isolate
unknown/malformed units"): this section's own logic already required *both* identical
dimensionality *and* a `1.0` conversion factor before sharing a panel -- `mM` and `uM` were
already kept separate by `test_compatible_but_differently_scaled_units_are_kept_separate_by_default`
before that request arrived. No backend code change was needed for this; re-run (§8) to
confirm, rather than assumed unchanged.

## 4. A real bug found and fixed: `app.units.resolve_unit_string` crashed on some malformed text

This increment's own panel grouping is the first caller to run `compare_units` over *every*
measurement column's own freely-typed unit string, not just a pre-validated one -- and
confirmed directly that `pint`'s own eval-based tokenizer raises plain `TypeError`/
`AssertionError`/`ZeroDivisionError` for some genuinely malformed free text a scientist might
actually type (e.g. `"not-a-real-unit!!"`, `"()"`, `"1/0"`), never its own `PintError`
subclass. `resolve_unit_string`'s own `except pint.errors.PintError` clause let every one of
these propagate as an unhandled exception instead of the already-documented `MALFORMED`
classification -- meaning a dataset with such a unit string would 500 instead of rendering.
Fixed by broadening that one `except` clause (every failure mode means exactly the same thing:
"not a real unit"), with a new regression test in `tests/test_units.py` covering all three
confirmed crash strings. The full backend suite was re-run clean after this fix (§8).

## 5. The time-course plot (`frontend/src/components/TimeSeriesPlot.tsx`)

A hand-rolled SVG scatter/line chart -- no charting library exists in this frontend yet (the
`package.json` description still calls it a "minimal React + TypeScript scaffold," and no
dependency beyond `react`/`react-dom` has ever been added), and introducing one for a single
chart type was judged not worth it. One panel per `unit_panels` group that has at least one
currently-selected column; every data decision is made by a separate, pure, unit-tested
library (`frontend/src/lib/timeSeriesPlotData.ts`), never inline in the component:

- **Original measurements under their own original names, always.** The plot reads
  `TimeSeriesDataRowItem.measurements[column_name]` directly -- the exact values docs/25
  persisted, under the exact bracketed names a scientist typed (`[aRAStot]`, confirmed in the
  real browser walkthrough, §8). No model or alias mapping is required anywhere in this path.
- **Preserves reported zeros, never coerces nonnumeric cells.** `plottablePointsForColumn`
  only ever excludes a row from the *plot* when its own `time_status` or this column's own
  measurement `status` is not `MEASURED` -- a real `0.0` is `MEASURED` and is plotted exactly
  (regression-tested directly, and confirmed live at `t=120` for `[pMEKtot]`, §8). Every
  excluded row is counted by *reason* (`summarizeExclusions`: `MISSING`/`NOT_APPLICABLE`/
  `UNKNOWN`/`UNRECOGNIZED`/`TIME_UNAVAILABLE`) and disclosed under the panel -- never a vague
  "N excluded," and never a silent drop (task instruction: "disclose excluded nonnumeric
  observations").
- **Connects one species' own points by time, grouped by condition and, where explicitly
  recorded, biological replicate -- never by sample id alone.** `groupIntoSeries` partitions
  one column's own plottable points by `(condition_id, biological_replicate)` before sorting
  each group by `time` (the independent variable; a species' own measured value is always the
  dependent variable) and drawing one connected line per group. `sample_id` alone never splits
  or joins a trajectory, and `technical_replicate` is deliberately *excluded* from the grouping
  key -- a technical-replicate number records a repeated measurement of one sample at one
  timepoint, and never by itself establishes identity *across* time (task instruction: "do not
  assume a technical-replicate number alone establishes longitudinal identity"). With no
  condition and no biological-replicate information recorded at all (the plain RAS/MAPK
  fixture), every point for a species falls into the single remaining group and is connected
  across every `sample_id` by time, exactly as before. Two points landing on the identical
  `time` value within one group are a genuinely ambiguous ordering -- which one came "first" is
  not knowable from the data -- so `groupIntoSeries` leaves it undrawn rather than inventing an
  order. **Breaking only the one edge between the tied points is not enough**: it would still
  arbitrarily hand the preceding point's connection to one specific tied point, and the
  following point's connection to the other, which is exactly as invented a choice as
  connecting the tied points to each other directly. So every connection touching a tied
  bucket is left undrawn -- into it, from its single predecessor, within it, among its own
  tied points, and out of it, to its single successor -- unless some identifier *more
  specific* than this grouping key already uses could resolve which tied point a neighbor
  actually continues from/to; none does for this dataset shape (`sample_id` and
  `technical_replicate` are both deliberately excluded from the grouping key itself, so neither
  is available to break a tie it is already excluded from forming). A tie one step further
  along the series -- a genuinely separate, unambiguous edge that does not itself touch the
  tied bucket -- is unaffected and still connects normally. Every real observation is still
  returned as its own point (never dropped, never averaged); a tied bucket's own points and
  both of its immediate neighbors each become their own single-point, `connectable: false`
  segment (task instruction: "show all observations and break connections into, within, and
  out of that group unless an explicit trajectory identifier resolves the ambiguity"). Sorting
  a series by time for display is never a mutation of the source rows the data table reads
  (task instruction: "handle repeated or unsorted times without changing source data").

  **A grouping key's own fields are taken at face value.** A `condition_id` of `"ctrl"` or a
  `biological_replicate` of `"1"` is trusted to mean exactly what it says wherever it recurs.
  In particular, a repeated `biological_replicate` label by itself does not *establish* that
  the rows carrying it are the same longitudinal unit -- it is only evidence of that if the
  dataset's own authors used the label consistently to track one organism/sample across time
  in the first place. Nothing in this increment verifies that consistency (there is no second,
  independent signal in this dataset shape to check it against); the label is honored exactly
  as given, the same way `condition_id` already is.

  **Revision history.** An earlier version of this increment connected points only within one
  shared, explicit `sample_id`, treating an unspecified sample identity as grounds to leave
  points unconnected. The user then directed a simpler rule: connect one species' own points
  across every `sample_id`, strictly by time, with no grouping by condition or replicate at
  all. A second correction refined that simpler rule: sample ids still never split a
  trajectory, but conditions and genuine, explicit biological-replicate identities now do --
  "sample IDs must not split trajectories .... [but] never connect different conditions or
  identified replicate trajectories" -- and a repeated-time tie broke only the one edge between
  the tied points. A third correction found that last part still arbitrary ("breaking only the
  connection between two same-time observations can still arbitrarily connect the preceding
  point to one replicate and the following point to the other") and tightened it to the
  into/within/out-of rule described above, which this section and §8 now describe and verify.
- **Tooltips and a legend.** Every point carries a native SVG `<title>` plus a custom tooltip
  (shown on hover *and* keyboard focus -- every point is focusable) with its exact value, unit,
  time, sample/condition/replicate identifiers, and source row index -- the last of these is
  "preserve source-row references," taken literally. The legend lists every currently-plotted
  column with its own color swatch and the panel's shared unit (or an explicit "Unit not
  declared").

## 6. Measurement-column/condition selection and the corresponding data table

`TimeSeriesDatasetDetailScreen.tsx` adds two accessible, native-HTML control groups (checkbox
`<fieldset>`s, every input with a visible `<label>`) -- one checkbox per measurement column,
and (only when the dataset actually has more than one distinct `condition_id`, including a "no
condition recorded" bucket if any row lacks one -- never fabricated if the dataset has none at
all) one per condition. Both default to **everything selected** -- the plot/table never start
pre-narrowed. One `TimeSeriesPlot` renders per `unit_panels` group with at least one selected
column; the same `selectedConditions` filter is applied to both the plot and a single, unified
data table beneath it, so the two always correspond exactly -- never two independent, possibly
inconsistent views of the same dataset. The table itself was extended, not replaced: a new
leading `Row`/`Sample`/`Condition`/`Bio. replicate`/`Tech. replicate` set of columns (task
instruction: "extend dataset detail with clear views of ... sample/replicate identifiers"),
honest `Not captured` cells when a structural column is absent, and every non-`MEASURED` cell
now shows **both** its own raw text and its classified status together (e.g. `NA
(NOT_APPLICABLE)`, `overflow (UNRECOGNIZED)`) -- showing only the raw text alone (an earlier
draft of this screen did exactly that) would have made `NOT_APPLICABLE` and `UNRECOGNIZED`
cells visually indistinguishable whenever a scientist's own raw text happened to look similar;
this was caught directly by this increment's own real-browser walkthrough (§8) and fixed
before this increment was considered complete. Nothing is ever paginated or truncated --
`filteredRows`/`selectedColumns` are an explicit, visible user choice, never a silent cut.

A new "Measurement columns" section lists every column's own declared unit, description,
`declared_in_metadata` status, and its default panel membership (echoing which other columns,
if any, it shares a panel with) -- all of it read straight from the existing, already-persisted
fields, nothing re-derived from a column's own spelling.

## 7. The alias-mapping overlay: two distinctions preserved explicitly

Selecting a model (the pre-existing "Map to a model" picker, docs/26/27) now also fetches that
model's **current** alias-mapping revision (`getCurrentAliasMapping`, reused unchanged) and
shows it in its own clearly separate block, never merged into the measurement-column table
above it:

- **The stored identifier is always the exact Antimony symbol, never a friendly label.** The
  overlay renders `target_antimony_species_id` verbatim, annotated explicitly as "(Antimony
  species id, not a display label)" -- confirmed live in the real browser walkthrough (§8) that
  this exact string (`s_S1_cyto`) appears, distinguished from the column's own original name.
- **A complete mapping establishes correspondence, not analysis readiness.** The overlay's own
  copy says this outright ("a separate fact from each column's own original name above; the
  plot and table below always show the dataset's own original values ... regardless of this
  mapping"), and nothing about selecting a model ever changes what the plot/table render --
  confirmed directly: the plot/table are identical before and after a model is selected.

If no mapping has ever been saved for the selected model, this is disclosed honestly ("No
mapping has been saved for this model yet.") rather than showing an empty table that could be
mistaken for "every column was explicitly left unmapped."

## 8. Test evidence

641 backend tests passed total (622 pre-existing + 19 new: 11 panel-grouping + 3 `app.units`
regression + 7 rich-fixture round-trip), `ruff check` clean -- unchanged by either
series-grouping correction (backend-only concern was the already-correct unit-panel logic,
reconfirmed by this same suite, §3). Frontend: `tsc --noEmit` + `vite build` + 55
`node --test` tests (36 pre-existing + 19 in `timeSeriesPlotData.test.ts`) all clean.

- `tests/unit/test_time_series_panels.py` -- every panel-grouping case (§3).
- `tests/test_units.py::test_resolve_classifies_unparseable_free_text_as_malformed_rather_than_raising`
  -- the real crash-string regression (§4).
- `tests/persistence/test_time_series_dataset_rich_fixture.py` (7 tests) -- the new richer
  regression fixture (`tests/time_series_helpers.py::RICH_FIXTURE_*`, added for this increment:
  three samples across two conditions with explicit biological/technical replicate
  identifiers, one genuinely repeated time within a sample, rows physically out of time order
  in the workbook, mixed declared units across four measurement columns, and every
  non-`MEASURED` cell status at least once) persisted and reopened exactly: panel grouping
  correct against real saved data, every row's own sample/condition/replicate identity
  preserved, the repeated time preserved as two distinct rows (never merged/averaged), and
  every nonnumeric status distinguished.
- `frontend/src/lib/timeSeriesPlotData.test.ts` (19 tests) -- plottability (including the real
  zero), exclusion counting by reason, series grouping (a species' own points connected across
  samples, by time, including a sample-less point and the single-point/no-point edge cases),
  condition filtering, and axis-domain padding, plus 5 tests added across the two
  series-grouping corrections: different conditions are never connected to each other even at
  an identical time; an explicit biological-replicate identity splits trajectories within one
  condition, across sample ids; a technical-replicate number alone neither splits nor joins a
  trajectory (rows differing only by it fall into the same group); a time genuinely repeated
  within one explicit trajectory returns every observation but breaks connections into,
  within, AND out of that tie -- all 4 of the repeated-time fixture's own points end up fully
  isolated, never just the one edge between the two tied points; and a tied bucket isolates
  only its immediate neighbors, leaving a genuinely separate, unambiguous edge one step
  further along the series (not itself touching the tie) still connected.

**Real, end-to-end browser verification** (never direct HTTP): `workbench_test` confirmed
disposable via `scripts/db_safety.py::require_disposable_database` before any write; the real
development database (`workbench`) was never started, connected to, or referenced.

A real, separate issue was found and fixed *before* this verification even began: this
session's own earlier full-suite run had used a shell fallback (`${TEST_DATABASE_URL:-postgresql://localhost/workbench_test}`,
with no credentials) that silently connected as the local OS role (`steven`) instead of the
project's own documented `TEST_DATABASE_URL` role (`agent1`, from `.env`) whenever the
environment variable happened not to already be exported -- each invocation was internally
self-consistent (so pytest reported passing runs either way), but the *next* invocation using
the documented `agent1` credentials then failed outright (`must be owner of table run_record`)
because the previous run had left the schema owned by `steven`. Fixed, with the user's explicit
authorization (a database-ownership change was correctly blocked pending confirmation), by
`REASSIGN OWNED BY steven TO agent1;` inside `workbench_test` alone -- confirmed disposable
first, scoped to that one database, never touching `workbench`. The full suite was re-run clean
immediately after with the documented credentials. Every command in this document and every
command this increment's own verification used afterward passed the full, explicit
`TEST_DATABASE_URL` from `.env`, never a bash-fallback guess.

A real harness-built model (via `run_orchestrator.submit_subproject_run` against the harness's
own `synthetic_agent1_view.json`, exactly the docs/26/27 pattern) produced a real, verified
`ModelSpeciesCatalog`; both the plain RAS/MAPK fixture (docs/25) and the new rich fixture (§
above) were saved as real datasets via `persist_time_series_dataset`. Driven entirely through
the actual rendered page:

1. **Plain fixture** -- every measurement column shown as unit-undeclared, sharing one default
   panel; no Conditions control offered (the dataset has no `condition_id` column at all); the
   one plot panel renders exactly 25 points (5 columns x 5 rows) and **5 connecting lines, one
   per species** (every row has no `sample_id`, `condition_id`, or replicate column recorded at
   all, so each species' own 5 points fall into a single group and are connected to each other
   by time) -- unchanged, and re-confirmed, by the series-grouping correction below; the real
   zero at `t=120` for `[pMEKtot]` reads exactly `0` in the table; every structural column
   reads `Not captured`, never fabricated; reloading reproduces the identical point/line count.
2. **Rich fixture** -- exactly three default panels (shared `mM`, separate `AU`, separate
   undeclared); real `ctrl`/`treated` condition checkboxes offered; the shared `mM` panel
   renders exactly **4 connecting lines (2 per species: `[aRAStot]`, `[pBRAFtot]`)** -- one line
   for `ctrl`/biological-replicate `1` (`S1`) and one for `ctrl`/biological-replicate `2`
   (`S2`), but *zero* lines for `treated`/biological-replicate `1` (`S3`): its own genuinely
   repeated `t=60` observation isolates not just the two tied points from each other, but also
   `t=0` (the tied bucket's one predecessor) and `t=120` (its one successor), leaving all 4 of
   `S3`'s own real observations drawn as unconnected points rather than connecting through the
   tie on an arbitrary side -- confirming lines are never merged across conditions or explicit
   biological-replicate identities, and that breaking only the edge between the two tied points
   themselves (an earlier version of this fix, since corrected) would still have been an
   undisclosed, arbitrary choice; the panel's own point count (19, not a naively-expected 20)
   is unaffected by any of this -- still directly confirms `S1`'s own `NOT_APPLICABLE` cell is
   excluded from the plot, not coerced; every non-`MEASURED` status
   (`NOT_APPLICABLE`/`UNKNOWN`/`UNRECOGNIZED`/`MISSING`) appears verbatim in the table; the
   exclusion disclosure list under the panel names the real reason and count; deselecting the
   `treated` condition drops the table to "6 of 10 rows" and the shared panel to 11 points
   across 4 lines (the two untied `ctrl` trajectories per species -- unchanged by removing
   `treated`, since `treated` drew zero lines either way) in both the table and the plot
   together; deselecting a measurement column removes its own panel entirely.
3. **Alias-mapping overlay** -- selecting the real seeded model before any mapping exists shows
   "No mapping has been saved for this model yet." honestly; saving a real mapping (through the
   pre-existing, unmodified alias-mapping screen, docs/27) and returning shows the overlay
   rendering the exact real Antimony species id (`s_S1_cyto`) explicitly annotated as "not a
   display label" -- and the plot/table above it are unchanged by this, confirmed directly.

`workbench_test` was reset to a clean, empty, head-migrated baseline afterward (full
`alembic downgrade base` / `upgrade head` cycle, confirmed disposable first).

## 9. Limitations, stated plainly

- **The plot is a hand-rolled SVG, not a library.** Adequate for this screen's own scope; a
  future increment with more chart types might reasonably introduce a real charting
  dependency instead of growing this one further by hand.
- **No virtualization/pagination for very large datasets.** Every selected row/point is
  rendered in full (task instruction: "never silently truncate") -- a dataset with many
  thousands of rows would render a correspondingly large table/point count rather than being
  cut down; this is an accepted performance tradeoff, not a correctness gap.
- **Keyboard/screen-reader access to the plot itself is partial.** Every point is focusable
  and announces its own tooltip content on focus, but the fully accessible, canonical
  representation of the data is the plain HTML data table beneath it (always present,
  reflecting the identical selection) -- the plot is a visual, pointer-first supplement, never
  the only place a value can be read.
- **Compatible-but-differently-scaled units are never combined on one panel, even though
  `compare_units` could report an exact conversion factor.** A future increment could choose to
  offer an explicit, disclosed "convert for display" toggle; this one does not, since silently
  combining them without that disclosure is exactly what task instructions forbid, and
  building a whole disclosed-conversion UI was judged out of this increment's own scope.
- **No new backend route and no new persisted fact** -- by design (§1/§2); any future increment
  needing new per-dataset computed facts beyond unit-panel grouping would need its own schema
  addition, not an extension of this one.
- **A dataset with no condition and no biological-replicate column at all still draws one line
  per species across every sample id, by explicit user direction (§5's revision history).** If
  two samples genuinely diverge at a shared or nearby time in that specific case, the single
  line will zigzag between them rather than showing two separate curves -- there is no field in
  that dataset shape asserting they *should* be kept apart. Once a dataset records a condition
  or an explicit biological-replicate identifier, this no longer applies: those trajectories are
  now kept separate (§5). Every point's own real `sample_id`/`condition_id`/replicate fields
  remain visible in its tooltip and in the data table beneath the plot regardless, so this is
  never a loss of information -- only a deliberate simplification of what an unstructured
  dataset's own single line implies.
- **A repeated-time tie within one trajectory isolates itself and both of its immediate
  neighbors -- never just the one edge between the tied points.** `groupIntoSeries` does not
  attempt to disambiguate a tie using any field this dataset shape offers but this grouping key
  already excludes (`sample_id`, row order, `technical_replicate`), since no task instruction
  establishes that any of those would be the correct tiebreaker; a future dataset shape that
  added a genuinely new, more specific trajectory identifier could resolve a tie it touches
  without changing this function's own general rule. One practical consequence: a trajectory
  with many repeated times (e.g. several technical replicates sharing one nominal timepoint
  throughout) could end up almost entirely composed of isolated points rather than one
  connected line -- an honest reflection of how little this shape's own fields actually pin
  down about ordering within such a trajectory, not a defect in the grouping logic itself.
- **A `biological_replicate` label is trusted at face value, never independently verified.**
  Two rows sharing the same `condition_id` and the same `biological_replicate` string are
  always treated as one longitudinal trajectory -- but this increment has no second signal to
  confirm the dataset's own authors actually used that label consistently to track one
  organism/sample across every time point it appears at. A dataset that reused a replicate
  label inconsistently (e.g. assigning "1" to two physically unrelated samples within one
  condition) would be connected as if it were one trajectory regardless; detecting that kind of
  authoring error is out of this increment's own scope.

## 10. Final repository state

`mechanistic-modeling-workbench` is left **uncommitted**, per explicit instruction. New:
`app/time_series/panels.py`, `frontend/src/lib/timeSeriesPlotData.ts` (+ its own test file),
`frontend/src/components/TimeSeriesPlot.tsx`, `tests/unit/test_time_series_panels.py`,
`tests/persistence/test_time_series_dataset_rich_fixture.py`, and this document. Modified:
`app/schemas/time_series_dataset.py` (`unit_panels`), `app/units.py` (the exception-handling
fix, §4), `tests/test_units.py` (its regression test), `tests/time_series_helpers.py` (the new
rich fixture), `frontend/src/components/TimeSeriesDatasetDetailScreen.tsx`,
`frontend/src/types.ts`, `frontend/src/styles/app.css`. No other repository (`agent-
integration-harness`, `agent2-antimony-builder`) is touched at all -- this increment has no
Harness/Agent 2/3/4/5 code change, and the one real harness model/catalog used for live
verification was produced entirely through the existing, unmodified docs/26 capture path.
