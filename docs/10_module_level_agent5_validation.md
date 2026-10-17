# Module-Level Agent5 Validation and Experimental Design

See `docs/09_module_level_agent4_calibration.md` for the increment this one builds on, and
`agent-integration-harness/docs/19_workbench_module_validation_contract.md` for that
repository's own copy of this document.

## Goal

Let Agent 5 validate a selected, already-calibrated `ModelModule` against independent
experimental observations and recommend informative follow-up experiments, preserving
complete scientific provenance -- without re-running Agent 3 or Agent 4, and without
fabricating validation data or an unsupported uncertainty claim.

## Agent 5 never re-calibrates; the prior calibration's own frozen report is reused

Agent 5's own contract (`ValidationRequest`) carries no model, no prior-calibration result,
and no training observations -- those live in the separate `Agent5Handoff`
(`{"agent2_model", "agent4_report"}`, built by the harness's own existing, unchanged
`build_agent5_handoff`, the identical function the whole-model `FULL_PIPELINE`'s own stage4->
stage5 transition already uses). Agent 5 reads the handoff's `agent4_report.calibration
.parameter_estimates` itself and applies them internally when simulating -- the Workbench
never needs to "bake in" calibrated values, and Agent 2's own fresh materialization of the
module (deterministic given the same `attach_payload`) is always the *original*, uncalibrated
structural model, exactly as the whole-model pipeline's own stage2->stage5 wiring already
works. `app.orchestration.module_validation_orchestrator.request_module_validation` therefore
requires an explicit `calibration_run_record_id` naming a prior, already-**SUCCEEDED**
`RunStage.AGENT4` `RunRecord` for *this exact module* -- its own `agent4_report` is read from
`RunRecord.artifact_reference` and passed straight through; Agent 3/Agent 4 are never
re-invoked.

## Why a new harness module, not `module_calibration_execution.py`

`app.harness.module_validation_execution` (new) reuses the identical building blocks
(`app.harness.module_simulation.materialize_module_handoff`,
`app.harness.adapters.build_agent5_handoff`, `runners/run_agent5.py`) without touching
`module_calibration_execution.py` or `module_calibration.py` at all -- this workflow's own
request shape (`agent4_report` supplied directly, no `calibration_request` built) is
genuinely different from calibration's own (`calibration_request` built, Agent3+Agent4 both
invoked), so a separate, parallel module is the correct shape rather than a conditional branch
inside the existing one.

## Schema

* `ModuleExecutionKind.VALIDATION` (new enum value, migration `0009_validation_execution_kind`
  -- a one-way PostgreSQL addition, identical precedent to `RunStatus.REQUIRES_USER_REVIEW`'s
  own prior migration). No new table or column: `module_execution_snapshot` (from the prior
  increment) was already designed generic over every `ModuleExecutionKind` value.
* `app.persistence.model_module.known_component_ids_by_type` and
  `app.persistence.module_execution_snapshot.compute_module_artifact_hash` were extracted
  (not duplicated) from `module_calibration_orchestrator.py`'s own prior private copies, now
  shared by both the calibration and validation orchestrators -- a small, behavior-preserving
  refactor (re-verified against the full, unchanged calibration test suite).

## Validation readiness

`request_module_validation` requires, in order: (1) `module.execution_status is
SIMULATION_READY` (identical gate to `request_module_simulation`/`request_module_calibration`
-- "compatible executable module"); (2) `calibration_run_record_id` names an existing,
`SUCCEEDED`, `RunStage.AGENT4` `RunRecord` whose own `model_module_id` matches this module --
"a valid module calibration result"; (3) `validation_request` is structurally complete (at
least one independent observation, matching `time_points`/`values` lengths) and every
observation's `target_species_id` (and every candidate experiment's `target_id`) is a real
member of this module's own durably-recorded membership (never a harness round-trip, never a
fabricated id); (4) **independence**: if `dataset_reference_ids` is supplied, none of them may
already appear in the *originating calibration run's own* snapshot's `dataset_references` --
the same dataset can never be used as both calibration input and the "independent" validation
evidence for one calibration-validation pair. All four rejections raise before any harness
call, as `ValueError`/`ModuleValidationValidationError`, never fabricating a measurement or
species/parameter id to make a request pass.

## Immutable execution snapshot

Created once per `RunRecord` (`execution_kind=VALIDATION`), before the harness is invoked,
following `request_module_calibration`'s own established pattern exactly. Captures:

* `module_artifact_hash` -- the shared, deterministic hash (see Schema above).
* `snapshot_payload["boundary_ports"]` -- a frozen copy of the module's own resolved boundary
  ports at the moment of this request (never affected by a later decision change).
* `snapshot_payload["calibration_run_record_id"]` -- the originating calibration run's own id.
* `snapshot_payload["calibrated_parameters"]` -- a frozen copy of that run's own
  `agent4_report.calibration.parameter_estimates` -- since the calibration `RunRecord` is
  itself terminal and never updated after completion, this copy is already stable by
  construction; copying it by value here (rather than a live join) makes that guarantee
  explicit and self-contained.
* `snapshot_payload["validation_config"]` -- the exact `ValidationRequest`-shaped dict sent to
  Agent 5.
* `snapshot_payload["dataset_references"]` -- a frozen copy of every referenced
  `DatasetReference`, when supplied.
* `snapshot_payload["module_handoff_summary"]`/`["parameters"]`/`["species"]` -- present only
  once the harness call actually completes.

Verified directly: a later `submit_boundary_decision` call revising the same port never
touches an already-created snapshot (`test_snapshot_survives_a_later_boundary_decision
_change`); a later change to the *calibration result itself* is structurally impossible to
retroactively affect a validation snapshot either, since the calibrated-parameters copy was
taken by value at validation-request time, never re-read from the (also-immutable) calibration
`RunRecord` afterward.

## Agent 5 handoff

`request_module_validation` resolves the module's own stored `attach_payload`, merges its
*current* resolved boundary ports in as `module_ports` (reused verbatim from
`app.orchestration.module_boundary_orchestrator.build_module_ports_payload`), and sends both
that payload and the originating calibration's own `agent4_report` plus the caller's own
`validation_request` dict through the harness's new module-validation canonical entrypoint.
Agent 5 therefore always validates the module's own standalone artifact -- never the root
model -- against the exact calibration result the caller named, never a different module's or
a stale one.

**Superseded by the Boundary-Condition Pinning increment** (see
`docs/11_module_validation_boundary_pinning.md`): by default, boundary conditions used for
validation are now the *calibration-time* conditions, read back verbatim from the
originating calibration run's own immutable snapshot -- never the module's current, possibly
since-revised state. An explicit `pin_to_calibration_snapshot=False` escape hatch still
reproduces this document's own originally-described behavior (validate under the module's
*current* live conditions) for a future workflow that genuinely wants that.

## Persistence

Agent 5's full, verbatim report lands in `RunRecord.artifact_reference`'s own JSON
(`{"module_id", "modularization_id", "calibration_run_record_id", "agent5_report"}`), cleanly
separated from the immutable snapshot (snapshot = *conditions*, `RunRecord` = *outcome*),
identical to the calibration increment's own established split. Repeated validation against
the same calibration result with different independent datasets creates a new `RunRecord` +
snapshot pair every time, never overwriting an earlier one
(`test_multiple_validation_runs_each_get_their_own_record_and_snapshot`).
`list_validation_runs(session, model_module_id)` retrieves every Agent5 run for a module,
newest first.

## Tests

`tests/orchestration/test_module_validation_orchestrator.py` (19 tests): the `SIMULATION_READY`
gate and unknown-module rejection; rejection of a missing/wrong-module/failed calibration run;
every validation rejection (empty/mismatched observations, unknown species/dataset-reference
ids, a dataset reused from the originating calibration run); a mocked happy-path confirming the
correct `agent4_report` and `validation_request` were sent and the result/snapshot correctly
linked and populated; snapshot immutability across a later boundary-decision change and a
fresh-session reload; multiple validation runs never overwriting each other; idempotent
replay; a client-level infrastructure failure recorded as `FAILED` while still snapshotting the
attempt; confirmation that an ordinary whole-model Agent5 run never sets `model_module_id` --
plus **one real, end-to-end test**
(`test_real_full_validation_smoke_uses_correct_calibrated_parameter_and_independent_data`)
continuing directly from a *real* Agent2->Agent3->Agent4 calibration (via
`module_calibration_orchestrator.request_module_calibration` itself, never a hand-crafted
stand-in) into a real Agent2->Agent5 validation: independent held-out observations (different
time points, same true dynamics) confirm Agent 5 actually used the correctly-fitted
`k_reaction-2_protein-2` and produced low validation residuals, and the persisted snapshot
confirms the correct calibration-run reference, frozen parameter value, and module-specific
artifact (2 of the root's 3 reactions/parameters).

Full Workbench suite, full Harness suite, and Agent 5's own suite all pass with no
regressions; lint and format clean in both repositories. Agent 2/3/4/5 repositories themselves
are untouched.

## Remaining scientific limitations

* No raw-observation-content independence check -- "independent validation data" is enforced
  only via `dataset_reference_ids` overlap (task instructions §2's own concrete, testable
  mechanism); nothing prevents a caller from pasting the identical numeric values into a
  validation request without going through a tracked `DatasetReference`. This is a disclosed
  gap, not a fabricated independence guarantee.
* ~~Boundary conditions used for validation are the module's *current* state, not pinned to
  what calibration itself used~~ -- resolved by the Boundary-Condition Pinning increment
  (`docs/11_module_validation_boundary_pinning.md`): pinned to the calibration's own snapshot
  by default.
* No hierarchical validation-result aggregation and no dynamic-coupling execution (explicitly
  out of scope, unchanged from prior increments).
* No GUI (explicitly out of scope).
