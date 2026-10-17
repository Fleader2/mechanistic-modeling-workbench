# Boundary-Condition Semantics

See `docs/07_executable_module_materialization.md` for the increment this one builds on, and
`agent-integration-harness/docs/17_workbench_module_boundary_derivation_contract.md` for that
repository's own copy of this document.

## Goal

Make hierarchy-derived `ModelModule`s scientifically executable by explicitly deriving,
representing, reviewing, and persisting how cross-boundary species are treated -- without
fabricating a scientific assumption anywhere, and without duplicating Agent 2's own
model-building logic in the Workbench.

## Why `ModulePort.externally_controlled` alone was not enough

The prior increment already let a caller supply `module_ports` by hand to make a module
simulatable (Agent 2's own `externally_controlled=True` boolean is the one mechanism that makes
a module standalone-executable). What was missing was everything *around* that boolean: where a
boundary candidate comes from, what treatment a human actually chose and why, whether that
choice survives reload, and whether a module is even allowed to reach Agent 3 before a human
has looked at it. This increment adds that layer -- `ModulePort`'s own vocabulary
(`direction`/`externally_controlled`/`initial_value`/`unit`) is reused verbatim, never
reinvented, for exactly the fields `ModuleBoundaryPort` shares with it.

## Schema

* Four new enums (`app/models/enums.py`): `ModulePortDirection` (`INPUT`/`OUTPUT`/
  `INPUT_OUTPUT` -- the Workbench's own copy of Agent 2's identical vocabulary),
  `ModuleBoundaryTreatmentType` (`EXTERNALLY_CONTROLLED`/`PRESCRIBED_INPUT`/`DYNAMIC_COUPLING`/
  `UNRESOLVED`), `ModuleBoundaryResolutionStatus` (`PENDING_REVIEW`/`RESOLVED`),
  `ModelModuleExecutionStatus` (`VIEW_ONLY`/`REQUIRES_BOUNDARY_REVIEW`/`SIMULATION_READY`).
* `model_module.execution_status` (new, non-nullable, default `VIEW_ONLY`) -- every
  pre-existing row is unaffected.
* `module_boundary_port` (new table) -- one row per `(model_module, species_id, direction)`
  (unique constraint), `CASCADE`-deleted from `model_module` (no independent meaning apart from
  the module it describes, unlike `model_module` itself, which stays `RESTRICT` everywhere).
  Columns: `port_id` (a stable, deterministic id, never Agent 2's own runtime-generated one --
  this row exists before any Agent 2 call is ever made), `species_id`, `direction`,
  `treatment_type` (default `UNRESOLVED`), `resolution_status` (default `PENDING_REVIEW`),
  `initial_value`/`unit`/`value_source`, `provenance_notes`, `derived_automatically` (default
  `True`), `decided_by`/`decided_at`.

See migration `0007_module_boundary_port`.

## Treatment classes and the standalone-capable mapping

`EXTERNALLY_CONTROLLED`/`PRESCRIBED_INPUT` both map to Agent 2's own
`ModulePort.externally_controlled=True` when passed to the harness's module-simulation
entrypoint -- distinguished here only for the Workbench's own richer scientific bookkeeping
(fixed/controlled vs. a prescribed input flux), never a difference Agent 2 itself acts on.
`DYNAMIC_COUPLING` is a genuine, resolved decision (`resolution_status=RESOLVED`) that a port
is coupled to its parent/external system rather than fixed -- and is never standalone-capable:
Agent 2 has no mechanism to simulate a module coupled to context it does not have, so a module
leaning on it stays `REQUIRES_BOUNDARY_REVIEW`, never `SIMULATION_READY`. `UNRESOLVED` is the
only value automatic derivation is ever allowed to assign (never fabricated); every other value
requires an explicit human (or, in a future increment, Agent4/5) decision.

## Derivation: structural only, never a treatment decision

`app.orchestration.module_boundary_orchestrator.derive_boundary_ports` asks the harness's new
module-boundary-derivation canonical entrypoint to compute candidate boundary species purely
from Agent 2's own reaction-participant topology (which species are touched by one of the
target module's own reactions *and* by a reaction belonging to a different module, or none) --
direction is derived structurally from internal participant roles (`REACTANT`/`MODIFIER` ->
`INPUT`, `PRODUCT` -> `OUTPUT`, both -> `INPUT_OUTPUT`). No reusable Agent 2 function already
computed this (confirmed by inspection of `derive_cross_module_connections`/
`compute_dependency_closure`/`score_topological_separation`); the harness's new runner script
replicates the small, pure graph computation the last of those already performs internally for
its own, unrelated scoring purpose -- no new Agent 2 algorithm, no model construction duplicated
in the Workbench. Every derived candidate is persisted as `UNRESOLVED`/`PENDING_REVIEW` --
structural fact only, never a scientific guess.

## Idempotency

`persist_candidate_boundary_ports` queries existing `(species_id, direction)` keys first and
creates only genuinely new rows; an already-known candidate (automatic or manually-decided) is
silently skipped, never touched -- the one mechanism that makes repeated derivation safe to
call after every resume/replay without ever overwriting a manual decision or duplicating a
port.

## Module execution status

`app.orchestration.module_boundary_orchestrator.evaluate_module_execution_status` recomputes
and persists `ModelModule.execution_status` from its current `ModuleBoundaryPort` rows: `VIEW_
ONLY` if none exist yet; `SIMULATION_READY` if every port is resolved to a standalone-capable
treatment; else `REQUIRES_BOUNDARY_REVIEW` (at least one port is still `UNRESOLVED` or resolved
to the non-standalone `DYNAMIC_COUPLING`). Called after every derivation and every decision, so
the column is always truthful, never cached stale.

