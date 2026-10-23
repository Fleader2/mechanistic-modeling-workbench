# 30. Joint Calibration Workflow — Configuration-Only Increment

> **Three of this document's own disclosed gaps (§6) are resolved by
> `docs/31_joint_calibration_configuration_prerequisites_increment.md`**: the whole-model
> parameter catalog, dose/arbitrary independent-variable capture, and the
> `INCOMPATIBLE_EXPERIMENTS_MERGED` finding's severity (now a non-blocking `WARNING`, never an
> `ERROR`). Every model/schema/route name below that docs/31 renamed or extended is noted inline
> where it recurs in this document; this document is left otherwise unchanged as the historical
> record of what this specific increment shipped.

Implements the configuration-only slice of `docs/29_joint_calibration_workflow_design.md`
(revised alongside this increment — see that document's §13 and its rewritten §5/§6/§7/§10):
a durable `CalibrationJob` and its own children, a full HTTP API, and a three-screen UI. No
migration, model, or screen in this increment runs a simulation, runs an optimizer, or submits
anything to the Harness — whole-model execution does not exist as a backend capability yet
(docs/29 §6), so every job's own "Run" stays disabled, with a named reason, regardless of how
complete its configuration is.

## 1. What shipped

### Backend

- **Enums** (`app/models/enums.py`): `ModelRelationshipKind`, `CalibrationJobStatus`,
  `CalibrationExperimentRole`, `CalibrationObjectiveWeighting`,
  `CalibrationScenarioOverrideTargetKind`, `CalibrationParameterRoleKind`,
  `CalibrationFindingSeverity`, `CalibrationFindingCategory` (the latter two are Python-only —
  see §2 below for why no Postgres enum type exists for either).
- **Models**: `app/models/model_relationship.py` (`ModelRelationship`, insert-only) and
  `app/models/calibration.py` (`CalibrationJob`, `CalibrationArm`, `CalibrationExperiment`,
  `CalibrationExperimentScenarioOverride`, `CalibrationParameterRole`,
  `CalibrationParameterRoleArm`).
- **Migration** `migrations/versions/0019_calibration_configuration.py` — seven new tables, six
  new Postgres enum types. No existing column is altered or dropped.
- **Persistence** `app/persistence/calibration.py` and `app/persistence/model_relationship.py`
  — every mutation, the optimistic-concurrency (`edit_version`) guard, and
  `compute_findings`/`execution_capability`/`complete_review`.
- **Schemas** `app/schemas/calibration.py`; **routes** `app/api/v1/routes/calibration.py`,
  registered in `app/api/v1/router.py`. Full endpoint list: create/list/get a job; declare and
  list model relationships; add/remove an arm; add/remove an experiment; set an experiment's
  mapping/role/objective-weighting; add/remove a scenario override; add/remove a parameter
  role; preview the review (read-only, always callable); complete review.

### Frontend

- `frontend/src/components/CalibrationJobsListScreen.tsx` — create/list jobs for a study.
- `frontend/src/components/CalibrationJobScreen.tsx` — the three-screen workflow (see §3).
- `frontend/src/types.ts`, `frontend/src/api/client.ts`, `frontend/src/lib/router.ts` extended;
  `App.tsx`/`Sidebar.tsx` wired in (a new "Calibration jobs" nav item, active for its own
  subtree, mirroring "All modules"/"All datasets"'s own precedent).

### Tests

- `tests/persistence/test_calibration.py` — 18 tests: arm/experiment CRUD and auto-pinning,
  scenario-override validation (real species catalog for `INITIAL_CONDITION`, never for
  `PARAMETER`), parameter-role validation, stale-edit rejection, the referenced-arm-not-
  removable guard, and every finding category (`ARM_WITHOUT_MAPPED_EXPERIMENT`,
  `NO_FREE_PARAMETER_TO_FIT`, `CALIBRATION_VALIDATION_DATASET_REUSE`,
  `AMBIGUOUS_SAME_NAME_PARAMETER`, `PARAMETER_ROLE_CYCLE`, `UNIT_INCOMPATIBLE_LINK`,
  `INCOMPATIBLE_EXPERIMENTS_MERGED`), plus `complete_review` success/blocked and the
  any-edit-drops-to-DRAFT rule.
- `tests/api/test_calibration.py` — 6 tests: the full happy path through HTTP (including a
  real alias-mapping save/re-pin round trip), model-relationship declaration/visibility, a
  stale `edit_version` 409, a blocked-review 422 with findings in the error context, a 404 for
  an unknown job, and a 422 for an unreal `INITIAL_CONDITION` species.
- `tests/api/test_calibration_durability.py` — 2 **independent-session** tests (the
  `real_client`/`migrated_engine` machinery `tests/api/test_dataset_model_alias_mapping
  _durability.py` already established): a full job configuration — arm, experiment, scenario
  override, parameter role — is visible from a brand-new request through a brand-new session;
  a job from a different study is a 404, never a cross-study leak.
- `frontend/src/lib/router.test.ts` — 2 new route-parsing tests.

**Results**: backend `667 passed` (641 pre-existing + 26 new), `ruff check` clean on every new
file; frontend `tsc --noEmit` clean, `vite build` succeeds, `node --test` `57 passed` (55
pre-existing + 2 new).

## 2. Design corrections made during implementation (see docs/29 §13 for the full rationale)

Three deliberate departures from the first draft of docs/29's entity list, each verified
against real code before being adopted, not assumed:

1. **`calibration_job` and its children are ordinarily mutable while `DRAFT`**, guarded by one
   `edit_version` optimistic-concurrency token — not the insert-only/orphan-and-replace scheme
   the original design sketched. The closest real precedent, `ModuleSetDraft`/
   `ModuleSetDraftMember` (`app/models/module_set.py`), already does exactly this, and
   reproducing an insert-only scheme here would have added complexity with no corresponding
   correctness benefit (nothing downstream needs a `calibration_arm`'s own edit history the way
   `DatasetModelAliasMappingRevision`'s own immutability actually matters for).
2. **`calibration_compatibility_finding` was never built as a table.** Every finding category
   docs/29 §5 describes is computed fresh, on every call to the review endpoint, directly from
   the job's own live child rows (`app.persistence.calibration.compute_findings`) — identical
   semantics to a persisted table that is always fully recomputed and never incrementally read,
   with one fewer migration and zero risk of a stored finding outliving the state that produced
   it. `calibration_parameter_estimate` is not built at all in this phase — there is no
   `agent4_report` yet to populate it from.
3. **A new, previously-undisclosed capability gap was found and handled honestly, never
   fabricated around**: `calibration_parameter_role.parameter_name` and a `PARAMETER`-kind
   scenario override's own `target_component_id` name a model *parameter*, and no durable,
   authoritative catalog of a whole model's parameters exists anywhere in this codebase —
   confirmed by direct inspection (`ModelSpeciesCatalog` captures species/compartments only;
   grepped for any `ModelParameterCatalog`/equivalent, zero hits). Every such field is
   persisted and displayed as **curator-declared, explicitly marked `catalog_validated: false`
   in the API response**, never silently treated as verified and never inferred from the
   species catalog (a structurally different kind of entity). This is now docs/29 §1 row 15,
   with a concrete, precedent-grounded proposed resolution (a new `ModelParameterCatalog`,
   captured the same way and at the same build-time moment as `ModelSpeciesCatalog`).
   `INITIAL_CONDITION`-kind targets are the one case that *is* validated server-side, against
   the real, already-existing `ModelSpeciesCatalog` — confirmed live (§4, exact-link
   validation and the dependent-field revalidation walkthrough both exercise real species).

## 3. The three screens, as actually implemented

One disclosed simplification from docs/29 §7's letter, not its substance: **one routed URL per
job** (`/projects/:id/studies/:id/calibration-jobs/:jobId`), with the three screens rendered as
internal step state rather than three distinct URLs. Every mutation persists immediately via
its own API call — there is no separate client-side "unsaved draft" to lose, so "Save Draft" is
an informational affordance ("every change is saved immediately"), not a distinct action with
its own request. Back/Next validate only structural completeness of the current step (Next off
Screen 1 requires every arm to have ≥1 experiment); returning to an earlier screen never
discards a later screen's own already-persisted state.

1. **Models & experimental data** — add one or more whole-model versions as arms (a plain
   `<select>` of the study's own models, never a module browser); add datasets as experiments
   per arm, with an unambiguous existing alias mapping pre-selected (checked live against the
   real alias-mapping endpoint) yet always visible and editable; designate each experiment
   `CALIBRATION`/`HELD_OUT_VALIDATION`; a model-relationships section that is **structurally
   absent** until ≥2 arms exist or a relationship is already declared.
2. **Variables, parameters & experimental settings** — an experiment selector (skipped entirely
   for a single experiment); per experiment: independent-variable disclosure (`time` always
   mapped; declared `condition_id` shown read-only; dose/arbitrary variables explicitly
   disclosed as not yet capturable, docs/29 §1 gap #6, never silently omitted), a link to the
   existing alias-mapping screen plus a stale-mapping banner and one-click re-pin, scenario
   overrides (server-validated for `INITIAL_CONDITION`, curator-declared for `PARAMETER`), and
   an objective-weighting declaration. A job-wide parameter-roles section, **always present,
   even for one arm** — this is the one deliberate net-new requirement of the revised design
   (docs/29 §7's audit of this exact point) — with the cross-arm linking roles appearing only
   once ≥2 arms exist.
3. **Review & readiness** — per-arm summary cards, the parameter-role table, every finding from
   `compute_findings` (resolved to human-readable arm names, not bare ids), and the
   execution-capability block, always `available: false` with the named reason in this phase.
   "Complete review" requires zero `ERROR`-severity findings; it is wholly separate from, and
   insufficient for, execution-capability — verified live (§4) for both a 1-arm and a 2-arm job.

## 4. Live-browser verification

Against the real Vite dev server + FastAPI backend (never via direct HTTP), on the confirmed-
disposable `workbench_test` database (reset to a clean migrated baseline, then seeded by a
standalone script that builds two real models with real, `AVAILABLE` species catalogs, a
declared `model_relationship`, and four real saved datasets — one plain, two single-condition
("ctrl"/"treated"), one reused for the drug-treated arm — plus a real alias-mapping revision
for each (dataset, model) pair actually used). All scenarios ran in one Playwright session and
**all passed**:

- **One model, one dataset**: create job → add arm → add experiment (dataset name shown
  immediately from the dropdown) → declare a `MODEL_SPECIFIC` parameter role with bounds →
  Review shows zero blocking findings and the honest, named execution-capability reason →
  Complete review succeeds → **a real full-page reload** confirms `REVIEWED` status and the
  configuration survive independently of any in-memory state.
- **One model, multiple experiments with genuinely different conditions**: adding both the
  "ctrl" and "treated" datasets to the same arm produces a blocking
  `INCOMPATIBLE_EXPERIMENTS_MERGED` `ERROR` finding naming the disagreement, and "Complete
  review" is correctly rejected with that finding surfaced, never silently approximated.
- **Related no-drug/drug models**: adding both arms makes the already-declared
  `model_relationship` appear (never re-declared by the test, confirming the "structurally
  absent until relevant" rule reads real data, not a UI-only toggle); a shared `kcat`
  (`EXACT_EQUALITY`, referencing the no-drug arm) and a state-specific `k_baseline`
  (`MODEL_SPECIFIC`, no-drug arm only) both declare correctly; review reaches `REVIEWED` while
  execution stays honestly disabled for the 2-arm case too — the same named reason as the
  1-arm case, never a different, multi-model-specific excuse (consistent with docs/29 §13's
  "Phase 0/1 blocks every arm count identically").
- **Exact-link validation**: an `EXACT_AFFINE_LINK` submitted with no reference arm/parameter
  is rejected server-side with a precise message — never silently accepted as an unresolved
  link.
- **Stale edits**: two independent browser tabs open the same job; the first tab's edit
  advances the job's own `edit_version`; the second tab's own edit (still holding the old
  version) is rejected with the real 409 message ("This calibration job was edited since you
  last loaded it"), never silently overwriting the first tab's change.
- **Ownership mismatch**: the identical job id, requested under a different study's own URL,
  resolves as not-found — confirmed live that no cross-study data is ever returned. (The
  displayed message says "This project could not be found" rather than naming the job
  specifically — a pre-existing imprecision this screen inherits from every other screen's own
  identical nested-fetch error-handling shape, e.g. `AliasMappingScreen.tsx`; not a regression
  introduced here, and not fixed in this increment since it is a pattern decision affecting
  every existing screen uniformly, not a new defect.)
- **Dependent-field revalidation**: re-saving the alias mapping for a dataset already pinned to
  a calibration experiment creates a new revision; reopening the calibration job shows that
  experiment marked **stale**, with the experiment row itself — and every other, unrelated
  choice in the job — left exactly in place. Nothing was deleted; nothing was silently re-
  pinned.

The dev servers used for this verification were stopped afterward. Per explicit instruction,
**`workbench_test` was not reset or cleaned afterward** — it still holds this verification run's
seeded project/models/datasets/calibration jobs; it remains the confirmed-disposable test
database, never the development database (`DATABASE_URL` was never pointed at it for anything
but this verification run).

## 5. Acceptance scenarios (docs/29 §11), as verified by this increment

| Scenario | Verified by |
|---|---|
| Simple path | §4 "one model, one dataset"; `tests/api/test_calibration.py::test_one_model_one_dataset_reaches_reviewed_but_not_executable` |
| Shared parameters across arms, draft-only pre-Phase-4 | §4 "related no-drug/drug models"; `tests/persistence/test_calibration.py::TestFindings` (ambiguity/cycle/unit checks) |
| Hard-link enforcement at every evaluation | Not executable in this phase by construction — no execution path exists to violate it; the configuration-side half (a hard link must name a real, resolvable reference) is enforced at declaration time, verified by §4 "exact-link validation" |
| Held-out exclusion | `CalibrationExperimentRole.HELD_OUT_VALIDATION` is a real, settable role per experiment; `CALIBRATION_VALIDATION_DATASET_REUSE` blocks the one way this could be silently abused (the same dataset double-counted) — `tests/persistence/test_calibration.py::test_calibration_and_validation_dataset_reuse_is_flagged` |
| Incompatible trajectory reuse blocked | §4 "multiple experiments with genuinely different conditions"; `tests/persistence/test_calibration.py::test_incompatible_experiments_merged_is_flagged_for_differing_scenario_overrides` |
| Explicit execution scope / no module substitution | Every arm is a `Model`, never a `ModelModule` — confirmed by schema (`calibration_arm.model_id` only) and by §4's execution-capability banner naming `WHOLE_MODEL_EXECUTION`, never a module-scoped fallback |

## 6. Remaining limitations, disclosed rather than papered over

- **No execution capability.** `request_model_calibration` does not exist; "Run" is disabled,
  with a named reason, for every job regardless of arm count or configuration completeness.
  This is docs/29's own Phase 1 and is explicitly out of this increment's scope.
- **No whole-model parameter catalog** (§2 above, docs/29 §1 row 15) — every parameter name is
  curator-declared and explicitly disclosed as unvalidated. Building the proposed
  `ModelParameterCatalog` is a real prerequisite for ever validating these, not solved here.
- **Dose/arbitrary independent variables are not capturable.** The §4 workbook-contract
  extension (a new `independent_variables` column, a Metadata sub-table) is dataset-import
  scope, not calibration-configuration scope — implementing it now would have touched the
  import/parser contract this increment was explicitly told to leave alone. Screen 2 discloses
  this honestly rather than faking a mapping control with nothing real behind it.
  `condition_id` (already real, already captured) is the one independent variable this
  increment can and does surface.
- **The compatibility check's condition comparison is an approximation**, not a full
  per-observation comparison: it compares the *set* of `condition_id` values recorded across an
  entire dataset, and discloses (via an `INFO` finding) when a dataset records more than one
  condition rather than attempting a finer-grained, per-row comparison this increment's
  experiment-level (not row-level) granularity cannot cleanly express.
- **No per-observation declared-error (sigma) capture.** `TimeSeriesDatasetRow` has no sigma
  column; `CalibrationObjectiveWeighting.DECLARED_SIGMA` is backed by curator-declared free
  text (`weighting_notes`), honestly labeled, never a fabricated parsed value.
- **One disclosed pre-existing UX imprecision** inherited from this codebase's established
  error-handling shape (§4's "ownership mismatch" note) — a Modeling-Study-level 404 can
  display as if the project itself failed to load. Shared by every other nested-fetch screen in
  this codebase; not introduced or fixed here.
- **One routed URL per job**, not three (§3) — a disclosed simplification of docs/29 §7's
  letter; the three screens' own ordered sections and progressive-disclosure rules are followed
  exactly, just not split across three separate browser URLs.

## 7. Scope discipline

Migrations, models, schemas, and routes are limited to the configuration entities this document
describes — no change to `ModelModule`, `module_calibration_orchestrator`,
`DatasetModelAliasMappingRevision`, `TimeSeriesDataset`/`TimeSeriesDatasetRow`, or any existing
migration. No simulation or optimization code was written. No Figma file was touched. Nothing
in this increment was committed or pushed.
