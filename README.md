# Mechanistic Modeling Workbench

The persistent user/project/workflow layer for the five-agent mechanistic
modeling system (`agent1-biochemical-curator` through
`agent5-validation-experimental-design`, orchestrated by the
`agent-integration-harness`).

> The Workbench owns persistent user/project/workflow state and the user
> interface. It does not own scientific agent logic.

See `docs/01_workbench_architecture.md` for the full architectural
rationale (this repository was created from a read-only architecture audit
of the existing five-agent system) and `docs/02_database_schema.md` for
the complete schema.

## This repository's scope (current increment)

* `Project`, `Subproject`, `ModelBuildRequest` (+ eight child tables),
  `ModelingDecision`/`ModelingDecisionOption`, `Model` (reference/lineage
  only, never executable content), `RunRecord`, `DatasetReference`.
* A clean PostgreSQL + SQLAlchemy + Alembic migration baseline.
* A matching persistence layer (idempotent create/reuse, lineage,
  resolution workflows, run lifecycle transitions).
* Placeholder/interface-level contract shapes for future cross-repository
  wiring (`app/contracts/`) -- **no live agent or harness calls exist
  yet**.

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
