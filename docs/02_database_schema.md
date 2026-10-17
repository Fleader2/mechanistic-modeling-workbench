# Workbench Database Schema

See `docs/01_workbench_architecture.md` for the architectural rationale.
This document is the single source of truth for every enum's value list
and every table's column list -- enums/models are transcribed from here,
never invented ad hoc in code.

## Conventions

* Every table has a UUID primary key (`id`, generated client-side via
  `uuid4()`).
* Lifecycle tables (ones a user or workflow revises over time) carry
  `created_at`/`updated_at`; append-only/provenance tables
  (`model_build_request_species` and its sibling child tables,
  `run_record`) carry `created_at` only; pure join tables carry neither.
* `ON DELETE RESTRICT` is the default for every foreign key. `CASCADE` is
  reserved for a child table whose rows have no independent meaning apart
  from the parent they describe (see "Delete Behavior" below).
* Every reference to a biological entity owned by Agent 1 (a compound, a
  reaction, a gene, a protein, a compartment, a regulatory interaction, an
  enzyme state, an organism) is a plain, nullable `(entity_type,
  entity_id)` pair or a single `agentN_*_id` column -- **never a foreign
  key**. There is no such thing as a cross-database foreign key in
  PostgreSQL, and even if there were, the Workbench never assumes it can
  reach another repository's database.

## Enumerated Types

### ProjectType
```text
MICROBIAL_METABOLISM
REGULATORY_NETWORK
```

### WorkflowLifecycleStatus
Shared by `project.status` and `subproject.status`.
```text
ACTIVE
COMPLETED
ON_HOLD
ARCHIVED
```

### SubprojectTaskType
Which stage of the five-agent pipeline one subproject is driving.
```text
BUILD_MODEL
IMPORT_MODEL
TEST_MODEL
CALIBRATE_MODEL
EXTEND_MODEL
```

### ModelBuildRequestSpeciesRole
```text
INPUT
OUTPUT
BOUNDARY
SEED
```

### ModelBuildRequestReactionRole
```text
SEED
REQUIRED
EXCLUDED
```

### ModelBuildRequestGeneProteinRole
```text
SEED
IMPORTANT
```

### ModelBuildRequestPathwayRole
```text
INCLUDE
EXCLUDE
```

### ModelingDecisionStatus
```text
OPEN
RESOLVED
DEFERRED
```

### ModelingDecisionResolutionSource
```text
USER
AGENT
RULE
```

### ConfidenceClass
The Workbench's own copy of a vocabulary that also exists, independently,
in Agent 1.
```text
VERY_HIGH
HIGH
MODERATE
LOW
UNKNOWN
```

### ModelSourceType
```text
GENERATED
IMPORTED
DERIVED
```

### ModelStatus
```text
DRAFT
ACTIVE
SUPERSEDED
ARCHIVED
```

### RunStage
A closed vocabulary: the pipeline is fixed at exactly five agents plus the
integration harness.
```text
AGENT1
AGENT2
AGENT3
AGENT4
AGENT5
HARNESS
```

