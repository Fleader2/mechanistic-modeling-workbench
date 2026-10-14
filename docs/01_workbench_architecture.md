# Workbench Architecture

## The one-sentence boundary

> The Workbench owns persistent user/project/workflow state and the user
> interface. It does not own scientific agent logic.

Everything else in this document exists to make that sentence operational.

## Origin

This repository was created from a read-only architecture audit of the
existing five-agent biochemical-modeling system
(`agent1-biochemical-curator`, `agent2-antimony-builder`,
`agent3-simulation-diagnostics`, `agent4-calibration-estimator`,
`agent5-validation-experimental-design`) plus the `agent-integration-harness`.
That audit found:

* Every agent repository (2-5) and the harness is **completely stateless** --
  no database, no ORM, no migrations anywhere. Agent 1 was, until this
  repository existed, the *only* repository with persistence.
* Agent 1's own migration `0020_project_subproject_model` had added
  `Project`/`Subproject`/`ModelSpecification`/`ModelingDecision`/`Model`
  tables that were never exposed through Agent 1's own versioned contract
  (`AGENT1_CONTRACT_VERSION`) and consumed by nobody -- real schema, with
  zero real consumers, because it was answering a workflow-orchestration
  question ("what modeling task is this?", "has the user decided X yet?"),
  not Agent 1's own chartered question ("what biochemical knowledge is
  supported by evidence?").
* Agent 2 already has its own, unrelated, in-memory type also called
  `ModelSpecification` -- meaning "the complete assembled executable
  model," nearly the opposite end of the pipeline from what Agent 1's
  table of the same name meant. This repository's `ModelBuildRequest`
  table is the renamed, Workbench-owned replacement for Agent 1's retired
  concept, specifically chosen to never collide with Agent 2's name again.

This repository is the direct implementation of that audit's own
recommended target architecture.

## Repository boundary diagram

```
                    ┌───────────────────────────┐
                    │  Workbench (UI + own DB)   │   <- this repository
                    │  Project / Subproject      │
                    │  ModelBuildRequest         │
                    │  ModelingDecision/Options  │
                    │  Model (artifact pointer)  │
                    │  RunRecord / DatasetRef.   │
                    └─────────────┬──────────────┘
                                  │ invokes (app.orchestration.run_orchestrator;
                                  │ see docs/03_workbench_harness_contract.md)
                                  ▼
                    ┌───────────────────────────┐
                    │     Integration Harness     │
                    │ subprocess orchestration   │
                    │ contract-version matrix    │
                    │ end-to-end invariants       │
                    └─────────────┬──────────────┘
         ┌───────────┬────────────┼────────────┬───────────┐
         ▼           ▼            ▼            ▼           ▼
   ┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐
   │ Agent 1  ││ Agent 2  ││ Agent 3  ││ Agent 4  ││ Agent 5  │
   │ curator  ││ builder  ││ sim/diag ││calibrate ││ validate │
   │  (DB)    ││(stateless)││(stateless)││(stateless)││(stateless)│
   └──────────┘└──────────┘└──────────┘└──────────┘└──────────┘
     each boundary a versioned, one-way data contract -- unchanged
     by this repository's existence
```

## What the Workbench owns

* `Project` -- the container a user manages: identity, title, lifecycle
  status, and a **one-time copy** of whatever biological framing Agent 1
  told it (organism, strain, disease/tissue/cell type) -- never a live
  foreign key into Agent 1's database, which this repository cannot reach
  and must never assume it can reach.
* `Subproject` -- which stage of the five-agent pipeline one modeling
  effort is currently driving (`task_type`). Pure orchestration metadata.
* `ModelBuildRequest` (+ eight child tables) -- what the user wants built,
  referencing Agent-1-resolved entities by copied id, never a foreign key.
  Preserves unresolved raw identifiers for later Agent 1 resolution.
* `ModelingDecision` / `ModelingDecisionOption` -- the human-in-the-loop
  reconciliation workflow for competing modeling alternatives.
* `Model` -- a reference/version/lineage pointer row. **Never the
  executable model content itself** -- that remains Agent 2's (currently
  in-memory, never persisted) responsibility. `artifact_reference` is an
  opaque string naming wherever the real content currently lives; the
  Workbench never parses or interprets it.
* `RunRecord` -- durable workflow execution history: which stage ran, for
  which subproject, with what status and what artifact/contract version.
  A durable version of what the integration harness today only keeps as
  gitignored, regenerable run output.
* `DatasetReference` -- a catalog entry for an uploaded or externally
  referenced dataset, never the dataset's own content.
* The user interface (not implemented in this increment).

## What the Workbench must NOT implement

Per the task's own explicit boundary, confirmed by the architecture audit:

* biochemical curation, normalization, or any KEGG/OmniPath/PhosphoSitePlus
  (or similar) connector logic -- stays Agent 1;
* Antimony construction, parsing, or any executable-model representation
  -- stays Agent 2;
* simulation or diagnostics -- stays Agent 3;
* parameter fitting/calibration -- stays Agent 4;
* validation or experimental-design algorithms -- stays Agent 5;
* inter-agent contract-version enforcement, subprocess orchestration, or
  end-to-end invariant checking -- stays the Integration Harness.

No code in this repository imports another repository's Python package.
Every cross-repository reference is a plain, nullable
`(entity_type, entity_id)` or `(contract_version, ...)` pair -- a copied
identifier or a future versioned data handoff, never a live call, a shared
database, or a shared ORM.

## Modularization and the executable model

Per the same audit, the executable model network representation
(compartments, species, reactions, kinetic laws, parameters with bounds)
belongs to Agent 2, which already has equivalent in-memory types -- it
simply does not persist them anywhere yet. If that ever needs durable
storage, it belongs to Agent 2's own future increment, or to a future
Workbench-owned *opaque artifact store* holding Agent 2's serialized
output as a blob -- never a competing structured duplicate inside the
Workbench's own schema. `Model.artifact_reference` is deliberately a
plain string for exactly this reason: it points at the artifact without
ever becoming a second copy of its structure.

Modularization of the executable model is a later, separate concept
entirely outside this repository's scope -- it is a derived decomposition
of an executable whole-network model that Agent 2 (or a later increment)
would own, not something `ModelBuildRequest` expresses or anticipates.

## This increment's scope

Only the Workbench foundation: the fourteen persistent tables above, a
clean Alembic migration baseline, the matching persistence layer, tests,
and this document. No live agent calls, no UI, and no changes to any of
the five agent repositories or the integration harness. See
`docs/02_database_schema.md` for the full schema and
`app/contracts/` for the placeholder/interface-level shapes reserved for
future cross-repository wiring.

**Forward pointer (Scoped-Build Support increment).** The "future
contract" referenced above now exists and is wired end to end:
`app.orchestration.run_orchestrator.submit_subproject_run` invokes the
harness for real, and -- new in this increment -- a persisted
`ModelBuildRequest` can now actually scope what Agent 2 builds. See
`docs/03_workbench_harness_contract.md`'s own "`ModelBuildRequest` ->
Agent 2 scoped builds" section for the full contract, and
`app/contracts/agent2_build_request.py` for the serializer (no longer a
placeholder). The ownership boundary this document states above is
unchanged by that increment: the Workbench still never persists Agent
2's executable model content, and all scoping *logic* (what counts as a
contradiction, which constraints are supported) lives in Agent 2's own
`agent2-antimony-builder/app/agent2/build_request` package, not here --
the Workbench only serializes user intent and stores the warnings Agent
2 reports back.
