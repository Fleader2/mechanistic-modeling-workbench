# Hierarchical Review/Resume

See `docs/04_hierarchical_recursion.md` for the increment this one builds directly on top of,
and `agent-integration-harness/docs/15_workbench_hierarchical_recursion_contract.md` ("Resume
contract" section) for that repository's own copy of this document.

## Goal

Make a paused (`require_human_review=True`) hierarchical-recursion run a durable, resumable
Workbench workflow, while keeping every architectural boundary unchanged:

* the **Harness** owns recursive-modularization logic, the checkpoint's own shape, resume
  semantics, and Agent 2 orchestration -- none of it is duplicated here;
* the **Workbench** owns persistent workflow state, user review state, and artifact/provenance
  references -- it stores the harness's own checkpoint verbatim and moves a `RunRecord` through
  its own state machine, never reinterpreting the checkpoint's internal shape.

## Harness-side contract addition

The pre-existing Workbench<->Harness hierarchical-recursion contract
(`docs/04_hierarchical_recursion.md`) had no resume concept at all. This increment adds, on the
harness side only (`agent-integration-harness`):

* `WorkbenchHierarchicalRunResult.checkpoint: dict | None` -- the harness's own
  `app.harness.hierarchical_recursion.serialize_checkpoint(...)` dict, populated whenever
  `requires_user_review` is `True`.
* `WorkbenchHierarchicalResumeRequest`/`WORKBENCH_HIERARCHICAL_RESUME_CONTRACT_VERSION`
  (`"workbench-hierarchical-resume-v1"`, deliberately separate from the initial-invocation
  contract's own version) -- `run_id`, `checkpoint` (passed back verbatim), `decisions`
  (`{pending_id: "APPROVE"|"REJECT"}`).
* A second, genuinely separate canonical entrypoint,
  `scripts/run_workbench_hierarchical_resume_request.py`, wrapping
  `app.harness.hierarchical_recursion.resume_hierarchical_recursive_modularization` with the
  identical idempotent-replay-by-`run_id` discipline the initial entrypoint already has.

This Workbench repository's own `app/contracts/hierarchical_recursion.py` is the
independently-maintained mirror of that shape (`checkpoint` field, `HierarchicalResumeRequest`,
`RESUME_CONTRACT_VERSION`) -- never imported across repositories, kept in sync by hand like
every other contract in this system.

## Status model

`RunStatus` gains one new, non-terminal value: `REQUIRES_USER_REVIEW`, sitting between
`RUNNING` and (`SUCCEEDED`/`FAILED`):

```text
PENDING -> RUNNING -> REQUIRES_USER_REVIEW -> RUNNING -> ... -> SUCCEEDED | FAILED
                  \                                   /
                   -----------------------------------
                       (no pause: straight through)
```

`app.persistence.run_record.pause_run_for_review` (`RUNNING` -> `REQUIRES_USER_REVIEW`) and
`resume_run` (`REQUIRES_USER_REVIEW` -> `RUNNING`) are the two new transitions, mirroring
`start_run`/`complete_run`'s own existing discipline exactly (raise `ValueError` if the record
is not in the expected source status). No new `RunStage` value, no new table replacing
`RunRecord` -- a paused run is still just a `RunRecord` row, exactly like the task's own
instruction to "use existing Workbench status conventions where possible."

## Checkpoint persistence: `HierarchyCheckpoint`

One row per pause of one hierarchical-recursion `run_record` (`app/models/hierarchy_checkpoint.py`),
storing the harness's own checkpoint dict **verbatim** as JSON text (`payload`) -- this
repository never parses or interprets anything inside it except to pass it back, unchanged, to
the harness's own resume call. `checkpoint_version`/`policy_version`/`hierarchy_id` are
denormalized copies of three of that payload's own top-level fields, carried as their own
columns purely for inspection/filtering without parsing JSON.

Checkpoints are append-only: a run's first pause is `sequence=0`; each subsequent
resume-then-re-pause cycle adds one more row at `sequence+1`. The *current* checkpoint for a
run is the row with the maximum `sequence` (`app.persistence.hierarchy_checkpoint
.get_current_checkpoint_for_run`). `consumed_at` (`NULL` until a resume attempt actually uses
it) is the staleness guard: a second resume attempt against an already-consumed checkpoint is
rejected with `StaleCheckpointError`, never silently re-invoking the harness.

## Pending review items: `HierarchyPendingReviewItem`

One row per entry of one checkpoint's own `pending_review_modules` (`pending_id`,
`parent_node_id`, `module_id`, `depth`, `reaction_count`) -- every field a UI needs to list
pending modules is its own typed, queryable column, never only an entry inside
`HierarchyCheckpoint.payload` a UI would have to parse to render anything (the identical
"first-class row, not an opaque blob" precedent `HierarchyNode` already established).

## Review decisions: `HierarchyReviewDecision`

