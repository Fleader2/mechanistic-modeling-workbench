# Structured Units and Dimensional-Consistency Validation

See `docs/13_cross_module_diagnostics.md`'s own "Remaining scientific limitations" section,
whose first bullet is exactly what this increment replaces: *"Unit comparison is a bare
string-equality check ... `"mM"` vs `"mmol/L"` ... would be flagged as incompatible even though
it is not."*

## Goal

Replace fragile unit-string comparisons with structured unit semantics, so the Workbench can
detect equivalent/convertible units, incompatible dimensions, and missing unit information
*before* simulation, calibration, validation, or cross-module comparison -- never a bare
string-equality check standing in for real dimensional analysis.

## Library choice

[`pint`](https://pint.readthedocs.io/) (task instructions §1: "preferably using a well-
supported units library rather than custom dimensional algebra"), confirmed by direct testing
against this Workbench's own real unit vocabulary -- not hypothetical units -- to correctly
parse and compare every standard unit already in use by Agent1/Agent2 (`"mM"`, `"mmol/L"`,
`"1/s"`, `"umol/min"`, `"umol/min/mg"`, `"°C"`, ...).

Four real, already-emitted unit strings are **not** in pint's own default registry, confirmed
by direct inspection of the upstream agents' own source (never assumed):

* `per_sec` -- Agent2's own `CANONICAL_UNIT_PER_SEC`
  (`agent2-antimony-builder/app/agent2/parameters/reconstruction.py:63`), physically
  `1/second`.
* `nM_per_s` -- Agent2's own `CANONICAL_UNIT_NM_PER_S`, physically `nanomole/liter/second`.
* `per_nMs` -- Agent2's own `CANONICAL_UNIT_PER_NMS`, physically
  `1/(nanomole/liter * second)`.
* `cell` -- from Agent1's own `"molecules/cell"` unit string (confirmed across
  `agent1-biochemical-curator/tests/`/`app/`) -- a count of cells.

`app/units.py` registers each of these on its own project-owned `pint.UnitRegistry` --
**taught, never invented** (task instructions §9): each is a real, already-well-defined
physical (or counting) unit Agent1/Agent2 already emit today, not a meaning assigned to
satisfy this increment alone. `cell` is given its own new base dimension (`[cell_count]`),
deliberately *not* unified with `[substance]` -- pint's own default registry already treats
`"molecules"`/`"molecule"` as the builtin `particle` unit, dimension `[substance]`, and a
copy-number ratio like `"molecules/cell"` is not the same physical quantity as a molar amount;
unifying them would be a fabricated equivalence, not a taught one.

## Structured unit representation

