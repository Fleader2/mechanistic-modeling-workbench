# Hierarchical Aggregation of Module-Level Agent3/4/5 Results

See `docs/09_module_level_agent4_calibration.md`/`docs/10_module_level_agent5_validation.md`/
`docs/11_module_validation_boundary_pinning.md` for the increments this one builds on.

## Goal

Assemble simulation, calibration, and validation outcomes from executable child modules into
durable parent/root hierarchy summaries -- without losing provenance, and without pretending
that independently analyzed modules form one globally calibrated model.

## Why this is a Workbench-only change

Aggregation only ever reads already-persisted `RunRecord`/`ModuleExecutionSnapshot` rows and
the already-persisted hierarchy topology (`ModelModule.parent_model_module_id`). It never
invokes any agent or the harness (task instructions §8) -- the module-level results it rolls up
were already produced by the existing, already-tested `request_module_simulation`/
`request_module_calibration`/`request_module_validation` orchestrators. This increment touches
only `mechanistic-modeling-workbench`.

## The aggregation model: recursive, per-execution-kind, immutable, versioned

A **target** is either a specific, durable `ModelModule` or the hierarchy root itself
(`target_model_module_id IS NULL`, rolling up every depth-1 `ModelModule` of one hierarchy
run -- the root is never itself a `ModelModule` row, the identical convention
`ModelModule.parent_model_module_id` already uses for "this module's own parent is the root").

Aggregates are tracked **separately by `ModuleExecutionKind`** (`SIMULATION`/`CALIBRATION`/
`VALIDATION`, the enum this repository already defined) -- a module can have up to three
independent, differently-shaped aggregates, one per kind, and they are never merged into one
score (task instructions §2). Within one kind, a target's own aggregate rolls up exactly two
things: that target's own *direct* result (the most recent successful `RunRecord` of the
matching stage for that module, if any -- or the most recent attempt of any outcome, so a
module that only ever failed still shows that failure rather than silently nothing), and each
direct child's own **already-built latest aggregate** (never re-walked raw `RunRecord`s a
second level down -- each level trusts the level below it, which is itself immutable once
built).

**Recursive by construction** (task instructions §5): `build_root_aggregate`/
`build_module_aggregate` recursively build (idempotently -- a no-op if nothing changed) every
direct child's own aggregate *before* rolling it up, so a single call to build the root
aggregate transparently walks the whole tree, leaf to root, using only the persisted
`parent_model_module_id` relationship -- topology is never recomputed.

