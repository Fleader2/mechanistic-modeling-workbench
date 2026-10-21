# Module-Set Domain Model and GUI–Backend Contract (Proposal)

**Revision note (second update):** module renaming and reaction-membership editing -- part
of what this document's original text calls "manual editing," listed throughout as deferred --
are now implemented. See `docs/23_module_set_manual_editing_increment.md` for the full
implementation report. What that increment actually decided, which the rest of this document's
own "deferred" language should now be read against: editing only ever redistributes a draft's
own already-known reactions among sibling modules (same hierarchical parent) -- it never
invents a reaction id, never moves one across a hierarchy boundary, and never touches the
`ModelModule.run_record_id` schema change this document's §2.1 found genuinely blocked (editing
a draft member's own `display_name`/`reaction_component_ids` overlay columns is additive and
needed no such change). Split/merge and per-member origin tracking remain exactly as deferred as
this document already said.

**Revision note (first update):** the four items originally listed in
[§9](#9-decisions-resolved-and-the-one-still-deferred) have now been **decided** by the
project owner and are incorporated below as settled rules, not open questions: (1) a set's
identity may span model versions, with each version immutably pinned to exactly one, and changing
that pin on a later version requires explicit revalidation (not yet built — see
[§2.1](#21-dependency-audit-and-resolution-for-increment-1)); (2) discarded drafts are soft-marked,
hidden from normal listings, and can never execute; (3) origin is tracked per **version**
(`AUTOMATED`/`MANUAL`/`MIXED_EDITED`), per-member origin and all editing operations deferred; (4)
`ModelModule` reuse is confirmed in principle, but **its `run_record_id`/`module_set_version_id`
schema change is *not* applied in this first increment** — a concrete dependency audit
([§2.1](#21-dependency-audit-and-resolution-for-increment-1)) found two real execution-path
conflicts that must be resolved first. This document now also describes exactly what was
implemented for the first slice; see `docs/21_module_set_first_increment.md` for the
implementation report, demonstrated validation, and limitations.

**This is a design-and-contract document for the domain model as a whole.** It proposes entities,
relationships, lifecycle rules, and an API shape for the full "draft → inspect → explicitly save →
reopen" module-set workflow, including parts (manual editing, split/merge, per-member origin) that
remain deliberately unimplemented after this first increment. Grounded in a direct reading of this
repository's existing hierarchy/module/boundary architecture and the current Figma prototype (file
`4tLH4HX0rdgPxjpNB1aJOW`) — never invented from the screen names alone.

## 0. Method

Read directly (not from memory, not from prior completion reports): `docs/01`–`docs/14` (the full
Workbench architecture/hierarchy/boundary/calibration/validation/aggregation/diagnostics/units
series), `docs/15_gui_backend_integration_audit.md` (the direct predecessor — it already names
this exact gap, see [§1](#1-what-exists-today-the-greenfield-confirmation)), and
`docs/16`–`docs/19` (the GUI increments, for API/persistence/frontend conventions). Read directly:
`app/models/{hierarchy_node,model_module,module_boundary_port,module_execution_snapshot,
module_aggregate,cross_module_diagnostic,model,run_record}.py` and their `app/persistence/`
counterparts, and `app/orchestration/{hierarchical_run,hierarchical_review,module_boundary,
module_calibration,module_validation,module_aggregation,cross_module_diagnostics}_orchestrator.py`.
Fetched live via `get_design_context`/`get_screenshot`: the "05 — Module set draft" / "Save as new
module set" / "Save new set version" / "Module set saved" screens (manual and automated
variants, nodes `112:672`/`112:719`/`112:766`/`112:831`/`112:1521`), "06 — All Modules" (node
`60:756`), and "Compare modularizations" (node `48:923`).

## 1. What exists today (the greenfield confirmation)

`grep -rniE "module[ _-]?set|\bdraft\b|save-as-new|save new version" app/ docs/` returns **zero**
hits for any of these as a backend concept (the only "draft"/"version" hits are `ModelStatus.DRAFT`
on the unrelated root `Model` entity, and `Model.parent_model_id` lineage — a different entity with
a different identity model). This is confirmed, unambiguous greenfield, exactly as
`docs/15_gui_backend_integration_audit.md` already found and flagged as its own P1 gap #7:

> "No concept of an independently-versioned 'module set' exists in the schema at all. `ModelModule`
> rows are created once per hierarchical run... and have no separate set-identity/set-version
> column, no 'Manual'/'Automated' method tag, and no draft/working-state distinct from a committed
> hierarchical-run result. This is a genuine new schema + orchestration surface — not a wiring gap."

**The single load-bearing fact this proposal is built on** (confirmed by direct code reading, not
inferred): today, a `ModelModule` row has **zero continuity across runs**. Its `module_id`/
`source_modularization_id` are content-addressed hashes computed by the harness per-run; its
`hierarchy_node_id` is unique (1:1, the idempotency key); its `run_record_id` is set once at
creation and never updated by any persistence function anywhere in the repository. Re-running the
identical hierarchy search from scratch produces an entirely new, structurally parallel set of
`HierarchyNode`+`ModelModule` rows with no FK, no shared id, and no persisted correspondence to the
prior run's modules — not even when the content is identical. **There is currently no way to say
"this module, as edited, is the same module as that one in an earlier save."** Designing that
continuity, honestly (never inferred from name matching, per the "All Modules" screen's own
footer caveat: *"Identical names across sets do not establish module identity"*), is this
document's central job.

**Guiding principle, stated once and applied throughout:** a module set is a new, additive
*curation and versioning layer* sitting above the existing, unchanged hierarchy/materialization
machinery — never a renaming of `RunRecord`/`HierarchyNode`, and never a duplicate reimplementation
of `ModuleBoundaryPort`/`ModuleExecutionSnapshot`/`ModuleAggregate`/`CrossModuleDiagnostic`, all of
which already work, are already fully tested, and are explicitly kept untouched and in scope-as-is
by this proposal.

## 2. The central reconciliation: what is an "executable module," really?

Today, `ModelModule` means "one accepted hierarchy-search node, materialized from one specific
hierarical `RunRecord`." Its own docstring already frames it as "a durable, independently-
referenceable execution target" — a *generalization* beyond "the root `Model`" that this proposal
extends one step further: **a module produced by an explicit module-set save is the same kind of
thing as a module produced by an automated hierarchy search — both are "one executable module with
its own boundary interface and execution-readiness state" — they differ only in *how* they came to
exist.**

Two designs were considered for representing a module-set member as something `request_module_
simulation`/`request_module_calibration`/`request_module_validation` can actually execute:

- **(Rejected) A fully parallel entity.** Give `ModuleSetMember` its own boundary-port table,
  its own `execution_status`, its own snapshot linkage. Pro: zero risk to the existing `ModelModule`
  table. Con: every orchestrator that today accepts a bare `model_module_id` would need to accept
  a union type and branch on it, or the boundary/calibration/validation/aggregation/diagnostics
  machinery would need to be duplicated for a second "kind" of module. This directly contradicts
  the task's own "do not duplicate scientific logic" spirit and this repository's own architecture
  principle (`docs/15`: "the GUI must never duplicate scientific logic the Harness or Agents already
  own").
- **(Proposed) `ModuleSetMember` always resolves to a real `ModelModule` row.** A member that is
  an unedited reference to an existing, already-materialized module simply *points at* that row —
  no duplication, no migration, nothing re-created. A member whose membership was genuinely edited
  (split, merged, or manually authored — not yet in this increment's build scope, see
  [§8](#8-recommended-smallest-implementation-slice)) gets a **new** `ModelModule` row materialized
  at save time, honestly recording that it came from an explicit set-version save rather than a
  harness run (see [§2.1](#21-dependency-audit-and-resolution-for-increment-1)). Every
  existing simulate/calibrate/validate/aggregate/diagnose code path keeps working, completely
  unaware that "module sets" exist, because it always operates on a plain `model_module_id`.

The second design is still the one this document recommends for the long-term domain model. But
**implementing it now was independently audited and found to be premature** — see below. The first
increment therefore reuses `ModelModule` in the weaker, fully safe sense: every `ModuleSetMember`
this increment can ever create ***references*** an existing, already-materialized `ModelModule`
row (produced by a real hierarchical run); it never *creates* one. The schema change below remains
the recommended path once manual editing/split/merge is actually built — it is deferred, not
abandoned.

### 2.1. Dependency audit and resolution for increment 1

Per the explicit instruction to "audit every dependency on `run_record_id` before making it
nullable," every reference to `ModelModule.run_record_id`/`module.run_record_id` across
`app/orchestration/` and `app/persistence/` was read directly (not summarized from memory). Two
concrete, load-bearing dependencies were found that **would break if a `ModelModule.run_record_id`
were ever `NULL`**:

1. **`resolve_stage1_inputs` is a required execution input, not metadata.**
   `app/persistence/run_record.py::resolve_stage1_inputs(run_record)` recovers the hierarchy run's
   own original `agent1_organism_id`/`stage1_synthetic_source` — needed to re-invoke the harness
   "against the same root model a hierarchy run was originally searched against" (its own
   docstring). **Four** separate call sites —
   `model_module_orchestrator.request_module_simulation` (line 99-101),
   `module_boundary_orchestrator.derive_boundary_ports` (line 109-111),
   `module_calibration_orchestrator.request_module_calibration` (line 262-264), and
   `module_validation_orchestrator.request_module_validation` (line 373-375) — all do
   `source_run_record = get_run_record(session, module.run_record_id); assert source_run_record is
   not None; agent1_organism_id, stage1_synthetic_source = resolve_stage1_inputs(source_run_record)`.
   A `NULL` `run_record_id` makes `get_run_record` return `None`, and the `assert` **hard-crashes**
   every one of boundary derivation, simulation, calibration, and validation for that module — not
   a graceful validation error, an `AssertionError`.
2. **`build_module_aggregate` passes a module's `run_record_id` straight into a `NOT NULL` column.**
   `app/orchestration/module_aggregation_orchestrator.py::build_module_aggregate(model_module_id=
   ...)` is a public entrypoint that looks up the module and calls
   `_build_aggregate(hierarchy_run_record_id=module.run_record_id, ...)`, which ultimately calls
   `create_aggregate(hierarchy_run_record_id=...)` — `ModuleAggregate.hierarchy_run_record_id` is
   `Mapped[UUID]`, **not nullable**. A `NULL` `run_record_id` here either violates that type
   contract outright or, if passed through, violates the database's own `NOT NULL` constraint at
   insert time.

Both are genuine conflicts with "require a valid owning context for every module" read literally
as "every module must be fully usable by every existing service," not just "traceable to a
subproject." Relaxing `run_record_id` today, without first designing a replacement resolution path
(e.g., falling back to `Project.agent1_organism_id` via `Model.subproject_id` when no run exists,
and giving `ModuleAggregate`/diagnostics a defined behavior for a run-less module), would silently
break four already-shipped, already-tested execution/derivation entrypoints the moment any future
caller — including a GUI "Simulate"/"Aggregate" button — pointed one at a set-saved, manually-
edited module.

**Resolution adopted for this increment:** do not apply the schema change yet. This increment's
own scope (an *unedited* draft from an existing automated run) never needs to create a new
`ModelModule` row at all — every `ModuleSetMember` it can ever produce points at a pre-existing row
whose `run_record_id` was already set by `materialize_accepted_modules` and is never touched. The
"valid owning context for every module" requirement is therefore satisfied by construction, for
every module this increment ever creates or references, via the **unmodified, already-guaranteed**
chain `ModelModule.run_record_id` (`NOT NULL`) → `RunRecord.subproject_id` (`NOT NULL`). The schema
change above, and the harder "where does a run-less module's stage-1 input/aggregate scope come
from" design question, is deferred to the increment that actually builds manual editing — see
`docs/21_module_set_first_increment.md` for the as-implemented statement of this.

**A second, independent schema-reality finding, also resolved by a guard rather than a schema
change:** `submit_hierarchical_run`'s own `model_id: UUID | None = None` parameter confirms a
hierarchical run can legitimately have **no** associated `Model` at all (e.g., an exploratory search
never tied to a specific model artifact). Since the approved decision requires every set version to
pin "exactly one model version," **draft creation is rejected outright (a structured 4xx, never a
crash) for a run whose own `model_id` is `NULL`** — there is no model version to pin, and this
increment does not attempt to let a user supply one standing in for the run's own missing
association. This is a narrow-slice scoping decision, not a conflict requiring a redesign.

**No migration/backfill of existing `ModelModule` rows is proposed or needed**, now or later. An
existing, already-materialized module stays exactly as it is — still fully simulatable/
calibratable/validatable today, unaffected by whether anyone ever wraps it in a module set. It
becomes *discoverable as a draft candidate* only when a user explicitly creates a draft from its
owning run (see [§4](#4-lifecycle-rules)) — never retroactively, automatically, or silently
relabeled as "already a module set." This is the direct answer to "representation or migration of
existing run-derived modules without fabricated provenance": there is no migration, because a
migration would have to either leave old rows un-set-affiliated (fine, and what this increment
already does for free) or fabricate a "set" that a human never actually reviewed, named, and saved
(never acceptable).

## 3. Proposed entities and relationships

All new tables follow this schema's own established conventions: UUID primary keys (client-side
`uuid4()`), `created_at`/`updated_at` only where a row is genuinely revised in place (never on an
append-only/immutable row), `ON DELETE RESTRICT` as the default, `CASCADE` reserved for a child row
with no independent meaning apart from its parent, free-text `*_by` fields (no auth system exists;
see `docs/15`'s own "Authentication / authorization: Missing" finding — unchanged by this proposal).

```
Project 1───* Subproject 1───* ModuleSet 1───* ModuleSetVersion 1───* ModuleSetMember *───1 ModelModule
                                   │                    │                                      │
                                   │                    └──(base_version_id, self-FK)          │
                                   │                                                            │
                                   └───────────────────────────────────* ModuleSetDraft         │
                                                                              │                  │
                                                                              └──1───* ModuleSetDraftMember
                                                                                            │
                                                              (model_module_id, nullable) ──┘
```

### `ModuleSet` — durable identity, nothing else

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `subproject_id` | UUID FK → `subproject.id`, `RESTRICT`, indexed | A module set belongs to one Modeling Study — matches "All Modules" being a per-study catalog (`60:756`'s own subtitle: "ACC1 perturbation · Module sets grouped by model and version"). |
| `stable_identifier` | String, NOT NULL | e.g. `"MS-001"`. Assigned **atomically at the moment "Save as new module set" is confirmed** — never pre-assigned to a draft (Figma, `112:719`: *"New set ID: assigned only when you confirm"*). Study-scoped sequential allocation (implementation detail, not consequential). |
| `name` | String, NOT NULL | e.g. `"Expert partition"`. Free text, user-entered/confirmed at save time. **Not** uniquely constrained — `stable_identifier` is the true identity; two sets may share a name (Figma shows this is expected, not an error: "Expert partition" vs. "Expert partition — alternative" are two distinct sets). |
| `created_at` | timestamptz | Set once, at first-version save. |

No `model_id` here. A set's identity is independent of any one model version — see
[§9](#9-decisions-resolved-and-the-one-still-deferred) for why this is flagged rather than
simply asserted.

### `ModuleSetVersion` — immutable, versioned, pinned to one model

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `module_set_id` | UUID FK → `module_set.id`, `RESTRICT`, indexed | |
| `version` | Integer, NOT NULL | 1-based, strictly increasing per `module_set_id`, **never reused or decremented** — the identical idiom `ModuleAggregate.version`/`CrossModuleDiagnosticRun.version` already establish in this schema (`docs/12`, `docs/13`). |
| `model_id` | UUID FK → `model.id`, `RESTRICT` | **The pin.** Immutable once the version is saved — "immutable versions pinned to a model version." **Decided:** a set's identity (`ModuleSet`) may span model versions — a later version of the same set is free to pin a different `model_id` than an earlier one. Changing the pin on a new version is a distinct, explicit action ("revalidation") from an ordinary same-model new version; this increment does not build that path at all (every version it can create pins the same, single model its one supported draft source — an existing run — already names), so no version created by increment 1 ever differs from its set's prior version's own `model_id`. A future increment that lets a user deliberately re-pin must make the revalidation step explicit (re-derive/confirm structural interfaces against the new model before saving), never silent. |
| `origin_method` | `ModuleSetOriginMethod` (`AUTOMATED`/`MANUAL`/`MIXED_EDITED`), NOT NULL | **Decided:** tracked per version (not per member — deferred, see [§10](#10-deferred--open-questions)), including the `MIXED_EDITED` case (a version that started from an existing/automated base but was then hand-edited before saving). User-confirmed at save time (Figma always shows exactly one "Method:" line per save screen) — a holistic label for *this save action*; see [§5](#5-manualautomated-origin-and-generation-run-provenance). Increment 1 only ever produces `AUTOMATED` (its one draft source is an existing, unedited automated run) — `MANUAL`/`MIXED_EDITED` are reachable only once editing is built, but the enum already carries all three so that a later increment never needs a migration to widen it. |
| `generation_run_record_id` | UUID FK → `run_record.id`, `RESTRICT`, nullable | The hierarchical-search run whose output this version's initial draft was seeded from, if any. `NULL` for a version built from scratch with no automated search behind it at all. |
| `base_version_id` | UUID FK → `module_set_version.id`, `RESTRICT`, nullable, self-referential | "Draft based on MS-001 v1" (Figma `112:672`) — recorded **regardless of whether the save becomes a new set or a new version of an existing one**; this is what resolves the audit's own flagged ambiguity (see [§5](#5-manualautomated-origin-and-generation-run-provenance)). |
| `version_note` | Text, nullable | Free text, user-entered at save time. |
| `saved_at` | timestamptz, NOT NULL | |
| `saved_by` | String, nullable | Free text, matching `decided_by`/`reviewed_by`'s own zero-auth convention elsewhere. |

No `updated_at` — once saved, a version is never revised in place, matching `ModuleExecutionSnapshot`'s
own "no persistence function anywhere issues an `UPDATE`" discipline exactly.

### `ModuleSetMember` — immutable, one row per module in one saved version

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `module_set_version_id` | UUID FK → `module_set_version.id`, `CASCADE`, indexed | `CASCADE`: a member row has no independent meaning apart from the version it belongs to — the same "no independent existence apart from its parent" precedent `CrossModuleDiagnostic` already uses from `CrossModuleDiagnosticRun`. |
| `model_module_id` | UUID FK → `model_module.id`, `RESTRICT`, **NOT NULL** | Always set once saved — the invariant "every saved member is a real, executable module" (see [§2](#2-the-central-reconciliation-what-is-an-executable-module-really)). |
| `created_at` | timestamptz | = the owning version's own `saved_at`. |

**As implemented in increment 1** (deliberately simpler than the full design below): no
`module_identity_id`, `parent_member_id`, or `name` column. Increment 1 only ever creates members
that reference a pre-existing, unedited `ModelModule`, so `model_module_id` itself already *is* a
stable, sufficient identity — a separate `module_identity_id` is redundant until editing/split/
merge can produce a member with no single corresponding prior `ModelModule`. Hierarchy
(which member is whose child) is never duplicated onto this table either — it is derived at read
time by resolving each member's own `model_module_id → ModelModule.parent_model_module_id` and
matching it against sibling members' own `model_module_id`s within the same version; a parent
module not itself included in this version simply has no matching sibling, a legitimate,
inspectable state (see `docs/21`). Display name is likewise not invented here: `ModelModule` has no
`name` column of its own today, and fabricating one (`"Acetyl-CoA supply"`-style, as Figma's mock
does) would invent data this schema does not have — the GUI shows the module's real
`stable_identifier`/`module_id`/`"Not captured"` instead, this project's own established honesty
convention (`docs/16`–`19`). `module_identity_id`/`parent_member_id`/`name` remain exactly as
specified in the full design below for the increment that builds editing.

### `ModuleLineageEdge` — append-only, explicit split/merge facts only (deferred — not created by increment 1's migration)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `predecessor_identity_id` | UUID, indexed | A `module_identity_id` that existed *before* this transition. |
| `successor_identity_id` | UUID, indexed | A `module_identity_id` that exists *after* it. |
| `relationship` | `ModuleLineageRelationship` (`SPLIT`/`MERGE`) | |
| `recorded_in_version_id` | UUID FK → `module_set_version.id`, `RESTRICT` | Which save action asserted this fact. |
| `created_at` | timestamptz | |

A simple rename, or a version with no membership change for a given module, needs **no edge row at
all** — it is already represented for free by the successor member simply reusing the identical
`module_identity_id`. Edges exist only for the genuinely ambiguous cases (one module becoming two,
or two becoming one), where a stable 1:1 id cannot honestly describe what happened — an explicit,
user-asserted fact, never inferred from name or membership-overlap heuristics. Not required by the
smallest implementation slice ([§8](#8-recommended-smallest-implementation-slice)), but defined
here because the task explicitly asks for "membership... and continuity across edits" semantics up
front, before any split/merge editing UI is built.

### `ModuleSetDraft` — mutable working state

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `subproject_id` | UUID FK → `subproject.id`, `RESTRICT` | |
| `model_id` | UUID FK → `model.id`, `RESTRICT` | Which model version this draft is scoped to (shown on every draft screen: "Curated fatty acid model v1.3 · ..."). |
| `module_set_id` | UUID FK → `module_set.id`, `RESTRICT`, nullable | `NULL` until the user chooses "save as new module set" vs. "save new set version" **at save time** — a draft is not yet attached to any set identity (Figma `112:719`: "New set ID: assigned only when you confirm"). |
| `base_version_id` | UUID FK → `module_set_version.id`, `RESTRICT`, nullable | "Draft based on MS-001 v1." |
| `base_run_record_id` | UUID FK → `run_record.id`, `RESTRICT`, nullable | Set instead of `base_version_id` when a draft is seeded straight from a hierarchical search's own raw output that has never been saved as any set before. At most one of `base_version_id`/`base_run_record_id` is set (both `NULL` is also valid — a from-scratch manual draft). |
| `origin_method` | `ModuleSetOriginMethod`, NOT NULL | Mutable while the draft is open (a human may start from an automated base and then hand-edit it); frozen into the saved version's own `origin_method` at save time. |
| `status` | `ModuleSetDraftStatus` (`OPEN`/`SAVED`/`DISCARDED`), NOT NULL, default `OPEN` | |
| `resulting_version_id` | UUID FK → `module_set_version.id`, `RESTRICT`, nullable | Set exactly when `status` transitions to `SAVED`. |
| `created_at`/`updated_at` | timestamptz | `updated_at` advances on every draft edit. |
| `created_by`/`updated_by` | String, nullable | Free text. |

A partial unique index enforces **at most one open draft per existing set at a time**:
`UNIQUE (module_set_id) WHERE status = 'OPEN' AND module_set_id IS NOT NULL` — a from-scratch draft
(`module_set_id IS NULL`) is exempt, since it has no existing set to conflict with.

**Decided and as implemented in increment 1:** a `DISCARDED` draft is never hard-deleted (soft-
marked via `status`) and is excluded from every normal listing query by default (`list_drafts`
filters `status = OPEN` unless explicitly asked to include discarded ones) — and, as with every
draft regardless of status, **can never be a target of execution**: no API surface anywhere accepts
a `module_set_draft_id`/`module_set_draft_member_id` as a simulate/calibrate/validate target (only
a bare `model_module_id` is ever accepted, unchanged).

### `ModuleSetDraftMember` — mutable, freely rewritable while the draft is open

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `draft_id` | UUID FK → `module_set_draft.id`, `CASCADE` | No independent meaning apart from its draft. |
| `module_identity_id` | UUID, NOT NULL | Minted once (new `uuid4()`) the first time a module is introduced into any draft lineage; carried forward unchanged across edits/re-drafts of "the same" module. |
| `parent_draft_member_id` | UUID FK → `module_set_draft_member.id`, `CASCADE`, nullable (within the same draft) | |
| `name` | String, NOT NULL | User-editable (rename). |
| `model_module_id` | UUID FK → `model_module.id`, `RESTRICT`, nullable | Set when this draft member is an **unedited** reference to an existing materialized module (inherited verbatim from `base_run_record_id`/`base_version_id`). **Cleared the moment its own membership is edited** — the signal that a fresh `ModelModule` must be materialized at save time. |
| `membership_payload` | Text (opaque JSON), nullable | Populated only when `model_module_id IS NULL` — this member's own reaction/species/parameter composition, in the **same wire shape** the harness's own modularization "memberships" array already uses (reused, never reinvented — matching `attach_payload`'s own "opaque, store-never-parse" discipline). |
| `updated_at` | timestamptz | |

**As implemented in increment 1:** only `id`, `draft_id`, `model_module_id` (`NOT NULL` — every
draft member in this increment always references an existing module; nothing is ever created
without one), and `created_at` exist. `module_identity_id`, `parent_draft_member_id`, `name`, and
`membership_payload` are not part of increment 1's migration at all — adding them later (once
editing is built) is a straightforward additive `ALTER TABLE`, not a redesign, so deferring the
columns themselves (not just the UI) avoids shipping dead, unused schema surface now. The same
"derive hierarchy at read time from `model_module_id`'s own parent chain, never invent a name"
reasoning given for `ModuleSetMember` above applies identically here.

## 4. Lifecycle rules

1. **A draft is created** from exactly one of: an existing `ModuleSetVersion` (`base_version_id`
   set — "reopen and continue editing"), a raw hierarchical `RunRecord` that was never saved as any
   set (`base_run_record_id` set — "start from an automated search's own output"), or neither
   (a from-scratch manual draft). Creating a draft from a base **copies** that base's member
   structure into fresh `ModuleSetDraftMember` rows (carrying `module_identity_id` forward
   unchanged, and `model_module_id` forward unchanged for anything not yet edited) — it never
   mutates the base itself.
2. **A draft is freely editable** while `status = OPEN`: rename a member, change its membership
   (clearing `model_module_id`, populating `membership_payload`), add/remove a member. (Split/merge/
   membership-editing *UI* is explicitly out of scope for the smallest slice,
   [§8](#8-recommended-smallest-implementation-slice) — the schema supports it; the first build does
   not expose it.)
3. **A draft is never itself simulatable/calibratable/validatable.** Only a saved member (one that
   resolves to a real `ModelModule.id`) can be sent to Agent 3/4/5 — identical to today's existing
   rule that only a `SIMULATION_READY` `ModelModule` can be, just one layer further out.
4. **Discard**: `status → DISCARDED` (soft-marked, never hard-deleted — decided, see
   [§9](#9-decisions-resolved-and-the-one-still-deferred)). No `ModuleSetVersion`/`ModuleSetMember`/
   `ModelModule` row is ever created. A discarded draft is excluded from every default listing
   query and can never be a target of execution.
5. **Save**, in either mode, is one atomic transaction:
   - Resolve or create the target `ModuleSet` (new row if "save as new module set"; existing row,
     looked up by id, if "save new set version" — `module_set_id` on the draft is set either way as
     part of this same transaction, never before).
   - Allocate the next `version` (1 for a new set; `max(version)+1` for an existing one — this is
     the **direct resolution of the audit's own flagged ambiguity**: version numbers are allocated
     per-`ModuleSet`, atomically, at save time, independent of `origin_method`. Two independent
     draft attempts — one manual, one automated — against the same set cannot both become "v2":
     whichever is confirmed first takes v2, and the other, saved after it, becomes v3. There is no
     scenario in this design where two saves share a version number.)
   - For every `ModuleSetDraftMember`: if `model_module_id` is already set, reuse it verbatim (no
     new row). If `NULL`, materialize a new `ModelModule` row (`run_record_id = NULL`,
     `module_set_version_id = <this version>`, membership from `membership_payload`, boundary ports
     freshly derived — see [§7](#7-structural-interfaces-versus-execution-specific-boundary-treatments)),
     then create the `ModuleSetMember` pointing at it. **Increment 1 never reaches this branch at
     all** — every draft member it can ever produce already has `model_module_id` set, by
     construction (its only draft source is an unedited automated run); the branch, and the schema
     change it depends on, apply only once editing is built (see
     [§2.1](#21-dependency-audit-and-resolution-for-increment-1)).
   - Mark the draft `status = SAVED`, `resulting_version_id = <this version>`. Save is **idempotent
     by draft**: a draft can be saved at most once (enforced by the `status` transition itself —
     `save` on a non-`OPEN` draft is rejected with a structured 409, returning the already-resulting
     version rather than creating a duplicate one).
6. **Reopen**: `GET` a saved `ModuleSetVersion` is always read-only — inspecting it never creates or
   mutates anything. Editing a saved version means creating a **new draft** based on it
   (`base_version_id` set); the original version is never touched.
7. **A module set and every one of its versions are permanent** once saved — there is no delete/
   archive path in this proposal (none was requested, and `ON DELETE RESTRICT` throughout means
   nothing upstream can be deleted out from under a saved version regardless).

## 5. Manual/automated origin and generation-run provenance

`origin_method` lives on `ModuleSetVersion` (and, while open, on `ModuleSetDraft`) as **one
holistic, user-confirmed label per save action** — matching the Figma screens exactly (every draft/
save screen shows exactly one "Method:" line, never a per-module breakdown). Per-member origin
tracking (distinguishing "this specific module within the version was hand-edited" from "this one
was inherited untouched") is a real, honest refinement this schema does not prevent adding later
(it would be one more nullable column on `ModuleSetMember`), but is **not required** for this
contract — see [§10](#10-deferred--open-questions) — because nothing in the current Figma file or
task scope exercises mixed-origin display, and inventing that UI now would be scope creep beyond
"define the domain model."

`generation_run_record_id` is a **provenance pointer**, never an identity: it answers "which
hierarchical search, if any, produced the content this version started from," purely for
traceability (e.g. "this automated partition's module boundaries were derived from run
`<uuid>`'s own topology"). It is explicitly *not* how a module set's own version lineage is tracked
— that is `base_version_id`, which can point to a prior version of the *same* set, a version of a
*different* set, or be `NULL` entirely, independent of whether a generation run exists at all. This
separation is what keeps "do not simply rename hierarchical runs as module sets" true in the schema
itself: a `RunRecord` remains exactly what it already is (one harness execution record); a module
set's own history is tracked entirely through `ModuleSetVersion.base_version_id`, a chain that can
span many runs, no runs, or the same run reused by several independent sets.

## 6. Module identity, hierarchy, membership, and continuity across edits

Three distinct concerns, each given its own mechanism, deliberately never conflated:

- **Hierarchy** (which module contains which, structurally): `parent_member_id`/
  `parent_draft_member_id`, a plain self-referential tree per version/draft — the direct analogue of
  `ModelModule.parent_model_module_id`/`depth`, just scoped to a set-version instead of a run.
- **Membership** (which reactions/species/parameters a module actually contains): either inherited
  verbatim from an existing `ModelModule` (the common case — nothing new to represent) or an opaque
  `membership_payload` in the harness's own existing wire shape (the edited case) — never a second,
  parallel representation of what membership even means.
- **Continuity across edits** (is this "the same" module as one in an earlier version?):
  `module_identity_id`, a stable UUID minted once and carried forward through every edit that is
  *not* a split or merge (rename, membership tweak, moving to a different parent — all preserve it).
  A split or merge is the one case a single stable id cannot honestly express — handled by minting
  **new** identity ids for the result(s) and recording the relationship as an explicit
  `ModuleLineageEdge`, never inferred from name or content overlap. This directly satisfies the "All
  Modules" screen's own stated caveat (*"Identical names across sets do not establish module
  identity"*) by construction: identity is never derived from `name` anywhere in this design,
  `module_identity_id` is the only authority, and two members can share an identical `name` (as the
  "Expert partition"/"Expert partition — alternative" sets already do at the *set* level) without
  being mistaken for the same thing.

## 7. Structural interfaces versus execution-specific boundary treatments

Already well-separated in the *existing* schema, and this proposal keeps the identical separation at
the set-member level:

- **Structural interface**: which species cross a module's own boundary, and in which direction
  (`INPUT`/`OUTPUT`/`INPUT_OUTPUT`) — a pure, re-derivable **fact of the partition**, computed from
  "which reactions are inside this member vs. outside it," identical in kind to what
  `module_boundary_orchestrator.derive_boundary_ports` already computes for a hierarchy-search
  module today. For a member that references an existing, unedited `ModelModule`, its structural
  interface is simply that `ModelModule`'s own already-derived `ModuleBoundaryPort` rows — nothing
  new to compute. For a genuinely edited/new member, the identical derivation algorithm must be
  re-run, but **retargeted**: today it is computed against one hierarchy search's own output
  partition; here it must be computed against the **whole saved version's own membership** (every
  sibling member's own composition), because "what's outside this module" now depends on a
  human-specified partition, not the search's own. This is a real integration point, named
  explicitly as a gap in [§11](#11-reuse-inventory-and-genuine-gaps) — the underlying topology
  computation is reused unchanged; only what it is pointed at changes.
- **Execution-specific boundary treatment**: `treatment_type`/`initial_value`/`unit`/`decided_by` —
  a human's scientific judgment about how to treat a given boundary species for actual execution.
  This already lives on `ModuleBoundaryPort`, keyed to `ModelModule`, and **stays exactly there** —
  once a set-version save materializes a fresh `ModelModule` row for an edited member, that row
  gets its own fresh `ModuleBoundaryPort` rows (derived `UNRESOLVED`/`PENDING_REVIEW`, exactly like
  any other newly-materialized module today), to be decided through the *existing*
  `submit_boundary_decision` function, completely unchanged. A member that reuses an existing,
  unedited `ModelModule` likewise reuses that module's own already-decided boundary ports verbatim —
  no copying, no new table, no new concept. The distinction the task asks for (structural vs.
  execution-specific) is therefore not a new schema split this proposal must invent — it is the
  split `ModuleBoundaryPort`'s own fields already express (`species_id`/`direction`, derived, vs.
  `treatment_type`/`initial_value`/`decided_by`, decided) — module sets simply inherit it by routing
  every member to a real `ModelModule`.

## 8. Recommended smallest implementation slice

**Supports exactly:** draft (from an existing automated hierarchical run, unedited) → inspect its
hierarchy and structural boundaries (read-only) → explicitly save (as a new set, or a new version of
an existing one) → reopen (read-only). **Does not yet support:** manual authoring, split, merge,
rename, or any boundary-*decision* UI (none exists in this repository today for any module, set or
not — out of scope for this slice specifically because it is a pre-existing, larger gap, not a
module-set-specific one).

**As actually implemented (see `docs/21_module_set_first_increment.md` for the full report):**
- Migration: `module_set`, `module_set_version`, `module_set_member`, `module_set_draft`,
  `module_set_draft_member` tables only — **no `module_lineage_edge` table, no `model_module`
  column changes**, both deferred per [§2.1](#21-dependency-audit-and-resolution-for-increment-1).
  New enums `ModuleSetOriginMethod` (3 values), `ModuleSetDraftStatus`.
- `app/persistence/module_set.py`: draft creation (from an existing, model-bearing, `SUCCEEDED`
  hierarchical run only), read, discard, and save (new-set/new-version), plus a small addition to
  `app/persistence/run_record.py` to list a study's own draftable hierarchical runs.
- No new orchestrator call into the harness — nothing here reaches Agent 2/3/4/5; an unedited
  draft's structural boundaries are already fully derived on the underlying `ModelModule` rows from
  whatever hierarchy run produced them, read via the existing `list_boundary_ports_for_module`.

**New frontend (illustrative):** a read-only "module set draft" screen (hierarchy tree + each
member's own already-derived boundary ports, display-only), the two save dialogs, the saved
confirmation screen, and a read-only "reopen" detail screen — all four already have a concrete
Figma reference (`112:672`/`719`/`766`/`831`) to build against; the "All Modules" catalog
(`60:756`) as the entry point. No split/merge/rename controls, matching the audit's own finding
that the current Figma mock promises but never implements them either.

**Explicitly deferred to a later slice:** manual draft authoring/editing (membership payload
construction, re-derivation of boundaries across a whole edited partition —
[§7](#7-structural-interfaces-versus-execution-specific-boundary-treatments)'s named integration
gap), `ModuleLineageEdge` creation (no split/merge UI exists yet to produce one), the "Compare
modularizations" screen's own "Save as new module set" action (depends on this slice existing
first), per-member origin tracking ([§10](#10-deferred--open-questions)).

## 9. Decisions (resolved) and the one still deferred

The four items originally raised here have been decided by the project owner:

1. **~~Relaxing `ModelModule.run_record_id` to nullable~~ — superseded.** Confirmed via a direct
   dependency audit ([§2.1](#21-dependency-audit-and-resolution-for-increment-1)) that applying this
   change *now*, without first designing a replacement stage-1-input resolution path and a defined
   aggregation/diagnostics behavior for a run-less module, would break four already-shipped
   execution/derivation entrypoints. **Decision: defer the schema change itself** to whichever
   increment actually builds manual editing/split/merge (the only thing that would ever need it);
   increment 1 reuses `ModelModule` purely by reference, never by relaxing its schema.
2. **A set's identity may span model versions.** Each `ModuleSetVersion` immutably pins exactly one
   model version at save time; a later version of the same set may pin a different one, but doing
   so deliberately is a distinct, explicit "revalidation" action (re-derive/confirm structural
   interfaces against the new model), never a silent side effect of an ordinary new-version save.
   Not built in increment 1 (no path in this slice ever produces two versions of a set pinning
   different models) — see [§8](#8-recommended-smallest-implementation-slice).
3. **Discarded drafts are soft-marked, hidden from normal listings, and can never execute.**
   Implemented exactly as stated — see the `ModuleSetDraft` table notes above.
4. **Origin is tracked per version, not per member; editing is deferred.** `ModuleSetOriginMethod`
   now has three values (`AUTOMATED`/`MANUAL`/`MIXED_EDITED`), carried on `ModuleSetVersion`/
   `ModuleSetDraft` only. Per-member origin remains a documented, schema-compatible future addition
   ([§10](#10-deferred--open-questions)).

Every other choice in this document (table/column names, index shapes, `CASCADE`/`RESTRICT`
assignments, the stable-identifier allocation scheme, the uniqueness-of-open-draft constraint) is
treated as routine — resolved here by direct analogy to an already-established convention elsewhere
in this schema, with the specific precedent cited inline, and not relitigated in this list.

## 10. Deferred / open questions

- Per-member origin tracking (distinguishing which specific modules within a version were hand-
  touched) — not built now; the schema does not preclude adding it later as one more nullable
  column.
- A `ModuleSet`/`ModuleSetVersion` update/delete/archive path — none requested, none proposed.
- Whether `ModuleLineageEdge` should also record a *rename-only* edit distinctly from "no change at
  all" for audit purposes (currently both are represented identically — nothing recorded, since the
  `module_identity_id` carries forward either way and `ModuleSetMember.name` is simply whatever the
  save action set it to). A rename is not a lineage fact in this design, only a display fact.
- Dataset-scoping interaction: `DatasetReference.subproject_id` is nullable (project-wide) while
  `subproject_id` is required elsewhere — this proposal introduces no new dataset-reference
  interaction, so this is noted only to flag that it was considered and found irrelevant here.

## 11. Reuse inventory and genuine gaps

| Capability this proposal needs | Reused unchanged | New |
|---|---|---|
| Boundary-port derivation algorithm (reaction-participant topology → candidate ports) | ✅ `module_boundary_orchestrator.derive_boundary_ports`'s own core logic | Retargeting it to a whole edited set-version's own membership instead of one hierarchy run's output partition ([§7](#7-structural-interfaces-versus-execution-specific-boundary-treatments)) — a genuine, named gap, not yet built anywhere. |
| Boundary *decision* submission/review | ✅ `submit_boundary_decision`, `evaluate_module_execution_status` | None — a freshly materialized member's `ModelModule` row goes through the identical existing flow. |
| Module-level simulate/calibrate/validate | ✅ unchanged, operates on `model_module_id` exactly as today | None. |
| Partition comparison (reaction-membership agreement, boundary-interface diffs) | ✅ `cross_module_diagnostics_orchestrator` — rated by `docs/15` as "the single strongest existing match in the whole file" | A thin new query resolving "which `ModelModule` ids belong to version X" from `ModuleSetMember`, so two versions' own member lists can be handed to the existing orchestrator unchanged. |
| Result aggregation / executable model composition | ✅ `module_aggregation_orchestrator` — already scoped per `ModelModule`/hierarchy run, untouched | None — explicitly kept distinct per the task's own instruction; a module set never becomes an input to aggregation's own logic, only a different way of *naming* which `ModelModule`s to look at. |
| Versioned, fingerprint-idempotent immutable snapshot idiom | ✅ the exact pattern `ModuleAggregate`/`CrossModuleDiagnosticRun` already establish, reused for `ModuleSetVersion.version` | None new. |
| Stable sequential display identifiers scoped to a parent | ✅ precedent: `Project.stable_identifier`/`Model.stable_identifier` | A study-scoped allocator for `ModuleSet.stable_identifier` ("MS-00N") — small, new, no existing helper does this exact scoping today. |
| GUI read-only draft/save/reopen screens | — | All new frontend (no module-set screen exists in the Workbench's own built GUI yet; Figma-only today). |

## 12. API request/response examples (illustrative — not implemented)

**Create a draft from an existing automated run:**
```
POST /api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts
{
  "model_id": "5e2f...",
  "base_run_record_id": "9a11...",
  "origin_method": "AUTOMATED"
}
→ 201
{
  "id": "draft-7c3e...",
  "status": "OPEN",
  "model_id": "5e2f...",
  "base_run_record_id": "9a11...",
  "base_version_id": null,
  "module_set_id": null,
  "origin_method": "AUTOMATED",
  "members": [
    {"id": "...", "module_identity_id": "...", "name": "Acetyl-CoA supply",
     "model_module_id": "mm-001", "parent_draft_member_id": null},
    {"id": "...", "module_identity_id": "...", "name": "Fatty acid synthesis",
     "model_module_id": "mm-002", "parent_draft_member_id": null},
    {"id": "...", "module_identity_id": "...", "name": "Cofactor recycling",
     "model_module_id": "mm-003", "parent_draft_member_id": null}
  ]
}
```

**Inspect one member's own structural interface (read-only, derived from its `model_module_id`):**
```
GET /api/v1/.../module-set-drafts/{draft_id}/members/{member_id}/boundary-ports
→ 200
[
  {"port_id": "port::mm-001::ACoA::OUTPUT", "species_id": "ACoA", "direction": "OUTPUT",
   "treatment_type": "UNRESOLVED", "resolution_status": "PENDING_REVIEW"}
]
```

**Save as a new module set:**
```
POST /api/v1/.../module-set-drafts/{draft_id}/save
{"mode": "new_set", "set_name": "Expert partition", "version_note": "Initial manual review.",
 "saved_by": "Morgan Lee"}
→ 201
{
  "module_set": {"id": "...", "stable_identifier": "MS-001", "name": "Expert partition"},
  "version": {"id": "...", "version": 1, "model_id": "5e2f...", "origin_method": "AUTOMATED",
              "generation_run_record_id": "9a11...", "base_version_id": null,
              "saved_at": "2026-10-20T19:04:00Z", "saved_by": "Morgan Lee"},
  "members": [
    {"model_module_id": "mm-001", "module_identity_id": "...", "name": "Acetyl-CoA supply"},
    {"model_module_id": "mm-002", "module_identity_id": "...", "name": "Fatty acid synthesis"},
    {"model_module_id": "mm-003", "module_identity_id": "...", "name": "Cofactor recycling"}
  ]
}
```

**Save a new version of an existing set:**
```
POST /api/v1/.../module-set-drafts/{draft_id}/save
{"mode": "new_version", "existing_set_id": "<MS-001's id>",
 "version_note": "Reviewed module membership and interfaces.", "saved_by": "Morgan Lee"}
→ 201   (same shape; version.version == 2, module_set unchanged)
```

**Attempting to re-save an already-saved/discarded draft:**
```
POST /api/v1/.../module-set-drafts/{draft_id}/save   (draft.status == "SAVED")
→ 409
{"detail": {"code": "CONFLICT", "message": "This draft was already saved as version 2.",
            "context": {"resulting_version_id": "..."}}}
```

**Reopen (read-only):**
```
GET /api/v1/.../module-sets/{set_id}/versions/2
→ 200  (full ModuleSetVersion + members, identical shape to the save response above)
```

**Ownership enforcement** (matching `docs/17`–`19`'s own established "404 identical to not-found,
never a cross-boundary leak" convention exactly): a `module_set_id`/`version`/`draft_id` that exists
but belongs to a different `subproject_id`/`project_id` than the URL's own path parameters 404s
identically to one that does not exist at all.

## 13. Figma action → API mapping

| Figma screen / action (node) | API call |
|---|---|
| "05 — Module set draft" (`112:672`/`1521`) loads | `GET .../module-set-drafts/{id}` |
| "Discard draft" | `POST .../module-set-drafts/{id}/discard` |
| "Save as new module set" (`112:719`) | `POST .../module-set-drafts/{id}/save` (`mode: "new_set"`) |
| "Save new set version" (`112:831`) | `POST .../module-set-drafts/{id}/save` (`mode: "new_version"`) |
| "Confirm save" on either save screen | same call as above, fired on confirm, not on navigating to the screen |
| "Cancel — return to draft" | no call — purely a client-side navigation back |
| "Module set saved" (`112:766`) → "Return to module sets" | `GET .../module-sets` (the "All Modules" catalog) |
| "06 — All Modules" (`60:756`) loads | `GET .../module-sets` (grouped client-side by `model_id`+`model.version_label`, matching the screen's own grouping) |
| "Select a set to inspect its modules" | `GET .../module-sets/{set_id}/versions/{version}` |
| "Compare modularizations" (`48:923`) loads | existing `cross_module_diagnostics_orchestrator` call, given the two versions' own resolved `model_module_id` lists (new thin resolution query only, per [§11](#11-reuse-inventory-and-genuine-gaps)) |
| "Save as new module set" from the compare screen | `POST .../module-set-drafts` seeded from the chosen version, then the normal save flow |

## 14. Acceptance tests (for the smallest slice, §8)

1. **Draft creation copies, never mutates, its base.** Given a `RunRecord` with 3 materialized
   `ModelModule` rows, creating a draft from it produces 3 `ModuleSetDraftMember` rows each with
   `model_module_id` set and a freshly-minted, distinct `module_identity_id`; the original
   `ModelModule`/`HierarchyNode`/`RunRecord` rows are unchanged (confirmed by re-reading them after).
2. **Save-as-new-set assigns identity only at confirm time.** Before saving, the draft's own
   `module_set_id` is `NULL` and no `ModuleSet` row with any related `stable_identifier` exists.
   After `save(mode="new_set", ...)`, exactly one new `ModuleSet` (version 1) and 3 `ModuleSetMember`
   rows exist, each pointing at the *original* `model_module_id`s (no new `ModelModule` rows
   created, since nothing was edited).
3. **Save-new-version allocates the next integer, never reuses one.** Given an existing set at
   version 1, saving a second, independent draft against it with `mode="new_version"` produces
   version 2; saving a third produces version 3 — regardless of the `origin_method` of any of the
   three saves (the audit's own flagged ambiguity, directly tested).
4. **Discard creates nothing.** After `discard`, no `ModuleSet`/`ModuleSetVersion`/`ModuleSetMember`/
   new `ModelModule` row exists anywhere; the draft's own `status` is `DISCARDED`.
5. **Reopen is read-only and exact.** `GET` on a saved version returns the identical `model_id`,
   member list, and `module_identity_id`s as the save response; no column on `ModuleSetVersion`/
   `ModuleSetMember` changes value between two consecutive reads.
6. **Existing `ModelModule` rows are untouched by the whole flow.** Before and after any draft/
   save/discard sequence above, every pre-existing `ModelModule` row's own `run_record_id`,
   `execution_status`, and boundary-port rows are byte-identical to before — confirming no
   migration/fabrication occurred.
7. **Ownership/404 enforcement.** A version/draft/set id that exists but belongs to a different
   study or project 404s identically to an unknown id, never leaking which study it actually
   belongs to (same assertion style as `tests/api/test_model_detail.py`'s own ownership-mismatch
   tests in this repository today).
8. **A module set never becomes simulatable/calibratable/validatable itself.** There is no API
   surface that accepts a `module_set_version_id` or `module_set_member_id` as a target for
   `request_module_simulation`/`calibration`/`validation` — every such call still takes a bare
   `model_module_id`, confirming module sets remain a pure curation/versioning layer, never a
   second execution entrypoint.
9. *(For a later slice, once lineage editing exists)* **A split/merge always produces a new
   `module_identity_id` for its result(s), never reuses the predecessor's.** A plain rename or
   membership-preserving move never creates a `ModuleLineageEdge` row.

---

**Status:** all four decisions in [§9](#9-decisions-resolved-and-the-one-still-deferred) are
resolved. The first implementation increment built against this revised contract is reported in
`docs/21_module_set_first_increment.md`. The second increment -- module renaming and
reaction-membership editing, still never touching the `ModelModule` schema change -- is reported
in `docs/23_module_set_manual_editing_increment.md`. Split/merge and per-member origin tracking
remain deferred.