One row per `(pending_review_item, decision)`, `pending_review_item_id` itself unique (exactly
one decision ever exists per item). `app.persistence.hierarchy_review_decision
.submit_review_decision` is idempotent on resubmission of the *identical* decision (returns the
existing row, including under a concurrent-insert race via `session.begin_nested()`, mirroring
`app.persistence.model.persist_model`'s own race-handling convention); resubmitting a
*different* decision for an already-decided item raises `ValueError` -- a genuine conflict,
never silently overwritten. `app.orchestration.hierarchical_review_orchestrator
.submit_review_decision` adds one more check on top: a decision submitted against an item whose
own checkpoint was already consumed by a resume raises `StaleCheckpointError`.

## Idempotent node insertion across resume

A resumed run's own harness result always carries every already-completed `HierarchyNode`
forward unchanged (identical `node_id`), ahead of any genuinely new ones.
`app.persistence.hierarchy_node.create_hierarchy_nodes` was changed (Hierarchical Review/Resume
increment) to query already-persisted `node_id`s for the run first and insert only the new
ones -- the primary idempotency mechanism. A new `(run_record_id, node_id)` unique constraint
(migration `0004_checkpoint_review`) is a database-level backstop against a caller that fails to
filter, never relied on as the primary mechanism.

## Service layer: `app.orchestration.hierarchical_review_orchestrator`

* `get_hierarchical_run_status(session, run_record_id)` -- the run's own `RunRecord` plus its
  full, depth-first `HierarchyNode` set so far.
* `list_pending_review_items(session, run_record_id)` -- the run's own current, still-resumable
  pending items (`[]` if never paused, or if the current checkpoint was already consumed).
* `submit_review_decision(...)` -- record one APPROVE/REJECT decision (see above).
* `resume_hierarchical_run(*, run_record_id, session, ...)` -- the orchestration entrypoint:
  validates the run is `REQUIRES_USER_REVIEW`, validates every current pending item has exactly
  one decision (raises `ValueError` naming the first undecided one otherwise -- never defaults
  a missing decision), marks the checkpoint consumed *before* invoking the harness (so a
  concurrent/repeated call fails fast rather than double-invoking it), builds a
  `HierarchicalResumeRequest` from the stored checkpoint plus the decided
  `{pending_id: "APPROVE"|"REJECT"}` mapping, transitions `RUNNING`, invokes
  `invoke_hierarchical_harness_resume`, and shares `app.orchestration
  .hierarchical_run_orchestrator.persist_result_and_transition` with the initial-invocation path
  to insert new nodes and either pause again or complete.
* `get_final_hierarchy(session, run_record_id)` -- the run's own complete `HierarchyNode` set;
  raises `ValueError` if the run has not reached `SUCCEEDED`.

`app.orchestration.hierarchical_run_orchestrator.submit_hierarchical_run` itself gained the
pause branch: when the harness's own result reports `requires_user_review=True`, it persists a
new `HierarchyCheckpoint` (+ its pending items) and calls `pause_run_for_review` instead of
`complete_run` -- the shared `persist_result_and_transition` helper this module now exports is
what both the initial call and every resume call funnel through.

## Provenance

Every accepted module's own stable identity and provenance already comes from the pre-existing
`HierarchyNode` schema (Automatic Hierarchical Recursive Modularization increment): its own
`node_id`/row `id`, `child_submodel_id`/`child_modularization_id` (the Harness/Agent 2
artifact reference), and `parent_modularization_id`/`parent_module_id` (reconstructable
parent/child lineage, walked against an ancestor's own `child_modularization_id`) -- all
carried forward unchanged across any number of pause/resume cycles for the identical
`run_record_id`. No new `Model` row is created per accepted module in this increment --
module-level Agent 3/4/5 execution (where a `Model` row would represent an independently
calibratable/simulatable artifact) is the next increment's own explicit scope, not this one's.

## Tests

* `tests/persistence/test_hierarchy_checkpoint.py` (7 tests), `test_hierarchy_pending_review_item.py`
  (4 tests), `test_hierarchy_review_decision.py` (5 tests): every field persists correctly,
  current-checkpoint-by-sequence lookup, consumption/staleness, uniqueness constraints,
  decision idempotency/conflict, `CASCADE` delete.
* `tests/persistence/test_hierarchy_node.py` gained one new test: a second
  `create_hierarchy_nodes` call that re-reports an already-persisted `node_id` inserts only the
  genuinely new ones.
* `tests/orchestration/test_hierarchical_review_orchestrator.py` (15 tests): start -> pause ->
  persist checkpoint; reload (via `session.expire_all()`) and reconstruct pending state;
  approve -> resume -> complete; reject branch; mixed approve/reject; repeated/idempotent
  review submission (identical resubmission is a no-op, conflicting resubmission raises,
  resuming twice never re-invokes the harness); invalid/stale checkpoint or decision
  (`StaleCheckpointError`, undecided-item `ValueError`, wrong-status `ValueError`);
  parent/child/root provenance integrity after resume; no duplication of the root node across
  pause and resume; final-hierarchy retrieval (and its own `ValueError` for a non-`SUCCEEDED`
  run) -- including **one real, live end-to-end test**
  (`test_real_end_to_end_pause_persist_reload_approve_resume_complete`) that drives the actual
  sibling harness repository as a genuine subprocess twice (initial invocation, then resume),
  which itself drives a real Agent 2 subprocess chain each time -- the one place in this
  repository that exercises the Workbench -> Harness boundary for this increment. Every other
  test mocks `invoke_hierarchical_harness`/`invoke_hierarchical_harness_resume`.

Full Workbench suite: 136 passed (104 pre-existing + 32 new); lint clean. Harness suite
(sibling repository): 164 passed; lint clean.

## Remaining gaps

* No GUI -- explicitly out of scope for this increment.
* No module-level Agent 3/4/5 execution against an accepted module -- explicitly deferred to
  the next increment, per its own instructions.
* `decided_by` is free text (no authentication/user-account system exists yet anywhere in this
  Workbench).
* A resume attempt that fails mid-flight (a true process crash between marking a checkpoint
  consumed and the harness subprocess actually returning) leaves that checkpoint consumed with
  the `RunRecord` stuck at `RUNNING` -- there is no automatic "unstick" path yet; recovering
  from that specific failure mode would need its own, separate operational tooling, out of
  scope here (the harness's own canonical entrypoint is already idempotent by `run_id`, so a
  clean *retry of the harness call itself* is always safe -- this gap is specifically about the
  Workbench-side `RunRecord`/checkpoint bookkeeping around that call).
