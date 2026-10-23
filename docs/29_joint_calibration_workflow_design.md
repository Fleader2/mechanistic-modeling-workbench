# 29. Joint Multi-Model/Multi-Dataset Calibration Workflow — Design Report

**This document is design only.** It changes no application behavior, no schema, no
migration, and no Figma file. Every capability claim gives a file:line reference so a reader
can re-verify it independently. Figma references are to file key `4tLH4HX0rdgPxjpNB1aJOW`
(the same file docs/15–19 already reference).

**Revision note.** This is a substantial revision of the first draft of this report. The first
draft proposed an "alternating fit" as an interim, labeled-approximate execution path for
multi-model calibration. On review, that proposal did not actually satisfy the scientific
contract a joint fit requires — in particular, it computed a hard parameter link once per
outer round and then held it `fixed=True`, which is not the same thing as a link that is
recomputed from its reference parameter's current value at every objective evaluation; and it
risked comparing multiple datasets against one simulated trajectory without verifying their
simulation inputs were actually interchangeable. This revision removes the alternating fit
entirely, replaces it with an explicit, precisely-stated execution contract, and treats true
multi-model joint execution as a capability that does not exist yet and is not designed here
in algorithmic detail — only scoped, so that whoever builds it knows exactly what it must
satisfy and what two architectural shapes are candidates for satisfying it.

**Second revision note.** This revision corrects a further architectural error: the prior
revision retained a module-vs-whole-model execution-scope selector inside this calibration
workflow, requiring the scientist to explicitly accept module-scoped execution even when
calibrating a single, undecomposed model. That selector does not belong here. This workflow
selects whole-model versions and their datasets; it never requires module selection, boundary
review, or decomposition. Recursive module-boundary refinement — proposing decompositions,
calibrating or evaluating candidate module configurations, comparing outcomes, and refining
boundaries — is a separate, distinct workflow, not designed in this report, though it may
reuse the same scientific services (Agent3/Agent4/the Harness) and the same immutable-snapshot
provenance pattern. Where whole-model execution does not yet exist as a backend capability,
that is treated strictly as a backend prerequisite to build (§6, §10) — never a reason to
substitute module-scoped execution in this workflow's place. Every section referencing the old
scope-selector has been rewritten accordingly.

## 0. What this document does and does not do

Designs: a three-screen UI workflow for calibrating **whole-model versions, never modules**,
against one or more datasets; a precise execution contract for what "joint" must mean; a
parameter-relationship taxonomy; and a phased roadmap in which every phase either ships
something real or is explicit about what it still cannot do. Does not design: the actual
multi-experiment optimization algorithm (that is Agent4's own, or a new service's own,
architecture decision — flagged, not specified); a parameter-relationship expression language
beyond one restricted affine primitive; any Figma change; or the separate, recursive
module-boundary-refinement workflow (propose decompositions, calibrate or evaluate candidate
module configurations, compare outcomes, refine boundaries) — a distinct workflow with its own
purpose, configuration, and navigation, which may reuse this report's scientific services and
provenance infrastructure but is not specified here (§6).

## 1. Capability-gap matrix (code-grounded)

Every row was confirmed by direct code inspection, not inferred from an earlier audit.

| # | Capability | Current state (file:line) | Gap |
|---|---|---|---|
| 1 | Calibrate one experimental evaluation against a model, end-to-end through the harness | **Only a module-scoped version exists today.** `request_module_calibration(*, model_module_id: UUID, ...)` (`app/orchestration/module_calibration_orchestrator.py:187`) validates a `calibration_request` dict against one module's own known components, captures an immutable `ModuleExecutionSnapshot` before invoking the harness (docs/09), persists a `RunRecord`. | **This workflow needs the whole-model-scoped sibling of this (row 14, §6) as its own, only execution primitive.** `module_calibration_orchestrator` informs that implementation — the immutable-snapshot discipline, the request-validation pattern — but is never itself called by this workflow. It remains the real execution primitive for the separate module-boundary-refinement workflow (§6), not designed here. |
| 2 | Excluding held-out evidence from a fit, within one calibration call | **Fully exists, previously missed.** `Observation.partition: ObservationPartition` (`agent4-calibration-estimator/app/agent4/types.py:34-43`, values `TRAIN`/`VALIDATION`) is assigned per observation; `run_agent4_pipeline` (`agent4-calibration-estimator/app/agent4/pipeline.py:160-165`) filters to `TRAIN` only for the objective, and reports `VALIDATION`-partition residuals separately as a diagnostic, never contributing to the fit. | None — reused directly (§5). This is finer-grained than, and complementary to, the Workbench's own existing calibration-vs-validation *dataset role* discipline (docs/11). |
| 3 | Declared per-observation error/weighting | **Fully exists.** `Observation.sigma` (`agent4-calibration-estimator/app/agent4/types.py:139-153`) drives weighted-least-squares weight `1/sigma**2`; omitted means unweighted. | None — this *is* the "declared error/weighting assumption" the execution contract (§5) requires; nothing new to build. |
| 4 | Multiple **compatible** experiments merged into one simulated trajectory | `agent4-calibration-estimator/app/agent4/simulation.py:26` simulates **one** `agent2_model` **once** per candidate parameter vector; `objective.py:68` sums every `Observation` in the set against that one simulated trajectory, with no per-observation initial-condition/intervention field anywhere in `Observation`/`ObservationSet` (confirmed: no such field exists in `types.py:139-153`). | **Narrow, not general.** Today's code already does the right thing *only* when every merged observation is actually comparable to one simulated trajectory. This report adds the compatibility check that makes that safe (§5) — the code needs no change for this narrow case, but using it without the check is a real correctness risk, not just an approximation. |
| 5 | A general multi-experiment joint-evaluation primitive (each experiment gets its own simulate call; shared/linked parameters are derived once per evaluation and threaded through every experiment) | **Does not exist at any layer.** No Agent4 code path simulates more than one `agent2_model`, or the same model under more than one input/intervention set, within one objective evaluation. The Harness's `WorkbenchModuleCalibrationRequest` (`agent-integration-harness/app/harness/workbench_contracts.py:1340-1398`) carries exactly one `module_id` and one `calibration_request` dict. | **Large — this is the one capability both "same model, genuinely different conditions" and "different models, shared parameters" are actually waiting on.** §5 states its exact required contract; §10 names two candidate architectural shapes and defers the choice, since neither exists and choosing between them is this report's own flagged open question, not a decision it makes unilaterally. |
| 6 | Non-time-series independent variables (dose, arbitrary condition), executable | `ObservationKind` is `TIME_SERIES \| STEADY_STATE` only (`agent4-calibration-estimator/app/agent4/types.py:27-31`); Agent3's only simulation entrypoint, `run_baseline_simulation` (`agent3-simulation-diagnostics/app/agent3/simulation.py:41`), has no field to override an initial/boundary value per call (confirmed by its own docstring, lines 49-53). The Workbench's workbook contract hardwires `TIME_COLUMN = "time"` (`app/time_series/contract.py:29`). | **Large.** The Workbench-side workbook extension (§4) is small and ships independently. Making it *executable* needs gap #5's own primitive plus a new Agent3 per-call boundary-override capability. |
| 7 | "Related models share structure," as an explicit, non-name-based fact | `Model.parent_model_id` (`app/models/model.py:70-72`) is a single-parent linear version chain, not a sibling/variant relationship. No code anywhere compares two `Model` rows' structure. | **Medium.** New, additive `model_relationship` table (§3). |
| 8 | Durable, queryable parameter facts | Parameter facts live only inside `ModuleExecutionSnapshot.snapshot_payload["parameters"]` JSON (`module_calibration_orchestrator.py:350-351`), never as rows. No `Parameter` table exists. | **Medium.** New `calibration_parameter_estimate` table (§3), populated from data Agent4 already produces. |
| 9 | Any calibration/validation/runs HTTP API | **Does not exist.** `app/api/v1/routes/` has only `health.py`/`projects.py`. | **Medium–large**, orchestration-only. |
| 10 | Background execution past the harness's synchronous 300s timeout | **Real, working precedent exists.** `app/orchestration/module_set_execution_orchestrator.py` + `scripts/module_set_simulation_worker.py` — a polling worker, fresh DB session per iteration. | None — reused directly once a job runs long enough to need it. |
| 11 | Immutable, pre-harness-call provenance snapshot | **Fully exists.** `ModuleExecutionSnapshot`, docs/09 — captured before the harness is invoked, `ON DELETE RESTRICT`, never mutated. | None — reused once per real executed experiment. |
| 12 | Checking two datasets aren't secretly the same/overlapping/incompatible evidence | A narrow precedent exists for one case: `module_validation_orchestrator.py`'s `_check_datasets_are_independent_of_calibration` (line 205), calibration-vs-validation dataset-id overlap on one module. | **Small–medium.** Generalized in §5/§6 into a compatibility+overlap check with four categories, two of them blocking. |
| 13 | Module-scoped execution | **Fully exists**, but only for a depth≥1, genuinely materialized `ModelModule` (`app/orchestration/model_module_orchestrator.py:57`; `app/persistence/model_module.py:22-46` excludes depth-0 "to preserve the existing root `Model`," by explicit docs/07 design requirement). | **Not used by this workflow at all.** This is the execution substrate for a separate, distinct workflow — recursive module-boundary refinement (propose decompositions, calibrate/evaluate candidate module configurations, compare outcomes, refine boundaries) — not designed in this report. This calibration workflow never selects, displays, or requires acceptance of a module (§6, §7). |
| 14 | Whole-model (non-decomposed) execution — **this workflow's own, only execution primitive** | **Does not exist as an orchestrator/contract**, but its one real prerequisite — a durable, independently re-verified Antimony artifact for the whole `Model`, captured *before* any hierarchical decomposition — **already exists and is reused by this report, not invented.** `capture_model_species_catalog` (`app/orchestration/model_species_catalog_orchestrator.py:71-99`) reads Agent2's own full-model-build output, durably saves the Antimony text (`save_model_antimony_text`), and re-verifies it loads via a real harness round-trip (`model_antimony_verification_harness_client.py:1-9`: *"Agent 2 is never invoked here, since the Workbench already has the Antimony text from its own prior full-model build"*) — entirely independent of `ModelModule`/`HierarchyNode`. | **Blocking — a hard prerequisite, not an optional enhancement.** Because this workflow has no module-scoped fallback (§6), **no job in this workflow, including a single-arm one, can execute until this ships.** Medium-sized and cleanly additive: a new `request_model_calibration(model_id=...)` orchestrator + a new, sibling Harness contract, reusing this already-durable artifact — never a change to `ModelModule`'s own, deliberate depth-0 exclusion, and never a reason to route this workflow's execution through `request_module_calibration` instead. |