### RunStatus
```text
PENDING
RUNNING
REQUIRES_USER_REVIEW
SUCCEEDED
FAILED
```
`REQUIRES_USER_REVIEW` (Hierarchical Review/Resume increment) is a non-terminal pause between
`RUNNING` and (`SUCCEEDED`/`FAILED`) -- added as a new `run_status` enum value by migration
`0004_checkpoint_review` (one-way in PostgreSQL, identical precedent to
`agent1-biochemical-curator`'s `0016_gotenzymes_source`).

### HierarchyReviewDecisionValue
```text
APPROVE
REJECT
```

### HierarchyResumeAttemptStatus
Added by the Crash-Safe Resume increment (migration `0005_resume_attempt`). Modeled after
`RunStatus`'s own style, but a deliberately separate vocabulary -- see `docs/06_crash_safe_
resume.md`.
```text
PENDING
IN_PROGRESS
SUCCEEDED
FAILED
```

### ModulePortDirection
Added by the Boundary-Condition Semantics increment (migration `0007_module_boundary_port`) --
the Workbench's own copy of Agent 2's identical vocabulary, reused verbatim because it is
exactly the direction value the harness's own module-simulation entrypoint already expects in
an `attach_payload["module_ports"]` entry.
```text
INPUT
OUTPUT
INPUT_OUTPUT
```

### ModuleBoundaryTreatmentType
`UNRESOLVED` is the only value automatic derivation is ever allowed to assign -- every other
value requires an explicit human (or future Agent4/5) decision. `EXTERNALLY_CONTROLLED`/
`PRESCRIBED_INPUT` both map to Agent 2's own `ModulePort.externally_controlled=True`;
`DYNAMIC_COUPLING` is a genuine, resolved decision that is never standalone-capable. See
`docs/08_boundary_condition_semantics.md`.
```text
EXTERNALLY_CONTROLLED
PRESCRIBED_INPUT
DYNAMIC_COUPLING
UNRESOLVED
```

### ModuleBoundaryResolutionStatus
Kept consistent with `treatment_type` by the persistence layer alone, never a database
constraint: `PENDING_REVIEW` if and only if `treatment_type is UNRESOLVED`.
```text
PENDING_REVIEW
RESOLVED
```

### ModelModuleExecutionStatus
One `model_module`'s own readiness to be handed to Agent 3. `VIEW_ONLY` until
`derive_boundary_ports` is ever called; `SIMULATION_READY` only once every boundary port is
resolved to a standalone-capable treatment; else `REQUIRES_BOUNDARY_REVIEW`.
```text
VIEW_ONLY
REQUIRES_BOUNDARY_REVIEW
SIMULATION_READY
```

### ModuleExecutionKind
Added by the Module-Level Agent4 Calibration with Immutable Execution-Condition Provenance
increment (migration `0008_module_execution_snapshot`) -- which downstream agent one
`module_execution_snapshot` row's own execution was for. Denormalized from the owning
`run_record.stage` (`AGENT3`/`AGENT4`/`AGENT5`) at creation time. `VALIDATION` was added by the
Module-Level Agent5 Validation and Experimental Design increment (migration
`0009_validation_execution_kind`, a one-way enum addition). `SIMULATION` remains schema-ready
for a later increment to adopt without a migration. See
`docs/09_module_level_agent4_calibration.md`/`docs/10_module_level_agent5_validation.md`.
```text
SIMULATION
CALIBRATION
VALIDATION
```

### ModuleAggregateCompleteness
Added by the Hierarchical Aggregation of Module-Level Agent3/4/5 Results increment (migration
`0010_module_aggregate`) -- a pure coverage statement about one `module_aggregate` row's own
roll-up, never a quality/agreement judgment and never a blended score across heterogeneous
children. `COMPLETE` only when every "slot" (the target's own direct attempt, if any, plus
every direct child) succeeded/is itself `COMPLETE`; `EMPTY` only when none did; `PARTIAL`
otherwise. See `docs/12_hierarchical_aggregation.md`.
```text
COMPLETE
PARTIAL
EMPTY
```

### CrossModuleDiagnosticCategory
Added by the Cross-Module Consistency and Reconciliation Diagnostics increment (migration
`0011_cross_module_diagnostics`) -- a 1:1 mapping onto that increment's own seven numbered
detection requirements; every finding's own category already says which specific comparison
produced it. See `docs/13_cross_module_diagnostics.md`.
```text
SHARED_BOUNDARY_SPECIES_CONFLICT
UNIT_INCOMPATIBILITY
PARAMETER_ASSUMPTION_CONFLICT
PARENT_CHILD_BOUNDARY_INCONSISTENCY
DATASET_CONTEXT_INCOMPATIBILITY
CONFLICTING_CALIBRATION_OR_VALIDATION_OUTCOME
INSUFFICIENT_EVIDENCE_FOR_COMPARISON
```

### DiagnosticSeverity
No existing enum in this schema already carried this exact vocabulary (confirmed by
inspection before adding it). `UNRESOLVED` means the comparison itself could not be
concluded -- never silently skipped, and never treated as "no conflict."
```text
INFO
WARNING
ERROR
UNRESOLVED
```

### DiagnosticReviewStatus
Whether a human has reviewed one `cross_module_diagnostic` finding. Marking a finding
reviewed is the one deliberately mutable operation this increment adds anywhere -- it never
alters the finding's own detection content or any source record it describes.
```text
UNREVIEWED
REVIEWED
```

### UnitParseStatus
(Structured Units and Dimensional-Consistency Validation increment, migration
`0012_unit_resolution`.) Whether one raw unit string could be resolved against this
Workbench's own `pint` registry (`app.units`). `MISSING` (no unit recorded) is kept distinct
from `MALFORMED` (a unit string recorded but unparseable) -- a `unit_resolution` row is never
created for `MISSING` at all (see that table's own section); the value exists in this enum
only for the in-memory `app.units.resolve_unit_string` result, never actually written to this
column.
```text
PARSED
MALFORMED
MISSING
```

---

# Table: project

```text
id                          UUID PRIMARY KEY
stable_identifier           VARCHAR NOT NULL UNIQUE
title                        VARCHAR NOT NULL
description                  TEXT
project_type                 ProjectType NOT NULL
agent1_organism_id           UUID                  -- copied Agent 1 organism.id, never an FK
biological_context_summary   TEXT
strain_genotype_notes        TEXT
biological_process           TEXT
disease                      VARCHAR
tissue                       VARCHAR
cell_type                    VARCHAR
status                       WorkflowLifecycleStatus NOT NULL DEFAULT ACTIVE
notes                        TEXT
created_at                   TIMESTAMP WITH TIME ZONE NOT NULL
updated_at                   TIMESTAMP WITH TIME ZONE NOT NULL
```

`disease`/`tissue`/`cell_type` fold what Agent 1's own retired
`project_regulatory_context` table held into `project` directly -- the
Workbench's `Project` is intentionally simpler than Agent 1's retired
version, since there is no cross-database uniqueness concern requiring a
separate one-to-one child table here.

---

# Table: subproject

```text
id            UUID PRIMARY KEY
project_id    UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT
title         VARCHAR NOT NULL
objective     TEXT
task_type     SubprojectTaskType NOT NULL
status        WorkflowLifecycleStatus NOT NULL DEFAULT ACTIVE
notes         TEXT
created_at    TIMESTAMP WITH TIME ZONE NOT NULL
updated_at    TIMESTAMP WITH TIME ZONE NOT NULL
```

`(project_id, title)` must be unique.

---

# Table: dataset_reference

```text
id                          UUID PRIMARY KEY
project_id                   UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT
subproject_id                 UUID REFERENCES subproject(id) ON DELETE RESTRICT
dataset_type                  VARCHAR NOT NULL   -- open vocabulary, never a closed enum
name                           VARCHAR NOT NULL
description                    TEXT
agent1_entity_type             VARCHAR
agent1_entity_id                UUID             -- copied, never an FK
biological_context_notes        TEXT
artifact_reference              TEXT NOT NULL    -- opaque pointer to the dataset's own file/blob
checksum                        VARCHAR
version_label                   VARCHAR
notes                           TEXT
created_at                      TIMESTAMP WITH TIME ZONE NOT NULL
updated_at                      TIMESTAMP WITH TIME ZONE NOT NULL
```

---

# Table: model

```text
id                    UUID PRIMARY KEY
subproject_id          UUID NOT NULL REFERENCES subproject(id) ON DELETE RESTRICT
stable_identifier       VARCHAR NOT NULL UNIQUE
name                    VARCHAR NOT NULL
source_type             ModelSourceType NOT NULL
status                  ModelStatus NOT NULL DEFAULT DRAFT
artifact_reference       TEXT             -- opaque pointer; never the content itself
parent_model_id          UUID REFERENCES model(id) ON DELETE RESTRICT
version_label             VARCHAR
notes                     TEXT
created_at                TIMESTAMP WITH TIME ZONE NOT NULL
updated_at                TIMESTAMP WITH TIME ZONE NOT NULL
```

A later calibration or modification never overwrites a prior row -- it
creates a new row linked via `parent_model_id`.

---

# Table: model_build_request

```text
id              UUID PRIMARY KEY
subproject_id    UUID NOT NULL UNIQUE REFERENCES subproject(id) ON DELETE RESTRICT
notes             TEXT
created_at         TIMESTAMP WITH TIME ZONE NOT NULL
updated_at         TIMESTAMP WITH TIME ZONE NOT NULL
```

One build request per subproject. Replaces the concept Agent 1's own
(retired) migration `0020` called `ModelSpecification` -- renamed to avoid
colliding with Agent 2's own, unrelated, in-memory type of the identical
name.

## Child tables

Each child table below carries no database uniqueness constraint of its
own (a request may legitimately need the identical reaction under two
different roles); idempotency is enforced at the application level (see
`app.persistence.model_build_request`). `agent1_entity_type`/
`agent1_entity_id` are copied references, never foreign keys;
`raw_identifier` is always preserved when supplied, regardless of whether
a resolved entity id was also supplied.

### model_build_request_species
```text
id, model_build_request_id, role (ModelBuildRequestSpeciesRole),
agent1_entity_type, agent1_entity_id, raw_identifier, notes, created_at
```
Covers model input/start species, model output/end species, boundary
species, and seed metabolites in one table.

### model_build_request_reaction
```text
id, model_build_request_id, role (ModelBuildRequestReactionRole),
agent1_entity_type, agent1_entity_id, raw_identifier, notes, created_at
```
Covers seed reactions, required reactions, and excluded reactions.

### model_build_request_gene_protein
```text
id, model_build_request_id, role (ModelBuildRequestGeneProteinRole),
agent1_entity_type, agent1_entity_id, raw_identifier,
localization_entity_type, localization_entity_id, localization_raw_identifier,
notes, created_at
```
Covers seed genes/proteins and important genes/proteins.
`localization_*` is the subcellular localization constraint on this one
reference -- distinct from "compartments to include" below.

### model_build_request_compartment
```text
id, model_build_request_id, agent1_entity_type, agent1_entity_id,
raw_identifier, notes, created_at
```
Compartments the model as a whole should include.

### model_build_request_regulatory_interaction
```text
id, model_build_request_id, agent1_entity_type, agent1_entity_id,
raw_identifier, notes, created_at
```

### model_build_request_enzyme_state
```text
id, model_build_request_id, agent1_entity_type, agent1_entity_id,
raw_identifier, notes, created_at
```
PTMs/protein states to include.

### model_build_request_pathway
```text
id, model_build_request_id, role (ModelBuildRequestPathwayRole),
external_pathway_id, name, notes, created_at
```
Pathway scope: inclusion and exclusion. No `Pathway` entity exists
anywhere in this system, so the source's own pathway identifier is stored
directly.

### model_build_request_assumption
```text
id, model_build_request_id, assumption (TEXT NOT NULL), rationale,
required (BOOLEAN NOT NULL DEFAULT FALSE), created_at
```
One user constraint or assumption. The Workbench's own table for this --
Agent 1 reuses its existing `ModelingAssumption` table polymorphically; the
Workbench has no such table to reuse.

---

# Table: modeling_decision

```text
id                  UUID PRIMARY KEY
project_id            UUID REFERENCES project(id) ON DELETE RESTRICT
subproject_id          UUID REFERENCES subproject(id) ON DELETE RESTRICT
model_id                UUID REFERENCES model(id) ON DELETE RESTRICT
question                 TEXT NOT NULL
decision_type             VARCHAR
status                    ModelingDecisionStatus NOT NULL DEFAULT OPEN
selected_option_id         UUID REFERENCES modeling_decision_option(id) ON DELETE RESTRICT
resolution_source           ModelingDecisionResolutionSource
rationale                   TEXT
notes                        TEXT
created_at                   TIMESTAMP WITH TIME ZONE NOT NULL
updated_at                   TIMESTAMP WITH TIME ZONE NOT NULL
```

`project_id`/`subproject_id`/`model_id` are all nullable: a decision's own
context may be scoped at whichever level is appropriate, and more than one
may be set at once. `selected_option_id` is a genuine forward reference to
`modeling_decision_option`, resolved via a two-phase migration (see that
migration's own docstring) exactly mirroring Agent 1's own solution to the
identical problem.

---

# Table: modeling_decision_option

```text
id                  UUID PRIMARY KEY
decision_id           UUID NOT NULL REFERENCES modeling_decision(id) ON DELETE CASCADE
label                  VARCHAR NOT NULL
description             TEXT
evidence_summary         TEXT
confidence_score          NUMERIC         -- CHECK 0..100, same pattern as Agent 1's Claim
confidence_class           ConfidenceClass
impact_summary               TEXT
recommended                   BOOLEAN NOT NULL DEFAULT FALSE
created_at                     TIMESTAMP WITH TIME ZONE NOT NULL
updated_at                     TIMESTAMP WITH TIME ZONE NOT NULL
```

---

# Table: run_record

```text
id                       UUID PRIMARY KEY
subproject_id            UUID NOT NULL REFERENCES subproject(id) ON DELETE RESTRICT
model_id                 UUID REFERENCES model(id) ON DELETE RESTRICT
model_build_request_id   UUID REFERENCES model_build_request(id) ON DELETE RESTRICT
model_module_id          UUID REFERENCES model_module(id) ON DELETE RESTRICT
stage                    RunStage NOT NULL
status                   RunStatus NOT NULL DEFAULT PENDING
contract_version         VARCHAR     -- free text; never enforced/interpreted here
artifact_reference       TEXT        -- opaque pointer to this run's output
result_summary           TEXT
error_summary            TEXT
warnings                 TEXT        -- opaque, JSON-encoded list of warning strings
started_at               TIMESTAMP WITH TIME ZONE
completed_at             TIMESTAMP WITH TIME ZONE
created_at               TIMESTAMP WITH TIME ZONE NOT NULL
```

Append-only: always a new row per invocation, never updated into a
different identity. No `updated_at` -- `started_at`/`completed_at` already
capture the lifecycle timestamps that matter.

`model_build_request_id`/`warnings` were added by the Scoped-Build
Support increment (migration `0002_run_record_build_request`): which
`ModelBuildRequest` (if any) scoped this run, and any structured warning
the harness/Agent 2 returned for it (an unresolved reference, an
unsupported pathway constraint, ...). Both are additive and nullable --
every pre-existing row is unaffected. Associated here, not on `model`,
because a `Model` row's own durable lineage is independent of which
specific run attempt built it, while `run_record` already records every
other request parameter a run was invoked with (`model_id`).

`model_module_id` was added by the Executable-Module Materialization increment (migration
`0006_model_module`): which `ModelModule` (if any) an Agent 3 run simulated -- set only for a
module-simulation run (`stage=RunStage.AGENT3`); `NULL` for every other stage, including an
ordinary whole-model Agent 3 run inside `FULL_PIPELINE`.

# Table: hierarchy_node

```text
id                                  UUID PRIMARY KEY
run_record_id                       UUID NOT NULL REFERENCES run_record(id) ON DELETE CASCADE
node_id                             VARCHAR NOT NULL   -- the harness's own node_id string
depth                                INTEGER NOT NULL
parent_modularization_id            TEXT        -- NULL only for the root node (depth 0)
parent_module_id                    TEXT
child_submodel_id                   TEXT        -- the materialized submodel's own model_id
child_modularization_id             TEXT        -- the accepted candidate's own id, or NULL
child_module_ids                    TEXT        -- opaque, JSON-encoded list of module ids
accepted                            BOOLEAN NOT NULL
reason                              TEXT NOT NULL
baseline_score                      NUMERIC     -- the degenerate "intact parent" baseline
child_score                         NUMERIC     -- the accepted/best-attempted candidate's score
branch_stopping_reason              VARCHAR     -- NULL for an accepted node that keeps descending
recursive_search_stopping_reason    VARCHAR NOT NULL
recursive_search_rounds             INTEGER NOT NULL
recursive_search_policy_version     VARCHAR NOT NULL
attach_payload                      TEXT        -- opaque; NULL for the root and never-materialized nodes
created_at                          TIMESTAMP WITH TIME ZONE NOT NULL
```

`attach_payload` was added by the Executable-Module Materialization increment (migration
`0006_model_module`): the exact, opaque payload the harness used to materialize that node's own
submodel, threaded through from the harness's own new `HierarchyNodeRecord.attach_payload`
field -- `NULL` for the root node (depth 0) and for a node never actually materialized
(`MODULE_TOO_SMALL`/`HUMAN_REVIEW_REJECTED`). Never parsed here except to pass it back,
unchanged, to the harness's own module-simulation entrypoint; see `model_module` below.

Added by the Automatic Hierarchical Recursive Modularization increment (migration
`0003_hierarchy_node`): one row per node of one hierarchical-recursion `run_record` (recorded
with `stage=RunStage.HARNESS`, the identical stage the `FULL_PIPELINE` workflow already uses --
a hierarchical-recursion run is distinguished from a `FULL_PIPELINE` one only by whether any
`hierarchy_node` rows exist for it). `ON DELETE CASCADE`, unlike every other FK on this table's
own parent `run_record`: a `HierarchyNode` has no independent existence apart from the run that
produced it, unlike e.g. a `Model` row's own durable lineage (`RESTRICT`). Every field a UI
needs to render the accepted module tree, stopped branches, scores, and reasons is its own
typed, queryable column; `child_module_ids` is the one list-shaped field still stored as an
opaque, JSON-encoded string (a UI needing it already has every child node's own
`parent_module_id`, so this column is redundant provenance, not the tree's own structural
backbone).

`(run_record_id, node_id)` is unique (added by migration `0004_checkpoint_review`): the
database-level idempotency backstop so a resumed run's own already-completed nodes are never
re-inserted (see `docs/05_hierarchical_review_resume.md`).

---

# Table: hierarchy_checkpoint

```text
id                   UUID PRIMARY KEY
run_record_id        UUID NOT NULL REFERENCES run_record(id) ON DELETE CASCADE
sequence             INTEGER NOT NULL   -- 0 for the first pause; +1 per resume-then-re-pause
checkpoint_version   VARCHAR NOT NULL   -- denormalized copy of payload's own field
policy_version       VARCHAR NOT NULL   -- denormalized copy of payload's own field
hierarchy_id         VARCHAR NOT NULL   -- denormalized copy of payload's own field
payload              TEXT NOT NULL      -- the harness's own serialize_checkpoint(...) dict, verbatim
consumed_at          TIMESTAMP WITH TIME ZONE   -- set once a resume attempt used this checkpoint
created_at           TIMESTAMP WITH TIME ZONE NOT NULL
```

`(run_record_id, sequence)` is unique. Added by the Hierarchical Review/Resume increment
(migration `0004_checkpoint_review`): one row per pause of one hierarchical-recursion
`run_record`, `ON DELETE CASCADE` (identical "no independent existence apart from the run"
precedent as `hierarchy_node`). `payload` is opaque -- never parsed or interpreted here except
to pass back, unchanged, to the harness's own resume call. The *current* checkpoint for a run
is the row with the maximum `sequence`; `consumed_at IS NOT NULL` marks it stale (already used
by a resume attempt, so it can never be resumed again). See
`docs/05_hierarchical_review_resume.md`.

---

# Table: hierarchy_pending_review_item

```text
id                       UUID PRIMARY KEY
hierarchy_checkpoint_id  UUID NOT NULL REFERENCES hierarchy_checkpoint(id) ON DELETE CASCADE
pending_id               TEXT NOT NULL   -- the harness's own stable identifier for this module
parent_node_id           TEXT NOT NULL   -- the harness's own node_id of the parent node
module_id                TEXT NOT NULL   -- the content-addressed module id awaiting review
depth                    INTEGER NOT NULL
reaction_count           INTEGER
created_at               TIMESTAMP WITH TIME ZONE NOT NULL
```

`(hierarchy_checkpoint_id, pending_id)` is unique. Added by the Hierarchical Review/Resume
increment: one row per entry of one checkpoint's own `pending_review_modules`, `ON DELETE
CASCADE` from `hierarchy_checkpoint`. Every field a UI needs to list pending modules is its own
typed column -- never only an entry inside `hierarchy_checkpoint.payload`.

---

# Table: hierarchy_review_decision

```text
id                       UUID PRIMARY KEY
pending_review_item_id   UUID NOT NULL UNIQUE REFERENCES hierarchy_pending_review_item(id) ON DELETE CASCADE
decision                 HierarchyReviewDecisionValue NOT NULL
decided_by               VARCHAR   -- free text; no user-account system exists yet, never an FK
notes                    TEXT
decided_at               TIMESTAMP WITH TIME ZONE NOT NULL
```

Added by the Hierarchical Review/Resume increment: exactly one decision per pending item
(`pending_review_item_id` is itself unique, not just indexed), `ON DELETE CASCADE` from
`hierarchy_pending_review_item`. Idempotency (resubmitting the identical decision is a no-op;
resubmitting a different one is rejected) is enforced at the application level, not by this
table's own constraints alone -- see `app.persistence.hierarchy_review_decision`.

---

# Table: hierarchy_resume_attempt

```text
id                       UUID PRIMARY KEY
hierarchy_checkpoint_id  UUID NOT NULL UNIQUE REFERENCES hierarchy_checkpoint(id) ON DELETE CASCADE
status                   HierarchyResumeAttemptStatus NOT NULL DEFAULT PENDING
attempt_count            INTEGER NOT NULL DEFAULT 0
started_at               TIMESTAMP WITH TIME ZONE
completed_at             TIMESTAMP WITH TIME ZONE
error_summary            TEXT
created_at               TIMESTAMP WITH TIME ZONE NOT NULL
updated_at               TIMESTAMP WITH TIME ZONE NOT NULL
```

Added by the Crash-Safe Resume increment (migration `0005_resume_attempt`): at most one row
per checkpoint (`hierarchy_checkpoint_id` is itself unique -- the idempotency key a repeated
resume request for the identical checkpoint always resolves against), `ON DELETE CASCADE` from
`hierarchy_checkpoint`. See `docs/06_crash_safe_resume.md` for the full state machine and the
crash-safety design this table exists to support.

---

# Table: model_module

```text
id                         UUID PRIMARY KEY
run_record_id              UUID NOT NULL REFERENCES run_record(id) ON DELETE RESTRICT
hierarchy_node_id          UUID NOT NULL UNIQUE REFERENCES hierarchy_node(id) ON DELETE RESTRICT
parent_model_module_id     UUID REFERENCES model_module(id) ON DELETE RESTRICT
root_model_id              UUID REFERENCES model(id) ON DELETE RESTRICT
depth                      INTEGER NOT NULL
module_id                  TEXT NOT NULL      -- content-addressed
source_modularization_id   TEXT NOT NULL
child_submodel_id          TEXT               -- denormalized from the producing hierarchy_node
attach_payload             TEXT NOT NULL      -- opaque; copied verbatim from hierarchy_node
execution_status           model_module_execution_status NOT NULL DEFAULT 'VIEW_ONLY'
created_at                 TIMESTAMP WITH TIME ZONE NOT NULL
```

Added by the Executable-Module Materialization increment (migration `0006_model_module`): one
row per depth>=1 `hierarchy_node` that was genuinely materialized (`attach_payload IS NOT
NULL`). `ON DELETE RESTRICT` everywhere, unlike every `CASCADE`-deleted table the Hierarchical
Review/Resume increment added -- a `ModelModule` is a durable, independently-referenceable
execution target, the identical precedent `model` itself already uses, never the "no
independent existence apart from its parent" precedent. `hierarchy_node_id` is itself unique
(1:1 with the node that produced it) -- the idempotency key repeated materialization calls
(every resume/replay) always resolve against. `parent_model_module_id` is `NULL` when this
module's own parent is the root model itself (the root is never represented as its own
`model_module` row). See `docs/07_executable_module_materialization.md`.

`execution_status` was added by the Boundary-Condition Semantics increment (migration
`0007_module_boundary_port`) -- recomputed from this module's own `module_boundary_port` rows
by `app.orchestration.module_boundary_orchestrator.evaluate_module_execution_status` alone,
never hand-set elsewhere. See `docs/08_boundary_condition_semantics.md`.

---

# Table: module_boundary_port

```text
id                         UUID PRIMARY KEY
model_module_id            UUID NOT NULL REFERENCES model_module(id) ON DELETE CASCADE
port_id                    TEXT NOT NULL      -- stable, deterministic; never Agent 2-generated
species_id                 TEXT NOT NULL
direction                  module_port_direction NOT NULL
treatment_type             module_boundary_treatment_type NOT NULL DEFAULT 'UNRESOLVED'
resolution_status          module_boundary_resolution_status NOT NULL DEFAULT 'PENDING_REVIEW'
initial_value              NUMERIC
unit                       VARCHAR
value_source               VARCHAR
provenance_notes           TEXT
derived_automatically      BOOLEAN NOT NULL DEFAULT TRUE
decided_by                 VARCHAR
decided_at                 TIMESTAMP WITH TIME ZONE
created_at                 TIMESTAMP WITH TIME ZONE NOT NULL
updated_at                 TIMESTAMP WITH TIME ZONE NOT NULL

UNIQUE (model_module_id, species_id, direction)
```

Added by the Boundary-Condition Semantics increment (migration `0007_module_boundary_port`):
one row per `(model_module, species_id, direction)` candidate or decided boundary port.
`ON DELETE CASCADE` from `model_module` -- unlike `model_module` itself, this row has no
independent meaning apart from the module it describes (the identical "no independent
existence apart from its parent" precedent `hierarchy_pending_review_item` already uses from
`hierarchy_checkpoint`). `port_id` is a stable, deterministic id computed before any Agent 2
call is ever made -- never Agent 2's own runtime-generated port id. The unique constraint is
this table's own idempotency key: `app.persistence.module_boundary_port
.persist_candidate_boundary_ports` queries it first and creates only genuinely new rows, never
touching (let alone overwriting) an already-known candidate, automatic or manually-decided.
See `docs/08_boundary_condition_semantics.md`.

---

# Table: module_execution_snapshot

```text
id                         UUID PRIMARY KEY
model_module_id            UUID NOT NULL REFERENCES model_module(id) ON DELETE RESTRICT
run_record_id              UUID NOT NULL UNIQUE REFERENCES run_record(id) ON DELETE RESTRICT
execution_kind             module_execution_kind NOT NULL
module_artifact_hash       VARCHAR NOT NULL  -- sha256 of the Agent 2 materialization input
snapshot_payload           TEXT NOT NULL     -- opaque; see below
created_at                 TIMESTAMP WITH TIME ZONE NOT NULL
```

Added by the Module-Level Agent4 Calibration with Immutable Execution-Condition Provenance
increment (migration `0008_module_execution_snapshot`): one immutable row per module-scoped
execution (`run_record_id` unique, 1:1). `ON DELETE RESTRICT` from both `model_module` and
`run_record` -- a durable, independently-meaningful provenance record, the identical "has its
own lineage" precedent `model_module` itself already uses, never the "no independent
existence apart from its parent" precedent `module_boundary_port`'s own `CASCADE` uses. There
is no `updated_at` column, and no persistence function anywhere in this repository ever issues
an `UPDATE` against this table -- a later change to a `module_boundary_port`'s own decision or
a `dataset_reference`'s own catalog row never alters a snapshot already on file.

`module_artifact_hash` is a `sha256` hex digest of the canonical JSON encoding of the exact
Agent 2 materialization input (`attach_payload` plus its own merged `module_ports`) --
deterministic and always computable before any harness subprocess is invoked, so a snapshot
exists even for a run that later fails (`app.persistence.module_execution_snapshot
.compute_module_artifact_hash`, the one shared helper every module-scoped orchestrator that
creates a snapshot reuses). `snapshot_payload` is an opaque, pre-serialized JSON object
(decoded only by `app.persistence.module_execution_snapshot.read_snapshot_payload`, the one
documented site, mirroring `model_module.attach_payload`'s own established discipline)
carrying `{"boundary_ports", "contract_versions"}` always, `{"calibration_config",
"dataset_references"}` only for `execution_kind=CALIBRATION`, `{"calibration_run_record_id",
"calibrated_parameters", "validation_config", "dataset_references"}` only for
`execution_kind=VALIDATION` (the originating calibration run's own frozen parameter
estimates, copied by value, never a live reference), and `{"module_handoff_summary",
"parameters", "species"}` only once the underlying harness call actually completed. See
`docs/09_module_level_agent4_calibration.md`/`docs/10_module_level_agent5_validation.md`.

---

# Table: module_aggregate

```text
id                         UUID PRIMARY KEY
hierarchy_run_record_id    UUID NOT NULL REFERENCES run_record(id) ON DELETE RESTRICT
target_model_module_id     UUID REFERENCES model_module(id) ON DELETE RESTRICT  -- NULL = root
execution_kind             module_execution_kind NOT NULL
version                    INTEGER NOT NULL
completeness_status        module_aggregate_completeness NOT NULL
input_fingerprint          VARCHAR NOT NULL
summary_payload            TEXT NOT NULL  -- opaque; see below
created_at                 TIMESTAMP WITH TIME ZONE NOT NULL
```

Added by the Hierarchical Aggregation of Module-Level Agent3/4/5 Results increment (migration
`0010_module_aggregate`): one immutable row per `(target, execution_kind, version)`, where
"target" is either a specific `model_module` or the hierarchy root itself
(`target_model_module_id IS NULL`, rolling up every depth-1 `model_module` of
`hierarchy_run_record_id` -- the root is never itself a `model_module` row, the identical
convention `model_module.parent_model_module_id` already uses). `ON DELETE RESTRICT` from
both `run_record` and `model_module`, the identical "has its own lineage, never ephemeral
workflow bookkeeping" precedent `model_module`/`module_execution_snapshot` already use. There
is no `updated_at` column, and no persistence function anywhere in this repository ever
issues an `UPDATE` against this table -- a new, separately-numbered `version` row is always
created instead of mutating an existing one.

`input_fingerprint` is a `sha256` hex digest (`app.persistence.module_aggregate
.compute_aggregate_fingerprint`) of exactly what this aggregate rolled up (its own direct
result's `run_record` id, if any, plus each direct child's own latest aggregate id+version) --
this table's own idempotency key: a rebuild whose freshly-computed fingerprint matches the
latest existing row's own is returned unchanged, never duplicated. `summary_payload` is an
opaque, pre-serialized JSON object (decoded only by `app.persistence.module_aggregate
.read_aggregate_payload`, the one documented site) carrying `{"own_result", "children",
"missing_or_failed_children", "provenance"}` -- never a blended/averaged value across
children, which are always listed side by side, tagged by their own `module_id`. See
`docs/12_hierarchical_aggregation.md`.

---

# Table: cross_module_diagnostic_run

```text
id                         UUID PRIMARY KEY
hierarchy_run_record_id    UUID NOT NULL REFERENCES run_record(id) ON DELETE RESTRICT
version                    INTEGER NOT NULL
input_fingerprint          VARCHAR NOT NULL
finding_count              INTEGER NOT NULL
created_at                 TIMESTAMP WITH TIME ZONE NOT NULL
```

Added by the Cross-Module Consistency and Reconciliation Diagnostics increment (migration
`0011_cross_module_diagnostics`): one immutable, versioned row per invocation of the
consistency sweep over one hierarchy run's own already-persisted modules. `ON DELETE
RESTRICT` from `run_record`, the identical precedent `model_module`/`module_execution_
snapshot`/`module_aggregate` already use. Idempotent by `input_fingerprint`
(`app.persistence.cross_module_diagnostic.compute_diagnostic_run_fingerprint`) against the
latest existing run for the same hierarchy run -- an unchanged source state returns the
existing run (and its own already-persisted findings) unchanged; a changed one creates a
new, separately-numbered version. See `docs/13_cross_module_diagnostics.md`.

---

# Table: cross_module_diagnostic

```text
id                         UUID PRIMARY KEY
diagnostic_run_id          UUID NOT NULL REFERENCES cross_module_diagnostic_run(id) ON DELETE CASCADE
category                   cross_module_diagnostic_category NOT NULL
severity                   diagnostic_severity NOT NULL
message                    TEXT NOT NULL
affected_model_module_ids  TEXT NOT NULL  -- opaque JSON array of model_module id strings
evidence_payload           TEXT NOT NULL  -- opaque; full comparison detail + provenance
review_status              diagnostic_review_status NOT NULL DEFAULT 'UNREVIEWED'
review_note                TEXT
reviewed_by                VARCHAR
reviewed_at                TIMESTAMP WITH TIME ZONE
created_at                 TIMESTAMP WITH TIME ZONE NOT NULL
```

One row per detected cross-module inconsistency. `ON DELETE CASCADE` from
`cross_module_diagnostic_run` -- a finding has no independent meaning apart from the run
batch that produced it, the identical "no independent existence apart from its parent"
precedent `module_boundary_port` already uses. `category`/`severity`/`message`/
`affected_model_module_ids`/`evidence_payload` are immutable once created -- no persistence
function ever updates them. `review_status`/`review_note`/`reviewed_by`/`reviewed_at` are
the one deliberately mutable field group this increment adds anywhere: marking a finding
reviewed (`app.persistence.cross_module_diagnostic.mark_finding_reviewed`) only ever touches
these four columns, never the finding's own detection content or any source record it
describes. See `docs/13_cross_module_diagnostics.md`.

---

# Table: unit_resolution

(Structured Units and Dimensional-Consistency Validation increment, migration
`0012_unit_resolution`.)

```text
id                   UUID PRIMARY KEY
source_unit_string   VARCHAR NOT NULL UNIQUE
normalized_unit      VARCHAR            -- pint's own short pretty form, e.g. "mM"; NULL if unparseable
dimensionality       VARCHAR            -- pint's own dimensionality string; NULL if unparseable
parse_status         unit_parse_status NOT NULL
created_at           TIMESTAMP WITH TIME ZONE NOT NULL
```

A durable, content-addressed cache of every distinct, non-empty raw unit string this
Workbench has ever resolved (`app.persistence.unit_resolution.resolve_and_persist_unit`) --
standalone, with **no foreign key in or out**: unlike every other table in this schema, no
column anywhere references `unit_resolution.id`, and this table references nothing. Callers
resolve a raw unit string and get back a plain dict; they never need to join against this
table directly. A `None`/blank unit string is never given a row here at all -- see
`app.units`'s own module docstring. Immutable once created -- no persistence function ever
updates an existing row. See `docs/14_structured_units.md`.

---

# Relationships

```text
project
   |
   +-- subproject
   |       |
   |       +-- model_build_request
   |       |       |
   |       |       +-- model_build_request_species / _reaction / _gene_protein /
   |       |           _compartment / _regulatory_interaction / _enzyme_state /
   |       |           _pathway / _assumption
   |       |
   |       +-- model
   |       |       |
   |       |       +-- model (parent_model_id, self-referential lineage)
   |       |
   |       +-- run_record (model_id / model_build_request_id optional)
   |               |
   |               +-- hierarchy_node (ON DELETE CASCADE)
   |               |
   |               +-- hierarchy_checkpoint (ON DELETE CASCADE)
   |                       |
   |                       |
   |                       +-- hierarchy_pending_review_item (ON DELETE CASCADE)
   |                       |       |
   |                       |       +-- hierarchy_review_decision (ON DELETE CASCADE)
   |                       |
   |                       +-- hierarchy_resume_attempt (ON DELETE CASCADE)
   |               |
   |               +-- model_module (ON DELETE RESTRICT; 1:1 with a materialized hierarchy_node)
   |               |       |
   |               |       +-- model_module (parent_model_module_id, self-referential lineage)
   |               |       |
   |               |       +-- run_record (model_module_id, an Agent 3 simulation of it, an
   |               |       |               Agent 4 calibration of it, or an Agent 5
   |               |       |               validation of it)
   |               |       |
   |               |       +-- module_boundary_port (ON DELETE CASCADE)
   |               |       |
   |               |       +-- module_execution_snapshot (ON DELETE RESTRICT; 1:1 with the
   |               |       |           run_record it snapshots)
   |               |       |
   |               |       +-- module_aggregate (ON DELETE RESTRICT; target_model_module_id --
   |               |                   this module's own roll-up, one per execution_kind)
   |               |
   |               +-- module_aggregate (ON DELETE RESTRICT; hierarchy_run_record_id with
   |               |           target_model_module_id IS NULL -- the hierarchy root's own
   |               |           roll-up, one per execution_kind)
   |               |
   |               +-- cross_module_diagnostic_run (ON DELETE RESTRICT; one versioned
   |                           consistency-sweep batch per hierarchy run)
   |                           |
   |                           +-- cross_module_diagnostic (ON DELETE CASCADE)
   |
   +-- dataset_reference (subproject_id optional)

modeling_decision
   |
   +-- project / subproject / model (optional context, any combination)
   |
   +-- modeling_decision_option
           |
           +-- modeling_decision (selected_option_id, optional)

unit_resolution   (standalone -- no foreign key in or out of this table anywhere)
```

---

# Required Indexes

```text
project.stable_identifier
project.agent1_organism_id
subproject.project_id
dataset_reference.project_id
dataset_reference.subproject_id
model.subproject_id
model.stable_identifier
model.parent_model_id
model_build_request.subproject_id
model_build_request_*.model_build_request_id   (all eight child tables)
modeling_decision.project_id
modeling_decision.subproject_id
modeling_decision.model_id
modeling_decision.selected_option_id
modeling_decision_option.decision_id
run_record.subproject_id
run_record.model_id
run_record.model_build_request_id
hierarchy_node.run_record_id
hierarchy_checkpoint.run_record_id
hierarchy_pending_review_item.hierarchy_checkpoint_id
hierarchy_resume_attempt.hierarchy_checkpoint_id
model_module.run_record_id
run_record.model_module_id
module_boundary_port.model_module_id
module_execution_snapshot.model_module_id
module_aggregate.target_model_module_id
module_aggregate.hierarchy_run_record_id (composite with execution_kind)
cross_module_diagnostic_run.hierarchy_run_record_id
cross_module_diagnostic.diagnostic_run_id
unit_resolution.source_unit_string
```

---

# Delete Behavior

`ON DELETE RESTRICT` is the default everywhere. Cascade is permitted only
for a child table whose rows have no independent meaning apart from the
parent they describe -- the same "container tears down its own subordinate
structure" precedent used by Agent 1 for `network`/`project_specification`
child tables, not the more conservative precedent Agent 1 uses for its own
core scientific records:

```text
model_build_request_species                   (cascades from model_build_request)
model_build_request_reaction                  (cascades from model_build_request)
model_build_request_gene_protein              (cascades from model_build_request)
model_build_request_compartment               (cascades from model_build_request)
model_build_request_regulatory_interaction    (cascades from model_build_request)
model_build_request_enzyme_state              (cascades from model_build_request)
model_build_request_pathway                   (cascades from model_build_request)
model_build_request_assumption                (cascades from model_build_request)
modeling_decision_option                       (cascades from modeling_decision)
hierarchy_node                                 (cascades from run_record)
hierarchy_checkpoint                           (cascades from run_record)
hierarchy_pending_review_item                  (cascades from hierarchy_checkpoint)
hierarchy_review_decision                      (cascades from hierarchy_pending_review_item)
hierarchy_resume_attempt                       (cascades from hierarchy_checkpoint)
module_boundary_port                           (cascades from model_module)
cross_module_diagnostic                        (cascades from cross_module_diagnostic_run)
```

`model.parent_model_id` restricts (a prior model version must not be
deleted while a later version still names it as its parent).
`subproject.project_id`, `model.subproject_id`, `run_record.subproject_id`,
and `dataset_reference.project_id`/`subproject_id` all restrict -- a
project/subproject with any dependent row cannot be deleted outright.

`model_module` restricts everywhere (`run_record_id`/`hierarchy_node_id`/
`parent_model_module_id`/`root_model_id`), and `run_record.model_module_id` restricts too --
deliberately the odd one out among the Hierarchical Review/Resume increment's own all-`CASCADE`
additions: a `ModelModule` is a durable, independently-referenceable execution target (the
identical "has its own lineage" precedent `model` already uses), never ephemeral workflow
bookkeeping.

`module_boundary_port` cascades from `model_module` -- unlike `model_module` itself, a boundary
port row has no independent meaning apart from the module it describes (Boundary-Condition
Semantics increment).

`module_execution_snapshot` restricts from both `model_module` and `run_record` -- a durable
provenance record, never ephemeral workflow bookkeeping, deliberately following
`model_module`'s own precedent rather than `module_boundary_port`'s (Module-Level Agent4
Calibration with Immutable Execution-Condition Provenance increment).

`module_aggregate` restricts from both `model_module` and `run_record`, the identical
precedent, for the identical reason (Hierarchical Aggregation of Module-Level Agent3/4/5
Results increment) -- a historical aggregate must never be silently orphaned or torn down by
deleting the module or run it describes.

`cross_module_diagnostic_run` restricts from `run_record`, the identical precedent, for the
identical reason (Cross-Module Consistency and Reconciliation Diagnostics increment).
`cross_module_diagnostic` cascades from `cross_module_diagnostic_run` -- unlike that table, a
single finding has no independent meaning apart from the sweep batch that produced it.

`unit_resolution` has no delete behavior to specify -- it has no foreign key in or out of any
other table (Structured Units and Dimensional-Consistency Validation increment).