Two layers, deliberately kept separate (task instructions §8: "add minimal additive ...
metadata support" rather than widen every existing table's own schema):

1. **`app.units`** -- pure, stateless, no database dependency. `resolve_unit_string(raw)`
   returns `{source_unit_string, normalized_unit, dimensionality, parse_status}`;
   `compare_units(unit_a, unit_b)` returns `{status, conversion_factor, unit_a, unit_b}` (each
   side's own full resolution, so a caller always sees exactly what was compared).
   `find_observation_unit_conflict` is the one additional pure function the pre-flight checks
   share (see below). Deterministic and idempotent by construction (task instructions §10): a
   pure function of its own string argument(s) alone, over one fixed, version-pinned registry
   configuration.
2. **`app.models.unit_resolution.UnitResolution`** / `app.persistence.unit_resolution` -- a
   durable, content-addressed *cache* of every distinct raw unit string this Workbench has
   ever resolved (`source_unit_string` unique; `normalized_unit`/`dimensionality`/
   `parse_status` alongside). Standalone: no foreign key in or out, never joined against by
   any other table's own schema. Immutable once created -- resolving the same string again
   returns the existing row's own already-stored fields, never updated (migration
   `0012_unit_resolution`).

A "comparison" (`compare_units`'s own result) is never itself persisted in its own table: every
caller that needs to record one already has an existing JSON evidence/snapshot column to embed
the full result into (task instructions §5 only asks that a conversion be *recorded*
somewhere, never that it live in a dedicated history table).

### `UnitComparisonStatus` -- the four outcomes (task instructions §4)

* `COMPATIBLE` -- same dimensionality; `conversion_factor` always reported (possibly `1.0`),
  never a silent conversion.
* `INCOMPATIBLE` -- both parse, but dimensionalities genuinely differ.
* `MALFORMED` -- at least one side fails to parse at all.
* `MISSING` -- at least one side is `None`/blank -- never fabricated as any other status (task
  instructions §9).

`UnitParseStatus` (`PARSED`/`MALFORMED`/`MISSING`) is the single-unit analogue, and the one
mapped to a real database column (`UnitResolution.parse_status`) -- deliberately re-declared
(not imported) in `app.models.enums` so every enum mapped to a column lives in that one module,
matching every other enum in this schema; `app.units` reads it only by `.value`.

## Where unit validation is applied (task instructions §3)

* **`ModuleBoundaryPort`** -- `cross_module_diagnostics_orchestrator._detect_boundary_conflicts`
  now calls `compare_units` on every shared-species pair's own recorded unit, replacing the
  prior bare `unit_a != unit_b` check.
* **Model parameters where unit metadata exists** -- a calibration's own
  `ModuleExecutionSnapshot.snapshot_payload["parameters"]` array already carries each
  materialized parameter's own `unit` (Agent2's own `_parameter_dict`, never fabricated here).
  `_detect_parameter_conflicts` now compares both modules' own recorded unit for the identical
  `target_id`/`parameter_id`, alongside its existing fitted-value comparison.
* **Experimental dataset observations / calibration/validation observables** -- neither
  Agent4's `Observation` nor Agent5's `ValidationObservation` carries a unit field today (no
  fabrication was going to change that), so this increment adds one small, additive,
  Workbench-only convention: an observation dict in a `calibration_request`/
  `validation_request` may carry an **optional** `"unit"` key. It is never required, and never
  read by Agent4/5 (their own request parsers index known keys explicitly -- an extra key is
  simply ignored, confirmed directly against `runners/run_agent4.py`/`run_agent5.py`).
* **Initial conditions/concentrations** -- covered by the `ModuleBoundaryPort` case above
  (`initial_value`/`unit` together already represent a boundary species' own fixed condition).

## Pre-flight dimensional checks (task instructions §6)

`app.units.find_observation_unit_conflict(observations, boundary_units_by_species)` checks
every observation's own optional `"unit"` against two sources of *already-available* metadata,
never a fabricated one:

1. the target species' own already-resolved `ModuleBoundaryPort.unit`, when that species
   happens to also be a boundary species;
2. every *other* observation in the same request for the identical `target_species_id` --
   always available, including for a purely dynamic (non-boundary) species, e.g. two
   independent/replicate observations of the same species declaring incompatible units.

`module_calibration_orchestrator._validate_calibration_request` and
`module_validation_orchestrator._validate_validation_request` both call this before any
harness invocation, raising `ModuleCalibrationValidationError`/`ModuleValidationValidationError`
on a genuine `INCOMPATIBLE` finding -- never on `MALFORMED`/`MISSING` (an unparseable or absent
unit is a disclosure concern for diagnostics, not grounds to block an otherwise-valid request).

## Diagnostics integration (task instructions §7)

`cross_module_diagnostics_orchestrator._unit_compatibility_finding` is the one shared helper
both `_detect_boundary_conflicts` and `_detect_parameter_conflicts` now call. Severity reflects
what was actually found, never a flat "units differ":

* `INCOMPATIBLE` -> `ERROR` (a real logical conflict, worse than the prior bare-string-mismatch
  `WARNING`).
* `MALFORMED` -> `WARNING` (not yet known whether the units would even conflict).
* a unit recorded on only one side, or dimensionally-equivalent-but-differently-written units
  (e.g. `"mM"` vs `"mmol/L"`) -> `INFO`, with the full `compare_units` result (including any
  conversion factor) embedded in the finding's own `evidence_payload` -- disclosed, never
  silently treated as either a conflict or a free conversion.
* both sides missing a unit entirely, or both resolving to the identical normalized unit -> no
  finding (nothing to compare, or nothing to disclose).

Still category `UNIT_INCOMPATIBILITY` -- no new `CrossModuleDiagnosticCategory` value was
needed; only the comparison *inside* that category became real dimensional analysis.

## Backward compatibility (task instructions §9)

No existing column changed shape: `ModuleBoundaryPort.unit`/a materialized parameter's own
`unit` were already free-text, nullable strings, and remain so. A pre-existing row with
`unit=None` is classified `MISSING`; a pre-existing row with a unit string pint cannot parse is
classified `MALFORMED` -- both are *disclosed*, never fabricated as a guessed-compatible or
guessed-incompatible outcome.

## Determinism and idempotency (task instructions §10)

`resolve_unit_string`/`compare_units` are pure functions of their own string argument(s) alone,
over one fixed registry configuration -- calling either twice with identical input always
returns an identical result. `resolve_and_persist_unit` is idempotent by
`source_unit_string` (create-if-absent), the same discipline every other content-addressed
table in this schema already uses.

## Tests

`tests/test_units.py` (18 tests, no database): equivalent concentration/time units,
incompatible dimensions, malformed/unknown units, missing-unit cases (including missing taking
precedence over malformed), non-trivial conversion factors, determinism/idempotency.

`tests/persistence/test_unit_resolution.py` (7 tests): missing/blank units never persisted,
parsed/malformed units persisted and cached, idempotent re-resolution, unknown-string lookup,
fresh-session reload.

`tests/orchestration/test_cross_module_diagnostics_orchestrator.py`: a genuinely incompatible
boundary-unit pair now correctly reported as `ERROR` (replacing the old test that had
incorrectly asserted `"mM"` vs `"mol/L"` as a `WARNING`-level conflict -- they are, in fact,
dimensionally equivalent); a new test confirming the equivalent-but-differently-written case is
`INFO` with the real conversion factor recorded; a new test for parameter-unit incompatibility
across modules sharing an identical, identically-fitted `target_id`.

`tests/orchestration/test_module_calibration_orchestrator.py` /
`test_module_validation_orchestrator.py`: a dimensionally incompatible observation unit
rejected before any harness call; an equivalent-but-differently-written observation unit
accepted; **one realistic integration test**
(`test_real_units_smoke_accepts_equivalent_rejects_incompatible`) driving the real Agent2-
>Agent3->Agent4 calibration subprocess chain twice against the identical real dynamics fixture
used by this repository's own non-units calibration smoke test -- confirming a second,
dimensionally incompatible observation of the same target species is rejected before the
harness is ever invoked, while a second observation declaring a merely differently-written but
equivalent unit is accepted and the real calibration still recovers the same true parameter
value.

Full Workbench suite: 334 passed (303 pre-existing + 31 new), zero regressions. Harness and
every Agent repository unaffected (confirmed by `git status`); lint and format clean.

## Remaining limitations

* `"molecules/cell"` (Agent1's own copy-number unit) parses successfully (both `molecules` --
  pint's own builtin `particle` -- and the custom `cell` are now real, defined units), with its
  own dimensionality `[substance] / [cell_count]` -- deliberately *not* unified with a molar
  concentration's own `[substance] / [length]**3`, so it is never wrongly reported `COMPATIBLE`
  with one. It is, however, *dimensionally identical* to any other `[substance]/[cell_count]`
  quantity, which is correct (a copy-number ratio is a copy-number ratio), not a gap.
* Temperature (and any other affine/offset unit) is excluded from `conversion_factor`'s own
  correctness guarantee: the factor is computed as a pure ratio-scale conversion
  (`Quantity(1, a).to(b).magnitude`), which is exact for every ratio-scale unit in this
  Workbench's own real vocabulary (concentration, time, mass, rate constants, ...) but not
  meaningful for an offset-based unit like `"°C"`. No test in this increment exercises
  temperature conversion for this reason; this Workbench's own unit model does not attempt
  offset-aware conversion.
* The observation-level `"unit"` annotation is a Workbench-only, additive convention -- it is
  never required, never validated as present, and (by design) never forwarded to or read by
  Agent4/5. A caller that omits it gets no pre-flight dimensional check at all for that
  observation, exactly as before this increment.
* Pre-flight observation-unit checking only ever compares against two sources: a matching
  boundary port's own unit, and other observations of the identical species *within the same
  request*. It cannot compare against a *different* request's own prior observations, or
  against a materialized (but not yet calibrated) parameter's own unit before any harness
  round-trip has ever happened for this module.
* `UnitResolution` caches a resolution by its own exact string under this repository's current
  registry definitions; upgrading this module's own custom unit definitions in a future release
  could in principle yield a different resolution for an already-cached string. Out of scope
  here, matching this schema's existing determinism assumptions elsewhere (e.g.
  `ModuleAggregate`'s own fingerprinting).
