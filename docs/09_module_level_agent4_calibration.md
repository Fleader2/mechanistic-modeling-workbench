# Module-Level Agent4 Calibration with Immutable Execution-Condition Provenance

See `docs/08_boundary_condition_semantics.md` for the increment this one builds on, and
`agent-integration-harness/docs/18_workbench_module_calibration_contract.md` for that
repository's own copy of this document.

## Goal

Let a Workbench `ModelModule` with `SIMULATION_READY` status undergo real Agent 4 parameter
calibration against experimental data, while preserving the exact model, boundary conditions,
parameters, and data used in each execution -- immutably, so a later change to a boundary
decision or a dataset's own catalog row never alters a historical record of what a completed
run actually used.

## Why a new harness module, not `app.harness.module_calibration`

The harness already routes one Agent2-*candidate* module through Agent 3 then Agent 4 for the
recursive hierarchy search's own scoring purposes (`app.harness.module_calibration`), mapping
Agent 4's own report down into a compressed `ModuleCalibrationEvaluation` -- deliberately
discarding per-estimate bounds/provenance, residual arrays, and optimizer diagnostics that
scoring heuristic has no use for. This increment's own consumer (a Workbench end user wanting
full calibration provenance for an already-durable, already-accepted module) needs the
opposite: the complete, verbatim `Agent3Report`/`Agent4Report` dicts, so nothing is lost before
it reaches the immutable snapshot below. Reusing the existing mapping would silently drop
exactly the fields persistence needs. `app.harness.module_calibration_execution` (new) instead
reuses `app.harness.module_simulation.materialize_module_handoff` (extracted, not duplicated,
from the prior increment's own Agent 2 materialization step) and the same
`runners/run_agent3.py`/`runners/run_agent4.py`/`app.harness.adapters.build_agent4_handoff`
building blocks `module_calibration.py` itself already reuses -- no new Agent 2/3/4 algorithm,
and `module_calibration.py` itself (the recursive search's own calibration semantics) is
completely untouched.

Validated, never fabricated: every calibration target/observation is checked against the
materialized module's own real `parameters`/`species` ids before Agent 3/Agent 4 are ever
invoked -- a request naming an unknown id is rejected with `ModuleCalibrationExecutionWorkflowError`.

## Schema

* `module_execution_kind` (new enum) -- `SIMULATION`/`CALIBRATION`. Only `CALIBRATION` is wired
  up by this increment.
* `module_execution_snapshot` (new table) -- one immutable row per module-scoped execution
  (`run_record_id` unique, 1:1), `ON DELETE RESTRICT` from both `model_module` and
  `run_record`. No `updated_at`, and no persistence function anywhere in this repository ever
  issues an `UPDATE` against it -- see migration `0008_module_execution_snapshot` and
  `docs/02_database_schema.md`'s own "Table: module_execution_snapshot" section for the full
  column list and `snapshot_payload`'s own contents.

## Calibration readiness and validation

`app.orchestration.module_calibration_orchestrator.request_module_calibration` gates on
`module.execution_status is SIMULATION_READY` -- identical to `request_module_simulation`'s
own gate. Before any harness call, `_validate_calibration_request` rejects (as
`ModuleCalibrationValidationError`, never a harness round-trip) a request with no targets, no
observations, a target naming a parameter/species the module does not have (checked against
the module's own durably-recorded `attach_payload["memberships"]`, filtered to this module's
own members -- a sibling module's memberships, also present in the same hierarchy node's
payload, are correctly excluded), an observation naming an unknown species, mismatched
`time_points`/`values` lengths, or a `dataset_reference_ids` entry that does not exist or
belongs to a different project. Nothing here fabricates a measurement, boundary value, or
kinetic parameter -- every rejection names a real, already-known id the request got wrong.

## Immutable execution snapshot

Created once per `RunRecord` (before the harness is ever invoked, so a snapshot exists even if
the call later fails), keyed 1:1 by `run_record_id` -- a repeated request for an
already-terminal `run_record_id` returns that row unchanged and never creates a second
snapshot. Captures:

* `module_artifact_hash` -- a `sha256` digest of the exact Agent 2 materialization input
  (`attach_payload` + its own merged, resolved `module_ports`), computed locally and always
  available regardless of harness outcome (never a hash of Agent 2's own *output*, which is
  only known after a successful round trip).
* `snapshot_payload["boundary_ports"]` -- a frozen copy of every `ModuleBoundaryPort`'s own
  `species_id`/`direction`/`treatment_type`/`initial_value`/`unit`/`value_source`/`decided_by`/
  `decided_at` *at the moment of this request* -- a later `submit_boundary_decision` call
  revising the same port never touches this copy (verified directly:
  `test_snapshot_survives_a_later_boundary_decision_change`).
* `snapshot_payload["calibration_config"]` -- the exact `CalibrationRequest`-shaped dict sent
  to Agent 4.
* `snapshot_payload["dataset_references"]` -- a frozen copy of every referenced
  `DatasetReference`'s own `name`/`dataset_type`/`artifact_reference`/`checksum`/
  `version_label`, when `dataset_reference_ids` was supplied.
* `snapshot_payload["contract_versions"]` -- this repository's own
  `app.contracts.module_calibration.CONTRACT_VERSION`.
* `snapshot_payload["module_handoff_summary"]`/`["parameters"]`/`["species"]` -- the
  materialized module's own real parameter/species arrays, present only once the harness call
  actually completes (absent for a run that failed before any artifact was materialized).

## Agent 4 handoff

`request_module_calibration` resolves the module's own stored `attach_payload`, merges its
resolved boundary ports in as `module_ports` (`app.orchestration.module_boundary_orchestrator
.build_module_ports_payload`, unchanged, reused verbatim), and sends both that payload and the
caller's own `calibration_request` dict through the harness's new module-calibration canonical
entrypoint. Agent 4 therefore always calibrates against the module's own standalone artifact --
never the root model -- with its own resolved, non-fabricated boundary treatment.

## Persistence

Agent 4's full, verbatim report (`{"module_id", "modularization_id", "agent4_report"}`) is
recorded in `RunRecord.artifact_reference`'s own JSON, identical to how `request_module
_simulation` already stores `agent3_report` -- a cleanly separate concern from the immutable
snapshot (snapshot = *conditions*, `RunRecord` = *outcome*). Repeated calibration against the
same module with a different dataset or boundary assumption creates a new `RunRecord` +
snapshot pair every time, never overwriting an earlier one
(`test_multiple_calibration_runs_each_get_their_own_record_and_snapshot`).
`list_calibration_runs(session, model_module_id)` retrieves every Agent4 run for a module,
newest first.

## Tests

`tests/persistence/test_module_execution_snapshot.py` (6 tests): creation, idempotency by
`run_record_id`, module-scoped listing, multiple runs each keeping their own row, fresh-session
reload.

`tests/orchestration/test_module_calibration_orchestrator.py` (18 tests): the `SIMULATION_READY`
gate and unknown-module rejection; every validation rejection (empty targets/observations,
unknown target/species/dataset-reference ids, mismatched observation shapes); a mocked
happy-path confirming the correct module-scoped `attach_payload`/`module_ports` were sent and
the result/snapshot correctly linked and populated; dataset-reference snapshotting; snapshot
immutability across a later boundary-decision change and a fresh-session reload; multiple
calibration runs never overwriting each other; idempotent replay; a client-level infrastructure
failure recorded as `FAILED` while still snapshotting the attempt; confirmation that an ordinary
whole-model Agent4 run never sets `model_module_id` -- plus **one real, end-to-end test**
(`test_real_full_calibration_smoke_recovers_true_parameter_and_persists_provenance`) driving
the sibling harness repository as a genuine subprocess chain: a real two-module split of the
synthetic fixture, with one species deliberately treated as an externally-controlled fixed feed
(a legitimate human modeling choice beyond the topologically-derived boundary) giving the
module real, non-degenerate dynamics; synthetic observations generated analytically from a
known true rate constant; a real Agent2->Agent3->Agent4 round trip recovers that constant
within 5% relative tolerance, and the persisted snapshot confirms both the module-specific
artifact (2 of the root's 3 reactions/parameters) and both resolved boundary species were what
was actually used.

Full Workbench suite: 232 passed (208 pre-existing + 24 new); Harness suite: 207 passed (194
pre-existing + 13 new); Agent 4's own suite: 64 passed, unaffected; lint and format clean in
both repositories. Agent 2/3/4 repositories themselves are untouched.

## Remaining scientific limitations

* Units are not independently validated. Neither Agent 4's own `CalibrationRequest`/
  `Observation` types nor `DatasetReference` carry a structured unit field to cross-check
  against -- validation here is limited to id existence and basic shape (matching
  `time_points`/`values` lengths), never a fabricated unit-consistency claim.
* No hierarchical calibration aggregation and no dynamic-coupling execution -- unchanged from
  the prior increment's own disclosed limitation, explicitly out of scope here too.
* No Agent5 integration (explicitly deferred).
* `ModuleExecutionSnapshot` is schema-ready for `execution_kind=SIMULATION` but
  `request_module_simulation` is not retrofitted to create one in this increment -- deliberately
  scoped out to avoid touching already-shipped, already-pushed behavior; a future increment can
  wire it in with zero migration.
* No GUI (explicitly out of scope).
