# Pin Module Validation Execution to the Calibration Snapshot's Boundary/Model Conditions

See `docs/10_module_level_agent5_validation.md` for the increment this one builds on and
supersedes the "boundary conditions used for validation are the module's current state"
behavior of.

## Goal

Ensure Agent 5 validates a calibrated `ModelModule` under the exact module/boundary conditions
that produced the selected Agent 4 calibration, by default -- a human revising a boundary
decision *after* calibration must never silently change what a validation run against that
calibration actually executes.

## Why this is a Workbench-only change

The harness's own module-validation contract/workflow (`app.harness
.module_validation_execution`, `scripts/run_workbench_module_validation_request.py`) already
accepts an arbitrary `attach_payload` (with its own `module_ports`) from the caller -- it has
no opinion about *where* that payload came from. Pinning is therefore entirely a question of
*which* `attach_payload`/`module_ports` the Workbench's own orchestrator constructs before
sending the request; nothing about the harness's own contract, entrypoint, or Agent 2/3/4/5
needed to change. This increment touches only `mechanistic-modeling-workbench`.

## What gets pinned, and from where

`ModelModule.attach_payload` itself (the `{"modularization_id", "module_ids", "memberships"}`
dict) is already immutable from the moment a module is materialized -- no persistence function
anywhere in this repository ever updates it. The one genuinely mutable input to Agent 2's own
materialization is the module's own resolved `module_ports` (derived from live
`ModuleBoundaryPort` rows, which a human *can* revise via `submit_boundary_decision` at any
time). Pinning therefore means: reconstruct `module_ports` from the *calibration run's own*
frozen record of what it used, not from the module's current `ModuleBoundaryPort` rows.

**Additive change to the calibration snapshot** (`app.orchestration
.module_calibration_orchestrator.request_module_calibration`): the exact `attach_payload`
(already including its own merged `module_ports` key) and the separate `module_ports_payload`
list it was built from are now also written into the calibration's own
`ModuleExecutionSnapshot.snapshot_payload`, verbatim, alongside the pre-existing
`boundary_ports` human-readable summary. This is purely additive -- no schema/migration change
(`snapshot_payload` is an opaque JSON `TEXT` column), and no behavior change to calibration
itself; re-verified against the full, unchanged calibration test suite (18/18 still pass).

**Reconstruction at validation time** (`app.orchestration.module_validation_orchestrator
._resolve_pinned_materialization_input`): reads `attach_payload`/`module_ports_payload` back
from the *originating calibration run's own* `ModuleExecutionSnapshot` (looked up by
`calibration_run_record_id`, the same id `request_module_validation` already required for the
frozen `agent4_report`) and uses them, byte-for-byte, as the materialization input sent to the
harness -- `build_attach_payload(module)`/`build_module_ports_payload(module, session)`
(which read the module's own *current* state) are never called on this path. A hash recomputed
from the reconstructed input is compared against the calibration snapshot's own recorded
`module_artifact_hash`; a mismatch is treated as a reconstruction failure (see below) rather
than trusted silently.

## API change

`request_module_validation` gained one new keyword parameter:

```python
pin_to_calibration_snapshot: bool = True
```

`True` (the default) is the behavior described above. `False` reproduces the *previous*
increment's own behavior exactly (`build_attach_payload`/`build_module_ports_payload` against
the module's current live state) -- kept as an explicit escape hatch for "an explicit future
workflow that genuinely wants to validate against current conditions instead" (task
instructions), not used by anything in this repository today.

## Failure behavior: fail clearly, never silently fall back

`_resolve_pinned_materialization_input` raises `ModuleValidationValidationError` -- caught by
the same pre-harness-call validation path every other rejection in this orchestrator already
uses, never a silent fallback to the module's current state -- when:

* the calibration run has no `ModuleExecutionSnapshot` at all (e.g. a calibration run that
  predates even the immutable-snapshot increment, if one somehow still existed); or
* that snapshot exists but lacks the `attach_payload`/`module_ports_payload` keys (e.g. a
  snapshot captured by calibration code that predates *this* increment); or
* the reconstructed input's own recomputed hash does not match what the calibration snapshot
  itself recorded (a defensive consistency check -- in practice this should never actually
  trigger, since the reconstruction is a pure byte-for-byte readback, but a real mismatch would
  indicate the snapshot data was corrupted or hand-edited, and "cannot reconstruct" is the
  honest response, never a best-effort guess).

## Provenance recorded on the validation's own snapshot

`ModuleExecutionSnapshot.snapshot_payload` (`execution_kind=VALIDATION`) now additionally
carries:

* `"pinned_to_calibration_snapshot"` -- `true`/`false`, which path was actually taken.
* `"calibration_snapshot_id"` -- the originating calibration run's own `ModuleExecutionSnapshot
  .id` (not just its `RunRecord.id`, already recorded as `"calibration_run_record_id"`) --
  `None`  when pinning was not used.
* `"pinned_module_artifact_hash"` -- the calibration snapshot's own recorded hash, confirmed
  (via the consistency check above) to equal the validation's own top-level
  `module_artifact_hash` column whenever pinning is active; `None` when pinning was not used.
* `"boundary_ports"` -- now the calibration-time frozen copy (read from the calibration
  snapshot) when pinned, or the module's current live state when not -- never a mix of the
  two.

## Tests

`tests/orchestration/test_module_validation_orchestrator.py` gained 6 new tests (19 -> 25):
`test_validation_uses_pinned_boundary_value_not_current_module_state` (calibrate under A,
revise to B, confirm the harness request still carries A);
`test_validation_with_pinning_disabled_uses_current_module_state` (the escape hatch, confirms
the pre-this-increment behavior remains reachable and correctly discloses
`pinned_to_calibration_snapshot=False`); `test_request_module_validation_rejects_calibration_run
_with_no_snapshot` and `test_request_module_validation_rejects_calibration_snapshot_missing
_pinned_fields` (both failure-clearly paths); `test_pinned_validation_fresh_session_reload
_preserves_pinned_behavior`; and an extension of `test_request_module_validation_creates
_immutable_snapshot` to assert the new provenance fields. The pre-existing
`_make_succeeded_calibration_run` test fixture was updated to build a real,
pinning-compatible `ModuleExecutionSnapshot` alongside its hand-built `RunRecord` (previously
it built neither) -- every other pre-existing test in the file (idempotent replay, multiple
runs, client-error-still-snapshots, the real end-to-end calibration-then-validation smoke test,
gating/validation rejections) continues to pass unchanged against the new, now-default, pinned
behavior.

**One real, end-to-end subprocess test**
(`test_real_pinning_smoke_validation_still_uses_calibration_time_boundary_value`): a real
hierarchy module is calibrated with its boundary species fixed at value A (10); the module's
own persisted boundary decision is then changed to B (777); a real validation request against
that same calibration run is sent through the real harness subprocess chain. The test reads
the harness's own on-disk materialized handoff artifact directly (the raw Antimony text is the
only place the actually-used boundary value is visible -- neither the Workbench's own
persisted snapshot summary nor the structured `parameters`/`species` arrays echo a boundary
species' own fixed value) and confirms the materialized Antimony text declares `const
<symbol>; <symbol> = 10;`, never `= 777;` -- proving the pinned value, not the current one,
reached Agent 2's own materialization and therefore Agent 5's own execution.

Full Workbench suite passes with no regressions (251 pre-existing + 6 new orchestration tests
= 257); Agent 5's own suite (44 tests) and the full Harness suite are unaffected (this
increment makes zero changes to either sibling repository); lint and format clean.

## Remaining gaps

* Pinning covers boundary ports/materialization input only. It does not (and cannot, without
  re-running Agent 2/3/4) pin the *calibrated parameter values themselves* against any
  structural change to the module's own membership (e.g. a hypothetical future increment that
  let a human add/remove a reaction from an already-calibrated module) -- out of scope here,
  and `attach_payload`'s own immutability already makes this scenario impossible today.
* The consistency hash-check can only detect a reconstruction mismatch; it cannot repair one.
  A corrupted/hand-edited snapshot is rejected, never partially trusted.
* No hierarchical aggregation, no dynamic-coupling implementation, no GUI (all explicitly out
  of scope, unchanged from prior increments).