## 2. Design principles, and which gap row each depends on

- *Calibration is not restricted to time-series or dose-series modes* → gap #6, gated on #5.
- *Each dataset may have multiple independent variables* → gap #6's Workbench-side half (§4) only, ships independently.
- *Related models share structure; matching names never establish identity* → gap #7.
- *Shared, fixed, model/experiment-specific, and explicitly linked parameters* → gaps #5 and #8; §5's relationship taxonomy makes "shared"/"linked" scientifically precise rather than a UI label.
- *Multiple datasets constrain a joint fit; confidence comes from diagnostics, never dataset count* → enforced throughout §5/§6: dataset or model *count* never appears anywhere in this design as a readiness or confidence signal on its own.

## 3. Proposed entities

Additive. `model_relationship` and the other durable records a job merely *references*
(`DatasetModelAliasMappingRevision`, `TimeSeriesDataset`) stay insert-only, the same precedent
this codebase already relies on — but `calibration_job` and its own children are **ordinarily
mutable while the job is `DRAFT`**, per §13's revision: the closest real precedent is
`ModuleSetDraft`/`ModuleSetDraftMember` (`app/models/module_set.py`), which edits and deletes
its own draft rows directly and guards concurrent edits with an `edit_version` optimistic-
concurrency token, not an insert-only/orphan-and-replace scheme. A `calibration_job`'s own
`edit_version` serves the identical role here.

| Table | Purpose | Key fields | Mutability |
|---|---|---|---|
| `model_relationship` | Declares two `Model` rows related as an explicit fact, never inferred from name. | `model_id_a`, `model_id_b`, `relationship_kind` (`VARIANT_OF` \| `SHARES_STRUCTURE_WITH`), `role_label_a`/`role_label_b`, `declared_by`, `declared_at` | Insert-only. |
| `calibration_job` | The envelope for one "Configure a run" submission with `analysis_type = CALIBRATION`. | `id`, `subproject_id`, `requested_by`, `status`, `created_at`, `completed_at` | Status transitions only; children insert-only. |
| `calibration_arm` | One participating model version's own slot — defines its *specific* parameter space. Always a whole-model version; this workflow never scopes an arm to a `ModelModule`. | `id`, `calibration_job_id`, `model_id` (FK `model`, the whole-model version the scientist picked), `role_label`, `sequence_index` | Insert-only. |
| `calibration_experiment` | **One experimental evaluation** — a dataset assigned to an arm, with its own scenario overrides and observation mapping. The atomic unit §5's contract operates on; several experiments on one arm *may* share a simulated trajectory, but only as an explicit, checked optimization (§5), never a default. | `id`, `calibration_arm_id`, `time_series_dataset_id`, `alias_mapping_revision_id`, `role` (`CALIBRATION` \| `HELD_OUT_VALIDATION`), `sequence_index` | Insert-only. |
| `calibration_experiment_scenario_override` | One boundary/initial-condition override for one experiment, sourced from its dataset's own condition legend or typed manually. Not executable until gap #5/#6 of §1 exist. | `id`, `calibration_experiment_id`, `target_kind` (`PARAMETER` \| `INITIAL_CONDITION`), `target_component_id`, `override_value`, `source` | Insert-only. |
| `calibration_parameter_role` | One parameter's relationship across the whole job (§5). `parameter_name` is **curator-declared, never catalog-validated** (§13, gap #15) until a parameter catalog exists. | `id`, `calibration_job_id`, `parameter_name`, `role` (`MODEL_SPECIFIC` \| `FIXED` \| `EXACT_EQUALITY` \| `EXACT_AFFINE_LINK` \| `SOFT_PRIOR_LINK`), `fixed_value`/`lower_bound`/`upper_bound`/`unit` (bounds apply to any free role, not only cross-arm ones — §7 Screen 2), `reference_arm_id`/`reference_parameter_name` (set only for the two link roles), `coefficient_a`, `coefficient_a_is_fixed`, `coefficient_b`, `coefficient_b_is_fixed` (set only for `EXACT_AFFINE_LINK`) | Mutable while the job is `DRAFT` (ordinary edit/delete, mirroring `ModuleSetDraftMember`'s own precedent, §13); the job's own `edit_version` is the optimistic-concurrency token. |
| `calibration_parameter_role_arm` | Which arms a role actually covers. | `calibration_parameter_role_id`, `calibration_arm_id` | Mutable with its own role, same discipline. |
| *(`calibration_compatibility_finding`)* | **Not a table, per §13's third change.** Every finding (`CALIBRATION_VALIDATION_DATASET_REUSE` \| `INCOMPATIBLE_EXPERIMENTS_MERGED` \| `DATASET_REUSED_ACROSS_DIFFERENT_MODELS` \| `PROVENANCE_TEXT_SIMILARITY_SUSPECTED` \| `PARAMETER_ROLE_CYCLE` \| `UNRESOLVED_LINK_REFERENCE` \| `AMBIGUOUS_SAME_NAME_PARAMETER`) is computed fresh, on demand, by the review endpoint alone, directly from the job's own live child rows — never stored, never at risk of going stale. | n/a | n/a |
| *(`calibration_parameter_estimate`)* | **Deferred, not built in this increment** (§10 Phase 2+) — there is no `agent4_report` to populate it from until a real execution exists; building it now would mean an empty table with no data path, never exercised. | n/a | n/a |

### Three persistence tiers, kept distinct

