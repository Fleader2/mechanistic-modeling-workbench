# Automatic Hierarchical Recursive Modularization: Workbench Integration

See `docs/01_workbench_architecture.md` for the repository-boundary diagram this implements,
`docs/03_workbench_harness_contract.md` for the first (`FULL_PIPELINE`) Workbench<->Harness
contract this one is deliberately separate from, and
`agent-integration-harness/docs/15_workbench_hierarchical_recursion_contract.md` for that
repository's own copy of this document (the two are written independently, kept in sync by
hand -- neither repository imports the other's Python package).

## Goal

A single Automatic Hierarchical Recursive Modularization search
(`agent-integration-harness/app/harness/hierarchical_recursion
.run_hierarchical_recursive_modularization`) against a model Agent 2 already assembled,
submitted and persisted from the Workbench, with the full accepted module tree -- every node's
own acceptance decision, score, and stopping reason -- stored as first-class, queryable rows
rather than an opaque JSON blob a UI would have to parse to render anything.

## Contract types

`app/contracts/hierarchical_recursion.py` -- the Workbench's own, independently-maintained copy
of `agent-integration-harness/app/harness/workbench_contracts.py`'s own
`WorkbenchHierarchicalInvocationRequest`/`WorkbenchHierarchicalRunResult`/
`WorkbenchHierarchyNodeSummary`:

* `HierarchicalInvocationRequest` -- `run_id`, `project_id`, `subproject_id`,
  `contract_version`, `criteria_weights`/`search_policy`/`calibration_selection_policy`/
  `flat_orchestration_policy`/`recursion_policy` (plain dicts, forwarded unread and unparsed --
  the Workbench never needs to understand their internal shape to submit a run), optional
  `functional_evaluation_selection_policy`/`model_id`/`agent1_organism_id`/
  `input_artifact_references`.
* `HierarchyNodeSummary` -- one node, field-for-field identical to the harness's own report.
  This is the shape `app.persistence.hierarchy_node.create_hierarchy_nodes` persists, one row
  per entry.
* `HierarchicalRunResult` -- `status`, `root_model_id`, the *full* `nodes` tuple (never
  truncated), `total_nodes_created`/`total_functional_evaluations_used`/
  `total_calibration_runs_used`, `requires_user_review`, `pending_review_modules`, `error`/
  `summary`/`warnings`/`replayed`.

`CONTRACT_VERSION` (`"workbench-hierarchical-v1"`) must match the harness's own
`WORKBENCH_HIERARCHICAL_CONTRACT_VERSION` exactly, or the harness's hierarchical-recursion
canonical entrypoint rejects the request before running anything. Unrelated to
`app.contracts.harness.CONTRACT_VERSION` (the `FULL_PIPELINE` contract).

## Canonical execution path

`app.orchestration.hierarchical_run_orchestrator.submit_hierarchical_run` is the one,
documented entrypoint:

1. create (or replay) a `RunRecord` (`stage=RunStage.HARNESS` -- the identical stage the
   `FULL_PIPELINE` workflow already uses; a hierarchical-recursion run is distinguished from a
   `FULL_PIPELINE` one only by whether any `HierarchyNode` rows exist for it, never by a new
   `RunStage` value);
2. transition it `PENDING -> RUNNING`;
3. serialize `HierarchicalInvocationRequest` (`app.contracts.hierarchical_recursion`);
4. invoke the harness's hierarchical-recursion canonical entrypoint as a real subprocess
   (`app.orchestration.hierarchical_harness_client.invoke_hierarchical_harness`);
5. parse the `HierarchicalRunResult`;
6. on success, bulk-insert every `HierarchyNodeSummary` as its own `HierarchyNode` row
   (`app.persistence.hierarchy_node.create_hierarchy_nodes`) -- **before** marking the run
   terminal, so a `RunRecord.status == SUCCEEDED` always has its full node set already
   persisted;
7. transition the `RunRecord` to `SUCCEEDED` or `FAILED`.

No scientific logic lives in any of these five modules: none of them interpret, re-derive, or
repair any node's own acceptance decision -- they only move a `RunRecord` through its own state
machine and copy already-decided fields onto rows.

## First-class persistence: `HierarchyNode`

`app/models/hierarchy_node.py` -- one row per node of one hierarchical-recursion run, a
`CASCADE`-deleted child of `run_record` (a deleted run never leaves orphaned node rows behind,
unlike `run_record.model_id`'s own `RESTRICT` FK protecting a `Model` row's independent
lineage). Every field a UI needs to render the accepted module tree, stopped branches, scores,
and reasons is its own typed, queryable column (`depth`, `accepted`, `reason`,
`baseline_score`/`child_score` as real `NUMERIC` values, `branch_stopping_reason`,
`parent_modularization_id`/`parent_module_id`/`child_modularization_id`/`child_submodel_id` for
tree reconstruction) -- never only an opaque JSON blob. `child_module_ids` (a list) is the one
field still stored as a JSON-encoded `Text` column, matching `RunRecord.warnings`'s own
identical "store the encoded list, never interpret it here" convention: a UI needing a child
module's own id list already has every child node's own `parent_module_id`, so this column is
redundant provenance, not the tree's own structural backbone.

`app/persistence/hierarchy_node.py` -- `create_hierarchy_nodes` (bulk insert, always a fresh
run), `list_hierarchy_nodes_for_run` (depth-first ordered read, the order a UI needs to
reconstruct the tree by walking each row's own parent reference against an ancestor's own
`child_modularization_id`).

## No calibration dataset provider

Identical disclosed scope limit to the harness's own contract: the canonical entrypoint always
uses a calibration request provider that returns no dataset, so every `CALIBRATE` decision
resolves as `NO_DATASET_AVAILABLE`. Deciding what counts as a usable calibration dataset for an
arbitrary candidate module is Agent 5's own future job, out of scope here.

## Tests

* `tests/persistence/test_hierarchy_node.py` (4 tests): every field persists correctly;
  depth-first read ordering; one run's own nodes never leak into another's; `CASCADE` delete.
* `tests/orchestration/test_hierarchical_harness_client.py` (6 tests): every subprocess
  failure mode (missing repo/venv/entrypoint, timeout, missing/invalid output), and a valid
  result parses correctly -- all mocked, no real subprocess.
* `tests/orchestration/test_hierarchical_run_orchestrator.py` (6 tests), including **one real,
  live end-to-end test** (`test_real_end_to_end_run_succeeds_and_persists_hierarchy_nodes`) that
  invokes the actual sibling harness repository's hierarchical-recursion canonical entrypoint as
  a genuine subprocess -- which itself drives a real Agent 2 subprocess chain -- confirming a
  `RunRecord` reaches `SUCCEEDED` with its full `HierarchyNode` set persisted (root node
  accepted, correct lineage). This is the one place in this repository that exercises the
  Workbench -> Harness boundary for this increment. Every other test mocks
  `invoke_hierarchical_harness`.

Full Workbench suite: 104 passed (88 pre-existing + 16 new); lint clean.
