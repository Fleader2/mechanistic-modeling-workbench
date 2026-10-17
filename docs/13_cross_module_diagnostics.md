# Cross-Module Consistency and Reconciliation Diagnostics

See `docs/12_hierarchical_aggregation.md` for the increment this one builds alongside (a
genuinely separate concern -- aggregation answers "what happened in each branch, and is
coverage complete"; this increment answers "do the branches *contradict* each other in ways
that matter scientifically").

## Goal

Detect and persist scientifically meaningful inconsistencies across sibling/parent-child
modules -- without ever automatically forcing reconciliation, averaging a conflicting value,
or claiming the hierarchy is globally valid just because no conflict was found.

## Why this is a Workbench-only change

Every comparison reads only already-persisted `ModelModule`/`ModuleBoundaryPort`/
`RunRecord`/`ModuleExecutionSnapshot` rows (task instructions §7) -- no agent or harness call
happens anywhere in this increment. This increment touches only
`mechanistic-modeling-workbench`.

## Diagnostic taxonomy

`CrossModuleDiagnosticCategory` is a 1:1 mapping onto task instructions §2's own seven
numbered detection requirements -- every finding's own category already says which specific
comparison produced it, never a catch-all "something looks wrong" bucket:

1. `SHARED_BOUNDARY_SPECIES_CONFLICT` -- the same species, resolved to two different fixed
   values across related modules.
2. `UNIT_INCOMPATIBILITY` -- units differ, or a unit is recorded on only one side (never
   automatically converted or reconciled).
3. `PARAMETER_ASSUMPTION_CONFLICT` -- the same parameter `target_id`, calibrated to two
   different values across related modules.
4. `PARENT_CHILD_BOUNDARY_INCONSISTENCY` -- the category 1 check, specifically between a
   module and its own direct parent.
5. `DATASET_CONTEXT_INCOMPATIBILITY` -- related modules used different calibration/validation
   datasets; compatibility is disclosed as unverifiable, never claimed either way.
6. `CONFLICTING_CALIBRATION_OR_VALIDATION_OUTCOME` -- related modules report heterogeneous
   validation outcomes (one clean, one not).
7. `INSUFFICIENT_EVIDENCE_FOR_COMPARISON` -- a comparison was *attempted* (a real reason to
   compare exists -- a shared boundary species) but could not be concluded because one side's
   own data is missing/unresolved. Never silently skipped.

`DiagnosticSeverity` (`INFO`/`WARNING`/`ERROR`/`UNRESOLVED`) is a genuinely new enum --
confirmed by inspection that no existing one carries this exact vocabulary before adding it
(task instructions §3). `UNRESOLVED` severity is reserved for category 7's own findings:
"the comparison itself could not be concluded," never conflated with "no conflict exists."

## Comparison rules

`app.orchestration.cross_module_diagnostics_orchestrator.run_diagnostics` gathers, for every
module of one hierarchy run, its own already-persisted facts (`_gather_module_facts`:
boundary ports, the latest calibration/validation `RunRecord` and its own snapshot's dataset
references), then compares every **related pair** -- siblings sharing the same parent, and
parent/child pairs (`_related_pairs`, using only `ModelModule.parent_model_module_id`, never
recomputed topology) -- across all seven categories:

* **Boundary conflicts** (categories 1, 4, part of 7): for every species_id shared between two
  related modules' own boundary ports, if either side is still `UNRESOLVED` -> category 7,
  severity `UNRESOLVED`. Otherwise, if both sides are value-bearing
  (`EXTERNALLY_CONTROLLED`/`PRESCRIBED_INPUT`) and the values differ -> category 1/4, severity
  `ERROR`; if the units differ (both present) -> category 2, `WARNING`; if a unit is present
  on only one side -> category 2, `INFO`. If the treatment *kinds* differ (e.g. one
  `DYNAMIC_COUPLING`, the other `EXTERNALLY_CONTROLLED`) without being directly numerically
  comparable -> category 1/4, `WARNING` (a modeling-assumption mismatch, not asserted to be a
  numeric conflict).
* **Parameter conflicts** (category 3): for every `target_id` present in both related
  modules' own latest *successful* calibration, if the fitted values differ -> `ERROR`. A
  `target_id` calibrated in only one of the two is never flagged -- there is nothing to
  compare.
* **Dataset context** (category 5): if both related modules used `dataset_reference_ids` for
  the same kind (calibration or validation) and the sets differ -> `INFO`. Never claims
  compatibility or incompatibility -- this Workbench has no structured unit/condition-matching
  system, so disclosing the difference honestly is the only defensible claim (task
  instructions §4: "never fabricate a reconciliation").
* **Validation outcome heterogeneity** (category 6): if both related modules have a
  validation result and exactly one reports `overall_status == "SUCCESS"` -> `WARNING`. Never
  interpreted as a deeper scientific contradiction -- only reported as heterogeneous.

## Non-destructive by construction

Nothing here ever writes back to a `ModuleBoundaryPort`, `RunRecord`, `ModuleExecutionSnapshot`,
or `ModuleAggregate` -- every detector only *reads* and *reports*. A clean sweep (zero
findings) is never interpreted as "globally valid": `run_diagnostics`'s own return value is
literally a list of findings, nothing more; there is no "hierarchy is consistent" flag
anywhere in this schema (task instructions §4's own explicit constraint, verified directly:
`test_compatible_boundary_values_produce_no_finding` only asserts an empty findings list,
never a positive validity claim).

## Immutability, idempotency, and versioning

`CrossModuleDiagnosticRun` + `CrossModuleDiagnostic` follow the identical immutable,
versioned, fingerprint-idempotent pattern `ModuleAggregate` already established: a sweep's
own `input_fingerprint` (a `sha256` digest of every module's own gathered facts) is checked
against the latest existing run for the same hierarchy run; an unchanged source state returns
the existing run (and its own already-persisted findings) untouched; a changed one creates a
new, separately-numbered version, and the previous version's own findings are never mutated
or deleted.

## The one deliberate mutable exception: review annotation

Task instructions §5 explicitly asks for "mark a diagnostic as reviewed/resolved with a human
note, without altering source results." `app.persistence.cross_module_diagnostic
.mark_finding_reviewed` is the one function in this entire increment (and the only one
introduced across every increment in this session) that issues a real `UPDATE` -- and it is
narrowly scoped to exactly four columns (`review_status`/`review_note`/`reviewed_by`/
`reviewed_at`). The finding's own `category`/`severity`/`message`/`evidence_payload` are
never touched by a review, verified directly
(`test_mark_finding_reviewed_only_touches_review_fields`).

## Provenance

Each finding's own `evidence_payload` carries the full comparison detail that produced it --
the exact species/parameter id, both sides' own compared values, and every contributing
`run_record_id`/`model_module_id` (and, where applicable, `execution_snapshot_id`) --
alongside `affected_model_module_ids`. `get_finding_evidence` surfaces both together for a
caller to verify every reported item against its real source.

## API

`app.orchestration.cross_module_diagnostics_orchestrator`:

* `run_diagnostics(*, hierarchy_run_record_id, session)` -- run (or idempotently return the
  current version of) the sweep for one hierarchy run.
* `get_current_findings(session, hierarchy_run_record_id)` -- every finding of the *latest*
  run, or `[]` if the sweep has never been run. Read-only.
* `get_finding_evidence(session, finding_id)` -- one finding's own full evidence +
  affected-module ids.
* `review_finding(*, finding_id, session, review_note=None, reviewed_by=None)` -- the one
  mutable operation.

## Tests

`tests/persistence/test_cross_module_diagnostic.py` (7 tests): creation, idempotency by
fingerprint, new-fingerprint versioning, absent-run handling, the review-marking exception
(confirmed to touch only its own four columns), review-annotation reload, unknown-finding
rejection.

`tests/orchestration/test_cross_module_diagnostics_orchestrator.py` (16 tests): sibling
boundary mismatch; parent/child boundary mismatch; two compatible-case no-false-positive
scenarios (matching values, and distinct species); parameter conflict and its own
no-false-positive counterpart; incompatible units and a missing-unit-on-one-side case;
conflicting validation outcomes; an unresolved comparison correctly reported as `UNRESOLVED`
rather than silently skipped; full evidence traceability; idempotent rerun; a changed
boundary value producing a new version while the old one's findings are preserved; a review
annotation surviving a fresh-session reload; an unknown-hierarchy-run rejection -- plus **one
realistic integration test** (`test_real_diagnostics_smoke_detects_a_real_boundary_conflict`)
driving two real, independently executed module-level results (a real Agent2->Agent3->Agent4
calibration of one sibling module, a real Agent2->Agent3 simulation of the other) with a
deliberate, real boundary-value conflict on the one real, structurally-shared species (S3:
modA's own output fixed at 0, modB's own input fixed at 99) through the sibling harness
repository, then running the sweep purely in-process and confirming the detected finding's
own evidence traces back to the exact real `ModuleBoundaryPort` values that produced it.

Full Workbench suite passes with no regressions (280 pre-existing + 23 new = 303); the full
Harness suite and every Agent repository are unaffected (confirmed by `git status`); lint and
format clean.

## Remaining scientific limitations

* Unit comparison is a bare string-equality check -- there is no unit-algebra/conversion
  system, so `"mM"` vs `"mmol/L"` (the same physical unit, different spelling) would be
  flagged as incompatible even though it is not. This is a disclosed, conservative
  false-positive risk, never a silently-wrong conversion.
* Dataset-context comparison only checks whether the referenced `DatasetReference` ids
  differ -- it cannot inspect the datasets' own content for genuine experimental-condition
  compatibility (temperature, pH, strain, ...), since no structured condition model exists in
  this schema yet.
* Parameter-conflict detection only compares already-fitted `target_id` values -- it has no
  notion of two *different* parameter ids that happen to represent the same real physical
  quantity under different names.
* Related-pair scope is limited to direct siblings and direct parent/child -- a conflict
  between two modules that are cousins (siblings of siblings) is not detected, by design,
  since a shared boundary species between topologically distant modules is not scientifically
  meaningful to compare the same way.
* No automatic reconciliation, merging, or "resolved" value is ever produced -- by design
  (task instructions §4); a human must decide what, if anything, to do about a finding.
* No dynamic-coupling implementation, no GUI (both explicitly out of scope, unchanged).
