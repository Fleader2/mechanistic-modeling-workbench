# Mechanistic Modeling Workbench

The persistent user/project/workflow layer for the five-agent mechanistic
modeling system (`agent1-biochemical-curator` through
`agent5-validation-experimental-design`, orchestrated by the
`agent-integration-harness`).

> The Workbench owns persistent user/project/workflow state and the user
> interface. It does not own scientific agent logic.

See `docs/01_workbench_architecture.md` for the full architectural
rationale (this repository was created from a read-only architecture audit
of the existing five-agent system), `docs/02_database_schema.md` for the
complete schema, and `docs/03_workbench_harness_contract.md` for the
Workbench <-> Harness invocation/result contract and run lifecycle.

## This repository's scope (current increment)

* `Project`, `Subproject`, `ModelBuildRequest` (+ eight child tables),
  `ModelingDecision`/`ModelingDecisionOption`, `Model` (reference/lineage
  only, never executable content), `RunRecord`, `DatasetReference`.
* A clean PostgreSQL + SQLAlchemy + Alembic migration baseline.
* A matching persistence layer (idempotent create/reuse, lineage,
  resolution workflows, run lifecycle transitions).
* **Live wiring to the integration harness** (`app/orchestration/`):
  `submit_subproject_run` drives a real `RunRecord` through a genuine
  subprocess invocation of the harness's own canonical entrypoint
  (`agent-integration-harness/scripts/run_workbench_request.py`),
  idempotent replay, and deterministic failure handling. No scientific
  logic was added to either repository.
* **`ModelBuildRequest` -> Agent 2 scoped builds** (Scoped-Build Support
  increment): `submit_subproject_run(..., model_build_request_id=...)`
  serializes a persisted `ModelBuildRequest`
  (`app/contracts/agent2_build_request.py`, no longer a placeholder) and
  forwards it through the harness to a real Agent 2 subprocess, which
  restricts its own assembled network to that request's scope. Results
  (`RunRecord.model_build_request_id`/`RunRecord.warnings`) are
  persisted; Agent 2's executable model content is never copied into the
  Workbench's own database. See
  `docs/03_workbench_harness_contract.md` for the full contract and
  `agent2-antimony-builder/docs/20_scoped_build_support.md` for the
  canonical, cross-repository record of this increment.
* `app/contracts/agent1.py` remains a placeholder/interface-level
  contract shape reserved for future cross-repository wiring that
  remains unbuilt.
* **Automatic Hierarchical Recursive Modularization** (`HierarchyNode`, `app/orchestration
  /hierarchical_run_orchestrator.py`): a second, genuinely separate live wiring to the
  integration harness -- `submit_hierarchical_run` drives a real `RunRecord` through a genuine
  subprocess invocation of the harness's own second canonical entrypoint
  (`agent-integration-harness/scripts/run_workbench_hierarchical_request.py`), persisting the
  full accepted-module tree (every node's own acceptance decision, score, and stopping reason)
  as first-class, queryable `HierarchyNode` rows rather than an opaque JSON blob -- no UI yet,
  but no JSON-parsing required to build one later. See `docs/04_hierarchical_recursion.md`.
* **Hierarchical Review/Resume** (`HierarchyCheckpoint`/`HierarchyPendingReviewItem`/
  `HierarchyReviewDecision`, `app/orchestration/hierarchical_review_orchestrator.py`): makes a
  paused (`RunStatus.REQUIRES_USER_REVIEW`) hierarchical-recursion run a durable, resumable
  Workbench workflow -- the harness's own checkpoint is persisted verbatim, pending modules are
  first-class rows a UI can list, APPROVE/REJECT decisions are recorded idempotently, and
  `resume_hierarchical_run` passes the stored checkpoint plus decisions back to the harness's
  own second, genuinely separate canonical entrypoint
  (`agent-integration-harness/scripts/run_workbench_hierarchical_resume_request.py`). No
  resume/checkpoint logic is duplicated here -- every decision is still made entirely inside
  `app.harness.hierarchical_recursion`. See `docs/05_hierarchical_review_resume.md`.
* **Crash-Safe Resume** (`HierarchyResumeAttempt`, same orchestrator): closes the failure
  window where a checkpoint could be marked consumed before the harness resume call actually,
  durably succeeded. `resume_hierarchical_run` now owns two explicit transaction boundaries --
  commit a durable `IN_PROGRESS` attempt *before* invoking the harness, then persist the result
  and consume the prior checkpoint in one all-or-nothing transaction *after* -- so a crash
  during the (possibly multi-minute) subprocess call always leaves the checkpoint reusable and
  the attempt safely retryable, never a permanently stuck run. No Harness or Agent2/3/4/5
  changes. See `docs/06_crash_safe_resume.md`.
* **Executable-Module Materialization** (`ModelModule`, `app/orchestration/model_module
  _orchestrator.py`): turns accepted hierarchy modules into durable, idempotently-
  materialized execution targets with full provenance (root model, parent module, hierarchy
  run/node), distinct from an ordinary top-level `Model`. `request_module_simulation` reuses
  the harness's own new module-simulation canonical entrypoint to run a real Agent 3
  simulation against the *module's* own standalone artifact -- never the root model's, and
  never duplicating Agent 2/Agent 3 logic here. See
  `docs/07_executable_module_materialization.md`.
* **Boundary-Condition Semantics** (`ModuleBoundaryPort`, `app/orchestration/module_boundary
  _orchestrator.py`): makes a hierarchy module scientifically executable by deriving candidate
  boundary species from Agent 2's own reaction topology (structural facts only, never a
  fabricated treatment), persisting human (or future Agent4/5) treatment decisions with full
  provenance, and computing `ModelModule.execution_status`
  (`VIEW_ONLY`/`REQUIRES_BOUNDARY_REVIEW`/`SIMULATION_READY`). `request_module_simulation` now
  refuses a non-`SIMULATION_READY` module before ever invoking the harness, and merges the
  module's own resolved boundary ports into the materialization request. See
  `docs/08_boundary_condition_semantics.md`.