1. **Editable drafts.** `calibration_job.status = DRAFT` and every child row above: ordinarily
   mutable, guarded by the job's own `edit_version` (§13) — added, edited, and removed freely
   as the scientist works, per §7's "revalidation, never deletion" table for how an *upstream*
   change (a different model, a re-saved mapping) is handled without discarding unrelated
   choices. Nothing here is executed yet.
2. **Immutable saved revisions.** `model_relationship`, `DatasetModelAliasMappingRevision`,
   `TimeSeriesDataset` — each already durable and versioned *independently* of any job. A draft
   job merely *references* a specific revision/row; re-saving a mapping elsewhere creates a new
   revision the job can choose to re-pin to, never retroactively changing what the job already
   referenced (§6's invalidation table).
3. **Execution snapshots.** Created **only** at the moment a real execution is actually
   submitted — one whole-model execution snapshot (§6; a sibling of the `ModuleExecutionSnapshot`
   the separate module-boundary-refinement workflow uses, never a repurposing of it) per
   `calibration_experiment` that actually ran, capturing the exact resolved parameters,
   overrides, and request sent to the harness, before the harness is ever invoked (docs/09's
   discipline, unchanged). A draft can be edited and re-saved any number of times with **zero**
   snapshots; a snapshot exists if and only if a real harness call was actually made for that
   exact configuration. The two are never conflated: "saved" never means "executed," and
   "executed once" never prevents the draft from later being edited and re-run as a new,
   separate execution with its own new snapshot.

## 4. Two-tab workbook contract extension: multiple independent variables

Unchanged from the prior revision's design; restated briefly since the execution-side changes
above depend on it. **Preserves every existing import byte-for-byte** — `time`
(`app/time_series/contract.py:29`) keeps its exact current meaning, no declaration needed.

New, optional Metadata sub-table, following the existing marker-based pattern
(`MEASUREMENT_COLUMNS_SECTION_MARKER`, `contract.py:122`):

```
## Independent variable definitions
Column name (must match a Data tab column exactly) | Role | Unit | Description
dose                                                | DOSE | uM   | Drug concentration applied at t=0
```

New, additive column `TimeSeriesDatasetRow.independent_variables: Text` (JSON, mirroring
`measurements`' own shape), defaulted `"{}"`. An existing dataset re-read after this migration
is byte-identical to today. Independent-variable mapping is a second assignment table scoped
to the *same* `DatasetModelAliasMappingRevision` row — never a new revisioning mechanism, and
never merged across different `(dataset, model)` pairs; N models × M datasets still get up to
N×M fully independent mapping-revision chains, exactly as today.

## 5. The execution contract

This is the core of the revision. "Joint" is defined once, precisely, as a five-step contract
every executable configuration must satisfy — not as a label applied after the fact to
whatever the code happens to already do.

### The contract, stated exactly

One optimization vector `theta` contains every **shared** parameter (one entry, used by every
arm a role declares it for) and every **arm-specific** free parameter (one entry per arm).
For every evaluation of `theta` during fitting:

1. **Apply parameter-sharing/linking transformations.** For each arm, derive its own full
   parameter set from `theta`: a `MODEL_SPECIFIC` parameter is read directly from its own
   entry; a `FIXED` parameter is never in `theta` at all, always its declared constant; an
   `EXACT_EQUALITY` parameter is literally the one shared entry; an `EXACT_AFFINE_LINK`
   parameter is computed **fresh, from its reference parameter's current value in this exact
   evaluation of `theta`** — `target = a * reference + b`, with `a`/`b` read from `theta` if
   not fixed, or from their declared constants if fixed; a `SOFT_PRIOR_LINK` parameter is an
   ordinary free parameter with a prior pulling it toward the same computed value.
2. **Evaluate each model/experiment with its own initial conditions, inputs, interventions,
   and observation mapping.** Every `calibration_experiment` gets its own simulated
   trajectory, using its own arm's derived parameters from step 1 and its own scenario
   overrides/initial conditions (§3) — never another experiment's.
3. **Compute residuals using declared error/weighting assumptions.** Reuses Agent4's own real
   `Observation.sigma` mechanism (§1 row 3) — nothing new.
4. **Combine calibration residuals into one objective; exclude held-out evidence.** `J(theta)
   = sum over every CALIBRATION-role experiment's own residuals`. A `HELD_OUT_VALIDATION`
   -role experiment's observations are tagged `ObservationPartition.VALIDATION` (§1 row 2) and
   **never** enter this sum — Agent4 itself mechanically enforces this, not just Workbench
   discipline, reusing a real existing mechanism.
5. **Retain per-model/experiment/dataset diagnostics.** Every residual, identifiability
   finding, and correlation Agent4 already computes (§1; real, per
   `agent4-calibration-estimator/app/agent4/types.py:273-309`) is kept traceable to its own
   `calibration_experiment`/arm — never collapsed into one undifferentiated job-level number.

**This is the complete definition of "joint" for this design. Nothing is called a joint fit,
anywhere in this report, unless it satisfies all five steps for its own configuration.**

### What satisfies this contract today, and what does not

**Step 2 is where today's code falls short of full generality**, and exactly where this
revision corrects the first draft's overreach: Agent4 simulates **one** trajectory per
objective evaluation, used for every observation in its `ObservationSet` (§1 row 4) — there is
no way, today, to give two different `calibration_experiment`s their own distinct simulated
trajectories within one objective evaluation, whether they differ by model, by initial
condition, or by intervention. A genuinely general implementation of step 2 needs gap #5 (§1)
— a new primitive, not designed here.

**One narrow, real special case already satisfies the full contract without that primitive**:
when every `calibration_experiment` assigned to one arm is proven, by an explicit check, to be
*interchangeable* — same model, same resolved parameters (trivial, one arm), same initial
conditions/inputs/interventions, same observation-mapping target semantics — then "evaluate
each experiment with its own initial conditions" is vacuously satisfied by evaluating one
shared trajectory, because every experiment's own inputs are, by the check's own definition,
identical. **This is never assumed from "they share a condition label."** The compatibility
check below is what actually proves it, and nothing may merge two experiments into one
simulated trajectory without passing it.

### The compatibility check — what "may share a trajectory" actually requires

Before any two `calibration_experiment`s on the same arm are merged into one `ObservationSet`
comparison, **all** of the following must hold, computed from already-recorded facts, never
assumed:

| Factor | Compared via |
|---|---|
| Declared experimental condition | Both experiments' own `condition_id` (from each dataset's `condition_legend`) must be identical, or both genuinely absent. |
| Every declared independent-variable value | Every value in each experiment's own `independent_variables` (§4, e.g. `dose`) must match exactly — a `dose` column present with different recorded values on either side is an incompatibility even if `condition_id` happens to match or be absent on both. |
| Scenario overrides | Neither experiment may carry a `calibration_experiment_scenario_override` the other lacks or contradicts. |
| Observation-mapping semantics | For every measurement-column name both experiments' datasets share, their own alias-mapping revisions must assign it to the **same** `target_antimony_species_id` — two datasets both having a column literally named `"[X]"` mapped to *different* species on either side is an incompatibility, not a coincidence to ignore. |

Any mismatch is a blocking `INCOMPATIBLE_EXPERIMENTS_MERGED` `ERROR` finding
(`calibration_compatibility_finding`), naming the specific factor that disagreed. This is not
advisory — merging incompatible experiments would silently compare observations against the
wrong simulated condition, which no diagnostic downstream could catch after the fact.

### Parameter relationships

Three roles, kept visibly and semantically distinct — never presented as interchangeable:

- **`EXACT_EQUALITY`** — the parameter is literally one shared value. No coefficients. In the
  real joint-evaluation primitive (once it exists), this is simply one entry in `theta` read
  by every arm the role names.
- **`EXACT_AFFINE_LINK`** — `target = a * reference + b`. Both `a` and `b` are independently
  either a user-supplied fixed constant, or their own new free entry in `theta` (with its own
  bounds) estimated by the fit. Required at declaration time, never left implicit:
  - **Dimensional compatibility**: `reference`'s and `target`'s own declared/known units are
    checked with `app.units.compare_units` (already real, already used identically for
    species-unit checks in docs/27) — an affine link between dimensionally incompatible
    quantities is rejected at declaration time, not discovered after a fit.
  - **Bounds**: the computed `target` value is still subject to whatever bounds/eligibility
    rules would apply to it as an ordinary calibration target (`app.agent4.eligibility`,
    confirmed real) — a link can propose a value outside a declared bound, and that is a
    rejected declaration, not a silently clamped one.
  - **Cycle handling**: before "Complete review" can succeed, the full graph of
    `EXACT_EQUALITY`/`EXACT_AFFINE_LINK` edges across the whole job is checked for cycles (a
    simple graph-cycle detection over `(parameter_name, arm) → reference` edges); a cycle
    (A's parameter linked from B's, linked from A's) is a blocking `PARAMETER_ROLE_CYCLE`
    finding, never silently resolved by picking an arbitrary evaluation order.
  - **The defining correctness requirement, stated explicitly because the first draft of this
    report got it wrong**: a hard link (`EXACT_EQUALITY` or `EXACT_AFFINE_LINK`) must be
    recomputed from its reference parameter's *current* value at **every** objective
    evaluation of the *same* optimization run. Computing it once, then holding the result
    `fixed=True` for a subsequent, separate optimizer call — the first draft's "alternating
    fit" — does **not** satisfy this, no matter how many rounds it runs or how tight its
    convergence tolerance is. `fixed=True` proves a parameter won't move *within one call*; it
    proves nothing about whether the value it was fixed to is still correct relative to a
    reference that may have changed in a different call. **No execution path in this design
    may claim to implement `EXACT_EQUALITY`/`EXACT_AFFINE_LINK` unless it genuinely
    recomputes the link inside one shared evaluation, every time** — which is exactly what
    gap #5's still-unbuilt joint-evaluation primitive would need to do, and exactly why no
    interim substitute for it is proposed in this report (§10).
- **`SOFT_PRIOR_LINK`** — the computed target value becomes a `prior_value`/`prior_weight` on
  the target's own `CalibrationTarget` (`agent4-calibration-estimator/app/agent4/types.py:134-
  135`, real, already supported, no new Agent4 capability needed). The fit can move away from
  it; **the UI must never describe a soft-linked parameter's own fitted value using the same
  visual treatment as an exact relationship's** — it is disclosed guidance, not a constraint,
  and how far the fit actually moved from the linkage prediction is itself shown as a
  diagnostic, never hidden.

A genuinely **nonlinear** relationship (a Hill-type drug-effect curve) is out of scope for the
affine primitive. §11's modeling-choice note covers why a dose-response relationship is
usually better expressed as one model with `dose` as a genuine input (once gap #5/#6 make that
executable) than as a cross-model relationship at all.

### Readiness rule

"Run" enables only once every one of the following is true, computed server-side, pre-flight:

1. Every arm has ≥1 `calibration_experiment` with its mapping `ASSIGNED`/`SKIPPED` (never
   `UNRESOLVED`) for every column feeding a calibration target.
2. Every parameter appearing in ≥2 arms has an explicit role — no silent `MODEL_SPECIFIC`
   default once ≥2 arms exist.
3. At least one parameter, somewhere in the job, is actually free to fit.
4. The compatibility check has run. `WARNING`/`INFO` findings never block; `ERROR` findings
   (`CALIBRATION_VALIDATION_DATASET_REUSE`, `INCOMPATIBLE_EXPERIMENTS_MERGED`,
   `PARAMETER_ROLE_CYCLE`) do.
5. **An execution-capability check, separate from configuration completeness.** The job's own
   required execution shape is compared against what actually exists (§1): **every** arm
   requires whole-model execution (§6, row 14) — until that backend prerequisite ships, **no
   job in this workflow can execute, including a single-arm one**, and "Run" stays disabled
   with an explicit, named reason ("Whole-model execution is not yet available for
   calibration. This configuration is saved as a draft.") — never worked around by routing the
   request through the module-scoped contract instead. Once whole-model execution ships,
   exactly one arm with mutually-compatible experiments becomes executable immediately;
   anything additionally needing gap #5's joint-evaluation primitive (≥2 arms with a
   `SHARED`/linked parameter role, or any `INCOMPATIBLE_EXPERIMENTS_MERGED`-flagged pair the
   scientist wants to keep as genuinely separate conditions rather than split into separate
   jobs) stays blocked with its own named reason ("Joint execution across models is not
   available yet") until that further capability exists. A complete, internally-consistent
   configuration and an *executable* one remain two different, separately-checked things at
   every stage.
6. "Complete review" has been explicitly clicked.

**Confidence is never inferred from dataset or model count** — enforced by construction:
nothing in this design surfaces a bare "N datasets"/"N models" figure as a readiness or
confidence signal; every figure shown is a named diagnostic (an identifiability finding, a
residual, a compatibility finding) tied to a specific experiment or parameter.

## 6. Execution: whole-model only, and the backend prerequisite it requires

**This workflow selects whole-model versions and their datasets. It does not select, display,
or require acceptance of a module, and it never substitutes module-scoped execution for the
whole-model version the scientist actually picked — whether or not whole-model execution
exists yet as a backend capability.**

This corrects the prior revision, which retained a module-vs-whole-model scope selector and an
explicit per-arm "accept module-scoped execution" confirmation. That selector was itself the
mistake: it let module-scoped execution stand in for whole-model execution whenever exactly
one module happened to exist, and presented that substitution as if it were simply an honest
disclosure. A scientist who picks a `Model` is calibrating that model version — not a
decomposed part of it chosen on their behalf because it happened to be the only one available.
**If whole-model execution is not yet supported, that is a backend prerequisite to implement
— never a reason to substitute module execution.**

| | Reality today | What this workflow does |
|---|---|---|
| **Whole-model execution** (§1 row 14) | **Does not exist as an orchestrator/contract yet.** Its hard prerequisite — a durable, independently re-verified Antimony artifact for the *whole* model, captured before any decomposition — already exists and needs no new Agent2 wiring (`capture_model_species_catalog`, `model_antimony_verification_harness_client.py`). | Every `calibration_arm` resolves to this, and only this. Until the backend extension below ships, a job can be fully configured and reach "Complete review," but **"Run" stays disabled for every job, including a single-arm one**, with an explicit, named reason: *"Whole-model execution is not yet available for calibration. This configuration is saved as a draft and can be run once that capability exists."* This is a backend prerequisite to build (below) — never a reason to fall back to module-scoped execution. |
| **Module-scoped execution** (§1 row 13) | Real, for a depth≥1, materialized `ModelModule` (`model_module_orchestrator.py:57`). The root/whole model is excluded on purpose from ever being one (`app/persistence/model_module.py:22-46`, docs/07's own explicit requirement). | **Not part of this workflow.** It is the execution substrate for a separate, distinct workflow — recursive module-boundary refinement: propose decompositions, calibrate or evaluate candidate module configurations, compare outcomes, refine boundaries. That workflow is not designed in this report. The two workflows may reuse the same scientific services (Agent3, Agent4, the Harness) and the same immutable-snapshot provenance pattern, while remaining distinct in purpose, configuration, and navigation — a scientist calibrating a whole model is never routed into module selection, and a scientist refining module boundaries is never routed into this workflow's screens. |

### The backend extension for whole-model execution

Documented, not built: a new orchestration function `request_model_calibration(*, model_id:
UUID, calibration_request: dict, ...)`, sibling to (never a modification of)
`request_module_calibration`, that:

1. Resolves `model_id`'s own durable `ModelSpeciesCatalog.source_antimony_artifact_reference`
   (already captured at build time, §1 row 14) as the executable content — never Agent2's
   transient run-output path, and never a `ModelModule`'s `attach_payload`.
2. Builds a new, sibling Harness contract, `WorkbenchModelCalibrationRequest` — a new
   dataclass, a new contract-version string, a new canonical script, following the Harness's
   own established precedent for every prior contract-shape change (confirmed as this
   project's standing practice: a new dataclass + new contract-version string + new canonical
   script, the old one left untouched).
3. Captures an immutable snapshot keyed to `model_id` (a sibling of `ModuleExecutionSnapshot`,
   not a repurposing of it, since the identity being snapshotted — a whole model, not a
   module — is genuinely different).

This is additive at every layer: `ModelModule`'s own depth-0 exclusion is never touched,
`request_module_calibration` is never modified, and no existing module calibration (real or
future, for the separate boundary-refinement workflow) is affected by this extension existing
or not.

### Generalizing to a joint job

Each `calibration_arm` resolves to `request_model_calibration` against its own `model_id` — a
joint job with two related models is simply two arms, each independently whole-model-scoped,
never a per-arm scope decision and never a module lookup.

## 7. UI screen sequence and rationale

**Rewritten in this revision** against a concrete, now-implemented increment (docs/30). Still
three screens, with ordered sections and progressive disclosure within each — reusing Figma's
existing "Runs & Results" screens where their shape still fits, diverging where the revised
architecture (§5, §6, §13) requires a section Figma's own mock never anticipated (no Figma
edit is made anywhere in this report; every divergence below is implemented directly in code):

| Screen | Maps to Figma node | Sections, in order |
|---|---|---|
| **1. Models & experimental data** | `48:1033` | (a) select one or more whole-model versions, each becoming one `calibration_arm` (§6 — never a module picker); (b) add datasets and assign experiments to models — an unambiguous dataset is **pre-selected, shown, and editable**, never blank by default and never hidden; (c) designate each experiment `CALIBRATION` vs. `HELD_OUT_VALIDATION`; (d) a model-relationship section, rendered **only once ≥2 arms' models actually have, or could have, a declared `model_relationship`** (§3) — structurally absent for one arm, not collapsed. |
| **2. Variables, parameters & experimental settings** | Extends `AliasMappingScreen` (docs/27) + new sections | An experiment selector (for ≥2 experiments) scopes everything below to one experiment at a time, so the simple case never shows a multi-experiment control surface. Per experiment: (a) map independent variables — `time` always, `condition_id` when the dataset's own condition legend is non-empty, with `dose`/arbitrary declared variables shown as **honestly unavailable** pending the §4 workbook extension, never silently skipped with no explanation; (b) map dependent measurements to supported outputs, reusing the existing species alias-mapping table unmodified; (c) specify initial-condition/intervention scenario overrides (§3); (d) declare this experiment's objective weighting/error assumption (an explicit, named policy choice — §3 — never inferred). Per job, **always shown, even for one arm**: a parameter-role section listing every parameter the scientist chooses to declare, each with an explicit free/fixed role and bounds (§5) — curator-declared, explicitly disclosed as not yet validated against an authoritative parameter catalog (§13, gap #15) — with the cross-arm sharing/linking roles (`EXACT_EQUALITY`/`EXACT_AFFINE_LINK`/`SOFT_PRIOR_LINK`) appearing **only once ≥2 arms exist**. |
| **3. Review & readiness** | `82:671` | Per-arm cards (model version, experiments, variable mappings, parameter roles, scenario overrides, objective settings) — a summary only, **no new required input**, with every actionable finding linking back to the exact input that produced it. A distinct configuration-completeness check and a distinct execution-capability check (§5 rule 5), never conflated: a single model, fully and correctly configured, is reported complete but **still not execution-ready** until whole-model execution (§6) ships — the readiness card states this explicitly, by name, every time. |

Results reuse "Calibration results" (`48:1246`) per arm, plus a joint summary where
applicable — unreachable in this increment, since nothing in it executes (§13).

### Back / Next / Save Draft

- **Next** validates only the current screen's own structural completeness (e.g., Screen 1
  requires every arm to have ≥1 experiment before Screen 2 is reachable) — never the full
  readiness rule, which only Screen 3 ever evaluates.
- **Back** never discards anything already entered on a later screen; a later screen's own
  state is preserved in the draft and simply re-shown if the scientist returns to it.
- **Save Draft** is available from every screen, persists the job's current `calibration_job`
  row and every child row exactly as entered (no implicit validation gate), and is the same
  action "leaving mid-flow" and "finishing a session to resume tomorrow" both use — a draft is
  never lost for being incomplete.

### Is the three-screen flow still simple for one model, one dataset?

Audited directly against the revised, now-implemented architecture: **yes.**

1. **Dataset/experiment assignment remains explicit** (reaffirmed): an unambiguous
   pre-selection is shown and editable, never blank, never hidden behind the default.
2. **The parameter-role section is now always present, even for one arm** — this is a
   deliberate, net-new requirement of this revision (a scientist calibrating even a single
   model must still say which parameters are free, which are fixed, and within what bounds);
   it was not a true addition to the simple case's *cognitive* load, since some such choice was
   always scientifically necessary to calibrate anything meaningfully — this revision simply
   stops deferring it to "only once it's complicated."
3. **Model relationships, cross-arm parameter-sharing/linking roles, and the
   compatibility/execution-capability cards remain structurally absent for one arm** — not
   collapsed, not rendered empty.
4. **Screen 3 renders exactly as `82:671` does today** for one arm, with no module-scope
   confirmation anywhere (§6) and no multi-experiment selector forced on a single-experiment
   job.

**Net assessment:** the simple case is one explicit, bounded addition (per-arm parameter roles)
beyond the original Figma design, and loses nothing. There is no module-scope step, no module
browser, and no multi-model control surface anywhere in the one-model/one-dataset path.

### Preserving prior work: revalidation, never deletion

Every upstream change that could affect an already-made choice **marks that choice for
revalidation and leaves it in place** — it is never silently deleted, and an unrelated choice
elsewhere in the same job is never touched at all:

| Upstream change | What's marked for revalidation | Mechanism |
|---|---|---|
| A different model version is picked for an existing arm | That arm's own experiments, variable mappings, and any parameter-role row naming a parameter the new model has no record of | The arm's `model_id` is updated in place (never a new row); every one of its experiments' alias-mapping pin is re-checked against the new `(dataset, model)` pair and flagged `UNMAPPED_FOR_NEW_MODEL` if no revision exists yet — the experiment row itself, and every other arm's own rows, are untouched. |
| A dataset's alias mapping is re-saved (new `DatasetModelAliasMappingRevision`) while the job is a draft | Nothing is force-invalidated — the pinned old revision number keeps working (it's immutable) | **Computed at read time, never stored**: every experiment response compares its own pinned `alias_mapping_revision_id` against the dataset/model pair's current revision and sets `mapping_is_stale: true` if they differ, reusing docs/27's own `expected_revision_number` discipline. Screen 2 shows a "mapping has changed since you assigned this — review?" banner; the scientist explicitly chooses whether to re-pin. |
| A parameter-role is removed that another role's `EXACT_AFFINE_LINK`/`EXACT_EQUALITY` referenced | The dependent link role becomes unresolved | An `UNRESOLVED_LINK_REFERENCE` finding (§13) blocks "Complete review" until either the reference is restored or the dependent link role is also removed — never silently defaulted to some other parameter. |
| Review is completed, then the job is edited again | Nothing — `calibration_job.status` drops back to `DRAFT` on the next edit; a later "Complete review" re-runs every rule in §5/§13 fresh | Matches the existing Figma copy ("changing the model, analysis, evidence or settings requires a new review," node `48:1135`) exactly, scoped to the whole job. |

## 8. Walkthroughs

### A. One model, one dataset

Screen 1: pick a model version → pick Calibration → the one already-mapped dataset is
pre-selected, shown, editable. No module is shown, selected, or accepted anywhere. Screen 2 is
skipped (already mapped). Screen 3: unchanged from today's `82:671`, one arm, nothing to check
beyond the vacuously-satisfied rules. **Run calls `request_model_calibration` (§6) — once that
capability exists (Phase 1, §10).** Until then, "Run" stays disabled with the named reason
from §6, and the job remains a fully-configured, reviewable draft. Results, once executable,
render as `48:1246` does today.

### B. One model, multiple compatible datasets (a real joint fit, today, under the compatibility check)

Screen 1: one arm, two datasets added as two `calibration_experiment`s — e.g. two
independently-collected wild-type time-courses under the *identical* declared condition, with
no `independent_variables`/scenario-override disagreement between them, and both datasets'
own alias mappings agreeing on every shared measurement-column's target species. The
compatibility check (§5) passes with no finding. Screen 3's compatibility card shows "no
incompatibility found" explicitly, not silently nothing. Run merges both experiments'
observations into one `ObservationSet` and calls `request_model_calibration` once (§6 —
available once Phase 1 ships) — satisfying all five steps of §5's contract because step 2 is
vacuously true (every merged experiment's own inputs are, by the check, identical). Results: a
per-experiment residual breakdown from the Workbench's own provenance bookkeeping.

**If instead the two datasets had recorded different conditions or different dose values**,
the compatibility check raises a blocking `INCOMPATIBLE_EXPERIMENTS_MERGED` finding and Review
cannot complete for that pairing — the scientist must either split them into separate arms
(giving up a joint fit for that pair, since gap #5's primitive doesn't exist) or wait for that
capability.

### C. Related no-drug/drug models — now a design-time case, not yet an execution-time one

1. A curator has already declared `model_relationship(model_id_a=<no-drug>, model_id_b=
   <drug-treated>, relationship_kind=VARIANT_OF, role_label_a="no_drug",
   role_label_b="drug_treated")`.
2. Screen 1: user adds both model versions as two arms, each with its own dataset assignment
   and mapping — no module selection or acceptance step for either. Parameter configuration
   appears. Most
   parameters default to no entry (`MODEL_SPECIFIC` must be chosen explicitly). A housekeeping
   `kcat` gets `EXACT_EQUALITY`. `Vmax_ACC1`'s drug-treated value gets `EXACT_AFFINE_LINK`
   (coefficient `a` estimated, `b` fixed at `0`), with `app.units.compare_units` confirming
   `Vmax_ACC1`'s own unit is identical on both sides (so `a` is a dimensionless scale factor,
   not a nonsensical cross-unit ratio) — this declaration is rejected at entry time if the
   units didn't match.
3. Screen 3: two Model/Evidence/Settings cards, a Parameter-roles card, a Compatibility card
   — and the execution-capability check (§5 rule 5) reports, plainly: **"Joint execution
   across 2 models is not available yet. This configuration is saved as a draft and can be
   run once joint multi-model execution capability exists."** "Complete review" still
   succeeds (the configuration itself is complete and internally consistent — no cycle, no
   unit mismatch, no missing role) but **"Run" stays disabled**, with that same message
   shown directly next to it, not buried in a separate log.
4. **Nothing executes.** The job remains a fully-specified, durably-saved draft — every
   entity in §3 exists and is reviewable, shareable, and resumable — until gap #5's primitive
   is actually built (§10). This report does not offer an interim approximation in its place;
   §10 explains why.

## 9. API examples

```http
POST /api/v1/subprojects/{subproject_id}/calibration-jobs
{ "requested_by": "scientist@local" }
→ 201 { "id": "job-...", "status": "DRAFT", "arms": [] }

POST /api/v1/calibration-jobs/{job_id}/arms
{ "model_id": "model-no-drug-..." }
→ 201 { "id": "arm-a-...", "model_id": "model-no-drug-..." }

POST /api/v1/calibration-jobs/{job_id}/arms/{arm_id}/experiments
{ "time_series_dataset_id": "tsd-...", "role": "CALIBRATION" }
→ 201 { "id": "experiment-...", "alias_mapping_revision_id": null }

POST /api/v1/calibration-jobs/{job_id}/parameter-roles
{
  "parameter_name": "Vmax_ACC1",
  "role": "EXACT_AFFINE_LINK",
  "reference_arm_id": "arm-a-...",
  "reference_parameter_name": "Vmax_ACC1",
  "coefficient_a_is_fixed": false,
  "coefficient_b": 0.0,
  "coefficient_b_is_fixed": true,
  "arm_ids": ["arm-b-..."]
}
→ 201 { "id": "role-...", "role": "EXACT_AFFINE_LINK" }

POST /api/v1/calibration-jobs/{job_id}/review
→ 200 {
  "status": "COMPLETE_BUT_NOT_EXECUTABLE",
  "compatibility_findings": [],
  "execution_capability": {
    "available": false,
    "reason": "Joint execution across 2 models is not available yet.",
    "missing_capability": "MULTI_MODEL_JOINT_EVALUATION"
  }
}
```

The same `execution_capability` block appears for a single-arm job before Phase 1 (§10) ships
— only the `missing_capability` differs, and the reason never mentions a module:

```http
POST /api/v1/calibration-jobs/{job_id}/review
→ 200 {
  "status": "COMPLETE_BUT_NOT_EXECUTABLE",
  "compatibility_findings": [],
  "execution_capability": {
    "available": false,
    "reason": "Whole-model execution is not yet available for calibration.",
    "missing_capability": "WHOLE_MODEL_EXECUTION"
  }
}
```

Only a single-arm job after Phase 1 ships, or a multi-experiment arm that additionally passes
the compatibility check, ever returns `"execution_capability": { "available": true }` and can
call `POST /calibration-jobs/{job_id}/run`.

## 10. Roadmap

**The alternating fit is removed as a default or interim execution path.** It is not offered
anywhere in this roadmap, including as a labeled approximation. Any future approximation to
true joint optimization is **not decided by this report** — it would need its own, separately
justified scientific proposal (addressing, at minimum, convergence guarantees relative to a
true joint optimum and a quantified, not just disclosed, uncertainty correction), reviewed on
its own terms, not shipped because a confidence-interval warning label seemed sufficient. A
bare warning is not that proposal.

| Phase | Delivers | Blocked / unavailable | Required repository changes | Acceptance evidence |
|---|---|---|---|---|
| **0 — Foundations (implemented — docs/30)** | The three-screen UI and `calibration_job`/`calibration_arm`/`calibration_experiment`/`calibration_experiment_scenario_override`/`calibration_parameter_role(_arm)`/`model_relationship` entities, always whole-model-scoped (never module-scoped), **no arm-count cap** (multi-arm configuration, including Walkthrough C, is fully buildable as a draft now — only execution is phase-gated, not configuration shape). Jobs can be fully configured, mapped, reviewed, saved, reopened, and re-edited — all of §3's "editable draft" tier, real over HTTP. | **Execution of any kind.** "Run" stays disabled for every job in this phase — including a single-arm one — because whole-model execution (Phase 1) does not exist yet. This is a deliberate, named block, never a silent fallback to module-scoped execution. | New, thin API routes for job/arm/experiment/parameter-role/scenario-override creation, mapping, and review only (no working `run` endpoint); the full table set above. | A fully-configured single-arm job reaches `"status": "COMPLETE_BUT_NOT_EXECUTABLE"` with `execution_capability.reason` naming the whole-model-execution prerequisite; an automated test asserts `POST .../run` is rejected for every job in this phase and that `module_calibration_orchestrator` is never invoked anywhere in the request path. See docs/30 for the actual acceptance evidence gathered. |
| **1 — Whole-model execution** | `request_model_calibration` (§6) — the one and only execution orchestrator this workflow ever calls. A single-arm job becomes genuinely executable for the first time, reusing the model's already-durable `ModelSpeciesCatalog` artifact. | Multi-arm/multi-model anything. | New orchestrator, new sibling Harness contract (`WorkbenchModelCalibrationRequest`), new model-scoped snapshot table; the async-worker pattern (gap #10, §1) adopted if a real run exceeds the harness's synchronous timeout. | A model with zero `ModelModule`s (confirmed via `model_module` row count = 0) is calibrated successfully end-to-end through `request_model_calibration`, with `request_module_calibration` never invoked for it at any point — confirmed by an automated test, not just the happy-path trace. |
| **2 — Compatible multi-experiment fits, one arm** | Walkthrough B — real joint fits across multiple datasets of **one** model, gated by the compatibility check (§5); the independent-variable workbook extension (§4) becomes usable for *declaring and mapping* dose/condition data, though not yet for driving it into execution. | Any arm count ≥2. Any pair of experiments the compatibility check flags `INCOMPATIBLE_EXPERIMENTS_MERGED` — correctly refused, not approximated. | `calibration_experiment` (plural per arm), the compatibility-check function, per-experiment residual bookkeeping. | Two independently-collected, same-condition replicate datasets, calibrated jointly, produce one whole-model execution snapshot (§6)/report whose residuals the Workbench can re-split per originating dataset; a deliberately mismatched-condition pair is rejected at Review with a named finding, confirmed by an automated test asserting the block, not just the happy path. |
| **3 — Multi-model configuration, draft-only** | Walkthrough C up to "Complete review" — `model_relationship`, the full parameter-role taxonomy (§5) with unit/bounds/cycle checking, the Parameter-configuration and Model-relationships UI, `calibration_parameter_estimate`. **"Run" is never enabled for ≥2 arms in this phase.** | Execution of any ≥2-arm job — by design, not by omission. | `model_relationship`, `calibration_parameter_role(_arm)`, the execution-capability check (§5 rule 5) returning `available: false` for every multi-arm configuration, the cycle/unit/bounds validators. | A fully-specified two-model job with every role declared, every unit check passed, zero cycles, reaches `"status": "COMPLETE_BUT_NOT_EXECUTABLE"` and can be saved, reopened, and re-edited indefinitely without ever being run; an automated test asserts `POST .../run` is rejected for it. |
| **4 — Real joint multi-experiment execution** | Gap #5's primitive, finally built as **Option (A)** (§13): Agent4 grows multi-arm/multi-experiment input support — receives N (model, experiment, scenario-override) tuples plus the parameter-role declarations, and runs its own internal optimizer over the combined vector, calling its own reusable, independently-testable per-experiment evaluate function once per experiment per candidate evaluation. Makes Phase 3's saved drafts executable, and (combined with Phase 4a below) makes genuine dose/condition scenarios (gap #6) executable too. The backend roadmap this phase actually follows, in order: **(4a)** confirm/extend the authoritative whole-model artifacts this depends on (`ModelSpeciesCatalog`, gap #15's proposed parameter catalog); **(4b)** Agent3 grows one-scenario-per-call evaluation (gap #6); **(4c)** Agent4 grows the internal multi-experiment optimizer described above; **(4d)** a new joint Harness contract and Workbench orchestrator wire the three together, mirroring every prior contract-shape change's own established precedent (§1 row 5). | Any relationship type beyond the affine primitive (§5's own stated limitation, unresolved by this phase). | Cross-repo: new Agent4 capability (4c), a new joint Harness contract (4d), new Agent3 per-scenario evaluation support (4b), the parameter catalog of gap #15 (4a) if parameter-targeted scenarios/roles are to be validated rather than merely disclosed as unvalidated. | A `SHARED`/`EXACT_AFFINE_LINK` parameter's value, inspected at the optimizer's own internal evaluation trace, is shown to be recomputed from its reference's current value at every evaluation within the run — not merely at the end of each of several separate calls — closing exactly the gap the first draft of this report got wrong. |

## 11. Acceptance scenarios

- **Simple path.** Given one arm, one dataset, fully mapped, **when** reviewed, **then** no
  relationship, cycle, or compatibility check ever blocks it (all vacuously satisfied).
  **Before** whole-model execution (§6, Phase 1) ships, the execution-capability check still
  blocks "Run" with the named reason "Whole-model execution is not yet available for
  calibration" — the job is saved as a complete, reviewable draft. **Once** Phase 1 ships, it
  runs via `request_model_calibration`, never via `request_module_calibration` regardless of
  how many modules the model happens to have.
- **Shared parameters across different conditions/models.** Given two arms with a parameter
  declared `EXACT_EQUALITY`, **when** the job is reviewed before Phase 4 ships, **then** it
  reaches `COMPLETE_BUT_NOT_EXECUTABLE` and is saved as a draft, never silently run via any
  interim substitute. **When** Phase 4's real primitive exists, **then** both arms' derived
  value for that parameter is identical at every single evaluation of the fit, not merely at
  convergence.
- **Hard-link enforcement at every evaluation.** Given an `EXACT_AFFINE_LINK` role with a
  non-fixed coefficient, **when** any execution path is proposed to satisfy it, **then** it is
  rejected as non-conforming unless it can show the link is recomputed from the reference
  parameter's current value inside the *same* objective evaluation — a multi-call scheme that
  fixes the computed value between calls does not qualify, regardless of its own convergence
  behavior.
- **Held-out exclusion.** Given an experiment with `role = HELD_OUT_VALIDATION`, **when** its
  arm's calibration request is built, **then** its observations are tagged
  `ObservationPartition.VALIDATION` and are mechanically excluded from the fitted objective by
  Agent4 itself, while their own residual is still reported as a diagnostic.
- **Incompatible trajectory reuse.** Given two experiments on one arm whose declared
  condition, independent-variable values, scenario overrides, or observation-mapping target
  species disagree in any one respect, **when** the compatibility check runs, **then** they
  are never merged into one simulated trajectory, and review is blocked with a finding naming
  the specific disagreeing factor.
- **No module substitution.** Given a model with one or more calibratable modules, **when**
  the scientist adds it as a calibration arm, **then** the workflow never shows, selects, or
  requires acceptance of any module — the arm always resolves to `request_model_calibration`
  against the model itself (§6). If whole-model execution does not yet exist, "Run" stays
  disabled with a reason naming that backend prerequisite; it never silently falls back to
  module-scoped execution, however unambiguous the module choice would have been.

## 12. Revised decisions and remaining questions for review

**Resolved by this revision:**

1. The alternating fit is removed; no interim approximation for multi-model joint execution
   exists anywhere in this design. Multi-model configurations are fully designable and
   saveable, never executable, until a real capability (Phase 4) exists.
2. Parameter relationships are now three distinct, separately-labeled roles
   (`EXACT_EQUALITY`/`EXACT_AFFINE_LINK`/`SOFT_PRIOR_LINK`), with unit, bounds, and cycle
   checking specified, and a precise, falsifiable definition of what "recomputed at every
   evaluation" requires — closing the `fixed=True` ambiguity directly.
3. **Module-vs-whole-model execution scope is removed as a concept from this workflow.** This
   workflow selects whole-model versions only; module-scoped execution belongs to a separate,
   undesigned module-boundary-refinement workflow (§6). Where whole-model execution does not
   yet exist, that is a named backend prerequisite (§1 row 14, §10 Phase 1) — never a reason to
   substitute module-scoped execution, and never requiring any scope-acceptance step from the
   scientist. The whole-model backend extension remains documented and grounded in the same
   already-existing durable-artifact precedent (`ModelSpeciesCatalog`), not invented from
   nothing.
4. The "same-condition datasets may share a trajectory" claim is now gated by an explicit,
   four-factor compatibility check, not asserted from a condition-label match alone.

**Resolved by the third (§13) revision:**

5. **Phase 4's architecture choice is Option (A)**, Agent4-internal multi-arm optimization —
   no longer open. See §13.
6. **The whole-model parameter catalog gap (§1 row 15)** is disclosed and given a concrete,
   precedent-grounded proposed resolution rather than left as a bare gap.

**Open, for review — this report does not decide these:**

1. **A nonlinear parameter-relationship language** remains explicitly out of scope; whether
   it's ever needed depends on whether Phase 4's dose-as-model-input path (the better fit for
   genuinely nonlinear dose-response relationships, per §5) turns out to cover the real
   science, or whether a true cross-model nonlinear link is still wanted afterward.
3. **Execution-capability messaging ownership** — whether "Joint execution is not available
   yet" should link to a roadmap/status page, a feature-flag explanation, or simply the plain
   text shown in this report's own API example, is a product-copy decision, not addressed
   further here.
4. **Evidence-overlap text-similarity checking** remains heuristic and advisory by
   construction (it can both miss and over-flag); whether a stronger mechanism (e.g.
   checksum-level duplicate-upload detection, which `TimeSeriesDataset` does not currently
   retain) is worth building is a data-provenance decision for this project's own owner.
5. **The module-boundary-refinement workflow itself** — propose decompositions, calibrate or
   evaluate candidate module configurations, compare outcomes, refine boundaries — is real as
   an execution substrate (§1 row 13) but has no UI/entity design of its own in this report.
   Whether and when it needs the same design-report treatment this document gives whole-model
   calibration is a scoping decision for this project's own owner, not decided here.

## 13. Third revision: the configuration-only increment (implemented — see docs/30)

This revision resolves the two items §12 had left open for review, and rewrites §7's screen
spec against a concrete, now-implemented configuration-only increment (see
`docs/30_joint_calibration_configuration_increment.md` for exactly what shipped, what was
verified live, and what remains a disclosed limitation). Three changes:

1. **Phase 4's architecture choice is resolved: Option (A).** Agent4 itself grows multi-arm/
   multi-experiment input support and owns its own internal optimizer, calling a reusable,
   independently testable per-experiment evaluation function once per experiment per candidate
   vector — generalizing the exact role `evaluate_vector`/`evaluate_candidate`
   (`agent4-calibration-estimator/app/agent4/objective.py`/`simulation.py`) already play for one
   model today. No new "evaluate-only" primitive or externally-owned outer optimizer is
   introduced; the fitting boundary stays inside Agent4, exactly where it already is. This
   closes §12's first open item. Responsibility split, restated precisely:
   - **Workbench** — owns configuration, provenance, review, job lifecycle, and results
     presentation. Never computes a residual, runs a simulation, or runs an optimizer.
   - **Harness** — owns validated transport and orchestration of the request/response round
     trip, per its own established contract-versioning precedent (§1 row 5) — a new, joint
     contract shape, never a mutation of `WorkbenchModuleCalibrationRequest`.
   - **Agent3** — evaluates one whole-model experimental scenario (its own initial conditions/
     interventions/boundary overrides) per call — the real capability gap #6 (§1) still needs
     built, now scoped precisely as "one scenario per call," not "one override field bolted
     onto the existing baseline-only entrypoint."
   - **Agent4** — owns the shared optimization vector, every parameter-sharing/linking
     transformation (§5), residual construction per experiment, the one combined objective
     (held-out evidence excluded per §5 step 4), the optimization run itself, and every
     uncertainty/identifiability diagnostic — all **inside** Agent4, never split across a
     Workbench-side or Harness-side loop.
2. **A new, previously-unidentified capability gap, found during the configuration increment's
   own implementation**: this design's `calibration_parameter_role.parameter_name` (§3) names a
   model parameter with no durable, authoritative catalog to validate it against — confirmed by
   inspection: `ModelSpeciesCatalog` (§1 row 14) captures *species and compartments only*, not
   parameters; no `ModelParameterCatalog` or equivalent exists anywhere in this codebase
   (confirmed by grep, zero hits for any such table/model). §1 gains row 15 below; the
   configuration increment resolves it honestly (free-text, explicitly disclosed as
   catalog-unvalidated), never by inferring a parameter list from the species catalog or
   fabricating one.
3. **`calibration_compatibility_finding` is no longer a persisted table.** Re-examined against
   its own stated discipline ("recomputed fresh at every review," §3) — a table that is always
   fully recomputed and never incrementally read has no correctness reason to be durable rows at
   all, and a durable copy only risks silently going stale between recomputations. The
   configuration increment computes every finding on demand, in the review response, from the
   job's own live child rows — identical semantics, one fewer table, zero risk of a stored
   finding outliving the state that produced it.

| # | Capability | Current state (file:line) | Gap |
|---|---|---|---|
| 15 | Authoritative, durable whole-model parameter catalog | **Does not exist.** `ModelSpeciesCatalog` (`app/models/model_species_catalog.py`) captures only `ModelSpecies`/`ModelCompartment` rows, confirmed by direct inspection — no parameter-id/unit/default-value table exists anywhere in this schema or any sibling repository's own durable storage (confirmed by grep across `app/models/`). A calibration target or scenario override naming a *parameter* (as opposed to a species' initial condition, which `ModelSpeciesCatalog` already covers) has nothing authoritative to validate against today. | **Medium, additive, and precisely scoped by precedent.** Proposed resolution: a new `ModelParameterCatalog`/`ModelParameter` table pair, captured at the identical build-time moment and via the identical mechanism as `ModelSpeciesCatalog` (`capture_model_species_catalog`, `app/orchestration/model_species_catalog_orchestrator.py:71-99`) — Agent 2's own structural network already carries parameter ids/values; the missing step is the same real-Antimony-load verification `ModelSpeciesCatalog` already performs for species, applied to parameters. Until this exists, every `parameter_name` a scientist enters in this workflow is **curator-declared, explicitly disclosed as not yet catalog-validated** — never silently treated as verified, and never inferred from `ModelSpeciesCatalog.species` (a structurally different kind of model entity). **Resolved — see §14 below and `docs/31_joint_calibration_configuration_prerequisites_increment.md`.** |

## 14. Fourth revision: the configuration-prerequisites increment (implemented — see docs/31)

This revision closes gap row 15 above and the two other configuration gaps docs/30 §6 left
disclosed (dose/arbitrary independent variables not capturable; the `INCOMPATIBLE_EXPERIMENTS_
MERGED` finding blocking saving rather than only execution) — see
`docs/31_joint_calibration_configuration_prerequisites_increment.md` for exactly what shipped,
the harness-side mechanism used to distinguish an independent from a derived (assignment-rule)
parameter, and what was verified live against a real compiled model. Three changes:

1. **Gap row 15 is resolved as proposed**, not substituted with an approximation: a new
   `ModelParameterCatalog`/`ModelParameter` table pair, captured at the identical build-time
   moment and via the identical mechanism as `ModelSpeciesCatalog`, with every
   `calibration_parameter_role.parameter_name` and independent-variable-binding
   `target_component_id` now validated server-side against it where one is `AVAILABLE` and
   relevant — `catalog_validated` is a real, honestly-computed field, never a hardcoded
   `Literal[False]`.
2. **The §4 workbook-contract extension (independent variable definitions) now ships**, as a
   dataset-import-scope addition exactly as §4 originally specified it: a declared Data-tab
   column becomes a calibration-experiment `DATASET_COLUMN` variable binding, preserving the
   original per-row data and units, never collapsed to one curator-typed constant.
3. **§5 rule 5's own "configuration vs. execution, never conflated" principle is now correctly
   applied to `INCOMPATIBLE_EXPERIMENTS_MERGED`**: a genuine condition/binding/mapping
   disagreement between two experiments sharing an arm is a `WARNING`, not an `ERROR` — it
   describes today's narrow trajectory-sharing shortcut (§1 row 4's own "narrow, not general"
   framing), never a reason the *configuration* cannot be saved and reviewed.

## 15. Fifth revision: the configuration close-out increment (implemented — see docs/32)

This revision closes the two configuration gaps docs/31 §2.3/§6 left disclosed rather than
closed (no structured uncertainty/weighting contract beyond free-text `weighting_notes`; the
docs/31 §5 migration-safety note's own general hazard left un-audited) — see
`docs/32_calibration_configuration_close_out_increment.md` for exactly what shipped, the
migration-compatibility audit's own evidence and resolution, and what was verified live. Note
that §1 row 3 ("Declared per-observation error/weighting") was always marked **fully exists,
nothing new to build** — correctly, at the Agent4 execution layer (`Observation.sigma`), which
this increment never touches. The gap this increment closes sits entirely on the Workbench
*configuration* side: nothing in this codebase's import pipeline could durably capture a
real, per-observation uncertainty value, nor explicitly declare which of measured/assumed/
unknown backs a given output, nor validate any of it — a configuration-completeness gap docs/30
§6 first disclosed and docs/31 §2.3 explicitly declined to fabricate a structured value for,
for lack of a real upstream source. Two changes:

1. **A real, structured minimal error/weighting contract**, collected on Screen 2 and
   summarized on Screen 3 exactly like every other configuration input: observation-level
   uncertainty supplied through a new, optional two-tab-workbook sub-table (mirroring §4's own
   independent-variable-column mechanism), or explicitly configured per experiment-output as a
   curator-typed constant — with `measured`/`user-assumed`/`unknown` kept as three distinct,
   always-disclosed states, never collapsed into a boolean or silently defaulted.
2. **A migration-compatibility audit of the docs/31 §5 in-place-edit hazard**: confirmed
   entirely local and unreleased (never committed, never shared, the one database it ever
   touched already fully reset past that state) — documented with its own evidence rather than
   re-asserted, and this increment's own new tables/columns go into a fresh, purely additive
   migration rather than risk a third in-place edit of the same files.
