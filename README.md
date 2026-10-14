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
* Placeholder/interface-level contract shapes still reserved for future
  cross-repository wiring that remains unbuilt (`app/contracts/agent1.py`,
  `app/contracts/agent2_build_request.py`) -- the
  `ModelBuildRequest` -> Agent 2 gap is disclosed, not closed, in this
  increment (see `docs/03_workbench_harness_contract.md`).

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
