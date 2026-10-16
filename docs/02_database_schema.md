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
created_at                          TIMESTAMP WITH TIME ZONE NOT NULL
```

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
   |                       +-- hierarchy_pending_review_item (ON DELETE CASCADE)
   |                               |
   |                               +-- hierarchy_review_decision (ON DELETE CASCADE)
   |
   +-- dataset_reference (subproject_id optional)

modeling_decision
   |
   +-- project / subproject / model (optional context, any combination)
   |
   +-- modeling_decision_option
           |
           +-- modeling_decision (selected_option_id, optional)
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
```

`model.parent_model_id` restricts (a prior model version must not be
deleted while a later version still names it as its parent).
`subproject.project_id`, `model.subproject_id`, `run_record.subproject_id`,
and `dataset_reference.project_id`/`subproject_id` all restrict -- a
project/subproject with any dependent row cannot be deleted outright.
