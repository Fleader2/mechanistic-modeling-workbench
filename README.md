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