* **Module-Level Agent4 Calibration with Immutable Execution-Condition Provenance**
  (`ModuleExecutionSnapshot`, `app/orchestration/module_calibration_orchestrator.py`): lets a
  `SIMULATION_READY` module undergo real Agent 4 calibration against Workbench-supplied
  experimental data. Every calibration target/observation is validated against the module's
  own known membership before any harness call (never fabricated); an immutable snapshot of
  the exact resolved boundary ports, calibration configuration, and referenced datasets is
  captured for every attempt, before the harness is invoked, so a later change to any of those
  never alters a historical record. Repeated calibration with different data/boundary
  assumptions never overwrites an earlier result. See
  `docs/09_module_level_agent4_calibration.md`.
* **Module-Level Agent5 Validation and Experimental Design**
  (`app/orchestration/module_validation_orchestrator.py`): lets an already-calibrated module
  undergo real Agent 5 validation against *independent* held-out experimental data and receive
  experimental-design recommendations -- Agent 3/Agent 4 are never re-invoked; a prior,
  already-succeeded calibration run's own frozen report is reused as-is. Requires a valid
  `SUCCEEDED` calibration result for the exact module, rejects a validation dataset already
  used as calibration input, and captures its own immutable `ModuleExecutionSnapshot`
  (`execution_kind=VALIDATION`) before the harness is ever invoked. See
  `docs/10_module_level_agent5_validation.md`.
* **Boundary-Condition Pinning for module validation**: by default, `request_module
  _validation` now reconstructs the Agent 2 materialization input from the *originating
  calibration run's own immutable snapshot* -- never the module's current, possibly
  since-revised boundary state -- so a boundary decision changed after calibration never
  alters a validation run based on that calibration. An explicit `pin_to_calibration_snapshot
  =False` escape hatch still validates against current conditions when genuinely wanted. See
  `docs/11_module_validation_boundary_pinning.md`.
* **Hierarchical Aggregation of Module-Level Agent3/4/5 Results**
  (`app/orchestration/module_aggregation_orchestrator.py`): rolls up module-level simulation/
  calibration/validation results into durable, immutable, versioned parent/root summaries --
  recursively, using only the persisted hierarchy topology, never invoking any agent. Tracked
  separately per execution kind, never blended into one score; a root/parent summary never
  averages incompatible children's own parameters, always listing them side by side tagged by
  `module_id`. Idempotent by content fingerprint; a new/changed contributing result creates a
  new version, the old one is never mutated. See `docs/12_hierarchical_aggregation.md`.
* **Cross-Module Consistency and Reconciliation Diagnostics**
  (`app/orchestration/cross_module_diagnostics_orchestrator.py`): detects scientifically
  meaningful inconsistencies across sibling/parent-child modules -- shared boundary species
  fixed at conflicting values, incompatible units, the same parameter calibrated to
  different values, heterogeneous validation outcomes, unverifiable dataset contexts, and
  comparisons that cannot be concluded due to missing evidence -- without ever averaging,
  merging, or automatically reconciling a conflict, and without ever claiming the hierarchy
  is globally valid just because none was found. Immutable and versioned like
  `ModuleAggregate`; a finding's own review annotation is the one deliberately mutable field
  this Workbench adds anywhere. See `docs/13_cross_module_diagnostics.md`.

## Explicitly out of scope (owned elsewhere)

* Biochemical curation, normalization, KEGG/OmniPath/PhosphoSitePlus logic
  -- Agent 1.
* Antimony construction/parsing, executable model representation -- Agent 2.
* Simulation, diagnostics -- Agent 3.
* Parameter fitting/calibration -- Agent 4.
* Validation, experimental-design algorithms -- Agent 5.
* Inter-agent contract-version enforcement, subprocess orchestration,
  end-to-end invariant checks -- the Integration Harness.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in DATABASE_URL / TEST_DATABASE_URL

alembic upgrade head
pytest
ruff check .
ruff format --check .
```