**Immutable and versioned** (task instructions §6), the identical discipline
`ModuleExecutionSnapshot` already established: no `updated_at` column, no `UPDATE` ever
issued. `app.persistence.module_aggregate.create_aggregate` is idempotent by
`input_fingerprint` (a `sha256` digest of the own-result's `run_record_id` plus every direct
child's own aggregate id+version) against the *latest* existing version for that exact
target+kind -- an unchanged rebuild returns the existing row untouched; a genuinely new or
changed contribution anywhere below creates a new, separately-numbered version, and the
previous version is never mutated or deleted.

## Completeness: a coverage statement, never a quality judgment

`ModuleAggregateCompleteness` (`COMPLETE`/`PARTIAL`/`EMPTY`) is computed by treating the
target's own direct attempt (when one was ever made) and each direct child's own aggregate as
equally-weighted *slots*:

```
total_slots   = n_children + (1 if own_attempted else 0)
complete_slots = n_children_complete + (1 if own_succeeded else 0)

COMPLETE  if complete_slots == total_slots  (and total_slots > 0)
EMPTY     if complete_slots == 0  (including total_slots == 0: nothing ever attempted)
PARTIAL   otherwise
```

This formula was deliberately reworked during development after a real bug: an earlier
version let a module whose own result *succeeded* be downgraded to `EMPTY` just because its
one child had no data at all. `test_own_result_plus_an_empty_child_is_partial_not_empty`
guards against a regression of exactly that. Completeness never reflects scientific
agreement, fit quality, or validity -- only whether evidence exists (task instructions §4).

## What never gets merged

A root/parent aggregate's own `summary_payload` never contains a blended or averaged
parameter/observable value. Each child's own contribution is only ever visible by descending
into *that child's own* aggregate (via its `aggregate_id`), tagged by its own `module_id` --
two sibling modules fitting entirely different, incompatible parameters are reported side by
side, never combined into one number (verified directly:
`test_incompatible_parameters_are_listed_separately_never_merged`).

## Summary payload shape

```json
{
  "target_model_module_id": "<uuid>" | null,
  "module_id": "<str>" | null,
  "execution_kind": "SIMULATION" | "CALIBRATION" | "VALIDATION",
  "completeness_status": "COMPLETE" | "PARTIAL" | "EMPTY",
  "own_result": {
    "run_record_id": "<uuid>",
    "status": "SUCCEEDED" | "FAILED" | ...,
    "execution_snapshot_id": "<uuid>" | null,
    "error_summary": "<str>" | null,
    // + kind-specific diagnostics: overall_status/module_handoff_summary (SIMULATION);
    // calibration_status/objective_before/objective_after/parameter_estimates (CALIBRATION);
    // validation_overall_status/calibrated_parameter_ids_checked/validation_metrics/
    // experiment_scores (VALIDATION)
  } | null,
  "children": [
    {"model_module_id", "module_id", "aggregate_id", "aggregate_version", "completeness_status"},
    ...
  ],
  "missing_or_failed_children": ["<module_id>", ...],
  "provenance": {
    "own_run_record_id": "<uuid>" | null,
    "own_execution_snapshot_id": "<uuid>" | null,
    "contributing_child_aggregate_ids": ["<uuid>", ...]
  }
}
```

Each kind-specific diagnostic is a *compact* extraction (fitted values, standard errors,
objective before/after, overall status, experiment scores, ...), never the full raw
`agent3_report`/`agent4_report`/`agent5_report` re-embedded -- keeps payload size reasonable
while still carrying the substance task instructions §3 names.

## Provenance: full traceability without re-deriving topology

Each level's own payload only names its *direct* contributions plus its children's own
aggregate ids -- never the full transitive closure. `get_aggregate_provenance` recursively
walks those `aggregate_id` links (re-fetching each referenced `ModuleAggregate` row) to
produce the fully flattened set: every contributing `run_record_id`, `execution_snapshot_id`,
`model_module_id`, and `aggregate_id` anywhere in the subtree. This is what the real
integration test uses to confirm every reported summary item is traceable to its real source.

## API

`app.orchestration.module_aggregation_orchestrator`:

* `build_module_aggregate(*, model_module_id, execution_kind, session)` / `build_root_aggregate
  (*, hierarchy_run_record_id, execution_kind, session)` -- build or idempotently return the
  current aggregate for a target, recursively ensuring every descendant's own aggregate is
  current first.
* `get_latest_module_aggregate(session, model_module_id, execution_kind)` / `get_latest_root
  _aggregate(session, hierarchy_run_record_id, execution_kind)` -- retrieve without building.
* `list_module_aggregate_versions(session, model_module_id, execution_kind)` -- every version
  on file, oldest first.
* `read_aggregate_summary(aggregate)` -- decode one aggregate's own payload.
* `get_aggregate_provenance(session, aggregate)` -- the full, recursively-flattened provenance
  set described above.

## Tests

`tests/persistence/test_module_aggregate.py` (8 tests): creation, idempotency by fingerprint,
new-fingerprint versioning, independent per-kind version sequences, root-aggregate querying,
absent-aggregate handling, fresh-session reload.

`tests/orchestration/test_module_aggregation_orchestrator.py` (15 tests): aggregation from
multiple complete children; mixed success/missing and success/failed children (`PARTIAL`);
all-missing children (`EMPTY`); three-level recursive roll-up (root -> modA -> modA1, built
via one top-level call); the own-result-plus-empty-child regression guard; independent
per-kind aggregation; incompatible-parameter non-merging; full provenance traceability;
idempotent rebuild; new-child-run produces a new version while the old one stays untouched;
fresh-session reload; unknown-module/unknown-hierarchy-run rejections -- plus **one realistic
integration test** (`test_real_aggregation_smoke_from_two_independently_executed_modules`)
driving two *really*, independently executed module-level results (a real Agent2->Agent3
->Agent4 calibration of one sibling module, a real Agent2->Agent3 simulation of the other -- genuinely
different execution kinds) through the sibling harness repository, then building the
`CALIBRATION` and `SIMULATION` root aggregates purely in-process (no agent/harness call of its
own) and confirming every reported summary item -- the real fitted parameter value, the real
`RunRecord`/`ModuleExecutionSnapshot` ids -- is traceable via `get_aggregate_provenance`.

Full Workbench suite passes with no regressions (257 pre-existing + 23 new = 280); the full
Harness suite and every Agent repository are unaffected (this increment makes zero changes to
any of them, confirmed by `git status`); lint and format clean.

## Remaining scientific limitations

* No cross-module scientific reconciliation of any kind -- a `COMPLETE` aggregate states only
  that every contributing branch succeeded, never that the resulting collection of
  independently-calibrated/validated modules forms a single, globally consistent, or globally
  valid model (task instructions §4's own explicit constraint).
* "Most recent successful attempt" is the only own-result selection rule; there is no notion
  of picking a "best" result among several successful attempts by any quality metric.
* No hierarchical hierarchical-*search* aggregation (candidate scoring, `ModuleCalibrationEvaluation`,
  etc.) is touched or reused here -- this is a separate, purely post-hoc reporting layer over
  already-accepted, already-materialized modules.
* No dynamic-coupling implementation, no GUI (both explicitly out of scope, unchanged).