## Service layer: `app.orchestration.module_boundary_orchestrator`

* `derive_boundary_ports(*, model_module_id, project_id, subproject_id, session, ...)` --
  routes to the harness, persists newly-found candidates, re-evaluates execution status.
  Raises `ModuleBoundaryDerivationError` only for a genuine harness/infrastructure failure --
  never for a module with zero cross-boundary species (a successful, disclosed empty result).
* `submit_boundary_decision(*, port_id, treatment_type, session, ...)` -- a thin wrapper
  around `app.persistence.module_boundary_port.submit_boundary_decision` that also re-evaluates
  the owning module's execution status, so a caller never has to remember to call that
  separately.
* `evaluate_module_execution_status(model_module, session)` -- the pure status rule above.
* `list_boundary_ports`/`get_boundary_port_with_provenance` -- read helpers; provenance
  (`decided_by`/`decided_at`/`derived_automatically`/`provenance_notes`) is already present as
  plain columns, no separate assembly step.
* `build_module_ports_payload(model_module, session)` -- the `module_ports` list (the exact
  shape `run_agent2_materialize_module_handoff.py` already parses) to merge into an
  `attach_payload` sent to the harness, including only standalone-capable ports.

## Agent 3 handoff: gated and payload-merged

`app.orchestration.model_module_orchestrator.request_module_simulation` now raises `ValueError`
immediately -- before ever invoking the harness -- unless `model_module.execution_status` is
already `SIMULATION_READY`. When it is, the module's own resolved `ModuleBoundaryPort` rows are
merged into a *copy* of the stored `attach_payload` as `module_ports` (the stored
`ModelModule.attach_payload` column itself is never mutated); the existing Agent 2/Agent 3
materialization path (`run_agent2_materialize_module_handoff.py`, unchanged) consumes it exactly
as it already did for a hand-supplied payload.

## Tests

`tests/persistence/test_module_boundary_port.py` (11 tests): candidate creation; idempotent
re-derivation; a manual decision is never overwritten by re-derivation; `EXTERNALLY_CONTROLLED`/
`PRESCRIBED_INPUT`/`DYNAMIC_COUPLING` decisions; rejection of resolving to `UNRESOLVED` and of
an unknown port; module-scoping; `INPUT` vs `INPUT_OUTPUT` as distinct ports; fresh-session
reload.

`tests/orchestration/test_module_boundary_orchestrator.py` (13 tests): automatic boundary
detection (mocked harness) and its `REQUIRES_BOUNDARY_REVIEW` status; a zero-candidate result
is not an error; a harness client error is raised as `ModuleBoundaryDerivationError`;
re-derivation never duplicates ports or overwrites a manual decision; every treatment class's
own status effect, including dynamic-coupling staying non-standalone and a mixed resolved/
unresolved set staying `REQUIRES_BOUNDARY_REVIEW`; the full `VIEW_ONLY` -> `REQUIRES_BOUNDARY_
REVIEW` -> `SIMULATION_READY` transition; fresh-session reload of a decision and its status;
`build_module_ports_payload` including only standalone-capable ports -- plus **two real,
end-to-end tests** driving the sibling harness repository as a genuine subprocess chain: one
confirming the real topology-derived boundary candidate for a hand-split two-module fixture,
and **the one required full smoke path** -- hierarchy module -> real derivation -> a human
`EXTERNALLY_CONTROLLED` decision with an explicit value -> `SIMULATION_READY` -> real Agent 2
materialization -> real Agent 3 simulation -- which reads the harness's own on-disk module
handoff artifact directly and confirms the human-supplied value (`2.5`) is exactly what Agent 2
declared (`const <symbol>; <symbol> = 2.5;`) for the resolved boundary species in the actual
simulated Antimony text (Agent 3's own report never echoes a constant boundary species' value,
since it is not part of the simulated ODE state -- the Antimony text is the only place this is
actually visible).

`tests/orchestration/test_model_module_orchestrator.py` (14 tests, 2 new): a `VIEW_ONLY` and a
`REQUIRES_BOUNDARY_REVIEW` module are both rejected before the harness is ever invoked; every
previously-mocked happy-path test now resolves its module to `SIMULATION_READY` first; the
real end-to-end test (previously asserting a harness-reported `MODULE_SIMULATION_FAILED`) now
asserts the *stronger*, pre-flight `ValueError` -- no subprocess is invoked at all for a module
with no boundary treatment.

Full Workbench suite and Harness suite both pass with no regressions; both repositories' lint
and format checks are clean.

## Remaining scientific ambiguities

* Direction derivation is purely structural (which role a species plays in the target module's
  own reactions) -- it says nothing about *why* a species crosses the boundary or what its real
  biological boundary condition should be. That judgment is deliberately left to a human (or a
  future Agent4/5 increment); this increment never guesses it.
* `DYNAMIC_COUPLING` is representable and distinguishable from `UNRESOLVED`, but there is no
  mechanism yet to actually *execute* a dynamically-coupled module against its parent/external
  system -- Agent 2/Agent 3 have no such capability today, so a module resolved this way stays
  `REQUIRES_BOUNDARY_REVIEW` by design, not a gap in this increment specifically.
* No GUI (explicitly out of scope). No Agent4/Agent5 automatic resolution (explicitly deferred).
