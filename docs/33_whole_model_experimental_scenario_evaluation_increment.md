# 33. Whole-Model Experimental-Scenario Evaluation Increment

Implements the reliable prediction primitive a future Agent 4 joint-optimization loop will
call once per experiment, per candidate parameter vector: given one saved, immutable
`CalibrationJobRevision`'s own experiment and explicit candidate parameter values, simulate the
whole model and report predictions aligned to the experiment's own real dataset rows.
**Prediction only, never fitting** — no optimizer, no fitting loop, and no module-boundary
workflow was introduced anywhere; `app.persistence.calibration.execution_capability` is
untouched and continues to report calibration (fitting) execution as unavailable,
unconditionally, exactly as `docs/29`/`docs/32` left it. Spans three repositories: Agent 3
(`agent3-simulation-diagnostics`), the integration harness (`agent-integration-harness`), and
this repository.

## 1. Architecture

Mirrors the division of ownership the task itself specified, and the identical three-repository
pattern every prior Agent3-backed increment in this project already uses (most directly,
Module-Set Edited-Module Materialization Phase B, `docs/24`):

- **Agent 3** (`app/agent3/scenario_evaluation.py`) owns whole-model scenario simulation
  itself: applying candidate values/overrides, stepping through declared interventions, and
  reporting a disclosed outcome (`SUCCESS`/`MODEL_LOAD_FAILED`/`INVALID_REQUEST`/
  `SIMULATION_FAILED`/`NUMERICAL_INSTABILITY`) for every call — never raising for an expected
  outcome.
- **The harness** (`app/harness/model_scenario_evaluation.py` + a new runner +
  `scripts/run_workbench_model_scenario_evaluation_request.py`) exposes this as a new,
  independent Workbench-invocable contract (`workbench-model-scenario-evaluation-v1`), routing
  directly to Agent 3 — never through Agent 2, and never through Agent 4.
- **The Workbench** (this repository) owns versioned configuration (the already-existing
  `CalibrationJobRevision`), the evaluation-request resolution logic (catalog validation,
  precedence, dosing-schedule rejection — §3 below), submission, background execution,
  persistence, and presentation (observed-vs-predicted table).

## 2. Agent 3: `evaluate_scenario`

New module `app/agent3/scenario_evaluation.py` (agent3-simulation-diagnostics), alongside the
existing `app.agent3.simulation`/`app.agent3.perturbation`. Request fields:
`parameter_overrides`/`initial_value_overrides` (applied once, before integration begins),
`interventions` (a tuple of `StepIntervention{target_kind, target_id, time, value}` — step
changes applied *during* the trajectory, sorted and applied in time order), `requested_times`
(any order, duplicates allowed), `requested_output_ids`.

Every evaluation loads a **fresh** `RoadRunner` instance via the existing
`app.agent3.loader.load_antimony_model` — never reused or cached across calls, so two
evaluations can never leak state into each other. Identifier validation happens against the
real, compiled model (never trusted from a caller's own catalog), collecting every unresolved
identifier together, never just the first. A value requested at exactly the same time an
intervention takes effect reports the state *immediately before* that intervention (the
"already observed, then the dose was given" convention, documented once in the module
docstring).

Segmented simulation (`rr.simulate(times=[current_time, breakpoint])`, continuing state across
segments, confirmed empirically against the real roadrunner engine during this increment's own
design phase) is what makes a step intervention actually restart decay from its own new value,
rather than from where the unmodified trajectory would have been.

**Tests**: `tests/agent3/test_scenario_evaluation.py`, 15 new tests — analytic-decay match,
parameter override, initial-value override, species- and parameter-targeted interventions
(exact pre/post values checked against the closed-form decay solution), irregular/repeated
requested times (including an exact duplicate-value equality check), A→B→A state-isolation
(three sequential calls), every unresolved-identifier/malformed-request case, solver failure,
numerical instability, and multi-output alignment with a mass-conservation check. **52/52**
`tests/agent3/` pass (37 pre-existing + 15 new), `ruff check` clean.

## 3. The harness contract

New, independent contract in `app.harness.workbench_contracts`
(`WORKBENCH_MODEL_SCENARIO_EVALUATION_CONTRACT_VERSION = "workbench-model-scenario-evaluation-
v1"`): `WorkbenchModelScenarioEvaluationRequest`/`Result` + `WorkbenchStepIntervention`, a new
`WorkbenchRunErrorCode.MODEL_SCENARIO_EVALUATION_FAILED`, mirroring
`WorkbenchModelAntimonyVerificationRequest`/`Result`'s own established shape byte-for-byte.
`app.harness.model_scenario_evaluation` + `app.harness.runners
.run_agent3_evaluate_whole_model_scenario` + `scripts/run_workbench_model_scenario_evaluation
_request.py` complete the chain: subprocess-isolated (Agent 3's own venv/cwd, never imported
directly), idempotent replay by `run_id` (a second identical request reads the cached result
back rather than re-invoking Agent 3), `WorkbenchRunStatus.SUCCEEDED` whenever the evaluation
*ran* (even a disclosed `MODEL_LOAD_FAILED`/`INVALID_REQUEST` outcome) — `FAILED` reserved for a
genuine infrastructure defect.

**Tests**: `tests/harness/test_workbench_model_scenario_evaluation_contract.py`, 11 new tests,
every one a real, end-to-end subprocess round against real Agent 3 Antimony/RoadRunner
execution (no mocked loader) — contract round-trip, version-mismatch/malformed-request
rejection, analytic-decay match, candidate-parameter-value change, step intervention, distinct
predictions from distinct fixed doses, unresolved-identifier and malformed-Antimony disclosed
outcomes, and replay. **258/258** harness tests pass (247 pre-existing + 11 new), `ruff check`
clean.

## 4. The Workbench's own evaluation-request resolution

New `app/persistence/calibration_scenario_evaluation.py::resolve_scenario` — the one place the
task's "evaluation contract" requirements (validate against catalogs; apply precedence; reject
conflicts; distinguish independent scenarios from interventions; never guess an intervention
target's kind) are actually enforced, operating on one saved revision's own frozen
`snapshot_payload`, never the live, possibly-still-being-edited draft.

**Per-binding resolution**, by `model_meaning`:

- `INITIAL_VALUE`/`PARAMETER_OVERRIDE`: resolved to one value (either the binding's own
  `CONSTANT`, or read from the dataset — see dosing-schedule rule below) and placed directly
  into the scenario's own `initial_value_overrides`/`parameter_overrides`.
- `INTERVENTION`: resolved the same way, plus `intervention_time` (new field, below); its own
  `target_kind` (`SPECIES`/`PARAMETER`, required by the harness contract) is determined by
  checking which of the model's own real, `AVAILABLE` species/parameter catalog actually
  contains the target id — never guessed. An id resolvable against neither catalog is rejected
  with an actionable error, never silently assumed to be one or the other.

**Conflict rule**: a caller-supplied candidate parameter value for a target already claimed by
a `PARAMETER_OVERRIDE`/parameter-targeted `INTERVENTION` binding is always rejected — supplying
at most one source for any one target's value is required, never arbitrated by precedence.

**Dosing-schedule rule**: a `DATASET_COLUMN`-sourced binding's value must be identical across
every dataset row in scope (the experiment's own rows, further scoped to one `condition_id`
when the dataset declares more than one) — a column that genuinely varies within that scope is
rejected, naming every distinct value found, never silently reduced to a single scalar (the
task's own "never treat successive dose rows as a dosing schedule without explicit
instructions"). An experiment whose dataset declares conditions but received no `condition_id`
is rejected as ambiguous, rather than guessing one.

**Output resolution**: every `ASSIGNED` row of the experiment's own saved dataset↔model alias
mapping revision (an experiment with none is rejected — no output species to predict).
`requested_times`/`requested_row_ids` come directly from the real, in-scope dataset rows
(`TimeSeriesDatasetRow.time_value`/`.id`), in original row order including duplicates — the
mechanism that makes "predictions aligned to exact dataset rows" and "irregular/repeated times"
actually hold.

### 4.1 `intervention_time` — the one new configuration field

`CalibrationExperimentVariableBinding.intervention_time` (nullable `NUMERIC`, migration `0022`):
required if and only if `model_meaning=INTERVENTION`, enforced by both a database `CHECK`
constraint and `app.persistence.calibration.add_variable_binding`. Without it, `INTERVENTION`
was behaviorally identical to `INITIAL_VALUE`/`PARAMETER_OVERRIDE` (all three previously took
effect at `t=0` with no way to say otherwise) — this field is what actually lets the three
`model_meaning`s mean different things. Plumbed through the model, the migration, the
persistence layer, the revision snapshot payload, the schema/route layer, and a minimal
frontend input (shown only when `model_meaning=INTERVENTION`).

## 5. Persistence, background execution, and provenance

Mirrors `app.persistence.module_set_execution`'s own submit/claim/track discipline exactly
(Module-Set Edited-Module Materialization Phase B, `docs/24`), substituting a
`CalibrationExperiment` for a `ModuleSetMember`:

- `RunRecord.calibration_experiment_id` (nullable FK, `RESTRICT`, migration `0022`) —
  distinguishes a scenario-evaluation run from every other kind.
- `CalibrationScenarioEvaluationSnapshot` (new table, migration `0022`) — one immutable,
  pinned record per run (`run_record_id` unique, `RESTRICT` from every FK): the model artifact
  reference/checksum, every resolved override/intervention, the requested times/row ids/output
  ids, the candidate values actually supplied, and the solver settings. Created once, at
  submission time, before any harness subprocess runs — a snapshot exists even for a run that
  later fails.
- **Duplicate-active-run detection is deliberately *not* a database constraint here** (unlike
  `module_set_member_id`'s own single-table partial unique index): the columns identifying "the
  same scenario" (`condition_id`, `input_hash`) live on the snapshot table while run status
  lives on `RunRecord`, and a Postgres partial-index predicate cannot reference another table.
  Enforced instead at the persistence layer (`submit_scenario_evaluation`), a disclosed,
  best-effort check — scoped deliberately narrowly, to a *genuinely identical* resubmission
  (same experiment, condition, candidate values, and solver settings): re-evaluating the
  identical scenario against a *different* candidate vector is always allowed to proceed
  concurrently, since that is exactly how Agent 4's future joint-optimization loop will call
  this repeatedly.
- `app.orchestration.calibration_scenario_evaluation_orchestrator.process_one_pending_run` +
  `app.orchestration.model_scenario_evaluation_harness_client` +
  `scripts/calibration_scenario_evaluation_worker.py` — the background worker's own unit of
  work, mirroring `module_set_execution_orchestrator`/`module_set_simulation_harness_client`/
  `module_set_simulation_worker.py` exactly, including the identical re-read-before-write
  discipline guarding against a manual stuck-run recovery racing a worker that was never
  actually dead.

`RunRecord.status` reflects the *scenario's own outcome*, not merely "the harness call
returned": `SUCCEEDED` only when `evaluation_status="SUCCESS"`; every other disclosed outcome
(`MODEL_LOAD_FAILED`/`INVALID_REQUEST`/`SIMULATION_FAILED`/`NUMERICAL_INSTABILITY`) is recorded
as `RunRecord.status=FAILED`, with the specific reason in `error_summary` — consistent with this
project's own established "a failed run remains visible, labeled honestly, never silently
retried" convention.

## 6. API surface

Three routes, mirroring the module-set-simulation submit/list/get pattern exactly, added to
`app/api/v1/routes/calibration.py` (never `projects.py` — calibration already owns its own
router):

```
POST /projects/{p}/subprojects/{s}/calibration-jobs/{j}/revisions/{n}/experiments/{e}/scenario-evaluations
GET  /projects/{p}/subprojects/{s}/calibration-jobs/{j}/revisions/{n}/experiments/{e}/scenario-evaluations
GET  /projects/{p}/subprojects/{s}/calibration-jobs/{j}/revisions/{n}/experiments/{e}/scenario-evaluations/{run_id}
```

`POST` returns immediately with a `PENDING` run (never holds the request open); `422` for an
unresolvable scenario (`ScenarioResolutionError`, no run ever created); `409` for a genuinely
identical active run. `app.schemas.calibration_scenario_evaluation.ScenarioEvaluationRunItem`
carries status/timing always, and (once terminal) `evaluation_status`/`validation_errors`/
`solver_message`/an `observed_vs_predicted` row list (`{row_id, output_id, column_name, unit,
observed, predicted}`, one row per requested-time × output pair) — the exact shape the
frontend's observed-vs-predicted table renders directly.

**Tests**: `tests/persistence/test_calibration_scenario_evaluation.py` (11 tests) +
`tests/api/test_calibration_scenario_evaluation.py` (7 tests), all real — a real harness
subprocess round against real Agent 3 execution every time a run is actually processed, never
mocked. Covers: analytic-decay match; candidate-parameter-value change; distinct predictions
from distinct conditions/doses (the task's own explicit "different fixed doses/conditions"
requirement); A→B→A state isolation across three sequential submissions; irregular/repeated
dataset times aligned exactly (including an exact duplicate-value equality check); every
rejection in §4 (conflicting override, dosing-schedule violation, unmapped experiment, duplicate
active run); a durable `FAILED` run from a corrupted Antimony artifact (never an exception);
persistence surviving an expired ORM identity map; and, at the API layer, ownership isolation
(an unrelated subproject's identical job/revision/experiment ids never resolve) and a malformed
candidate value rejected as `422`. **749/749** backend tests pass (731 pre-existing + 18 new),
`ruff check .` clean.

## 7. Frontend

`ScenarioEvaluationPanel`, a new component inside `CalibrationJobScreen.tsx`'s existing
`RevisionsPanel` (shown once a revision's snapshot is opened) — there is no Figma reference for
this screen, so it follows `ModuleSetMemberExecutionScreen`'s own established submit/poll/
display structure (3s polling interval against any non-terminal run, since the background
worker runs out-of-process) rather than a design reference. Lets the scientist pick which
experiment, an optional `condition_id`, and candidate parameter values (`name=value`, one per
line); submits; polls to completion; renders the observed-vs-predicted table with its own
per-output unit, never silently converted. New API client functions
(`submitCalibrationScenarioEvaluation`/`listCalibrationScenarioEvaluations`/
`getCalibrationScenarioEvaluation`) and types (`ScenarioEvaluationRunItem`,
`SubmitScenarioEvaluationRequest`) mirror the module-set-simulation client exactly.
`npx tsc --noEmit` clean (no ESLint is configured in this project).

## 8. Live-browser verification

**Database-identity discipline** (`docs/22`): every server/script in this verification had
`DATABASE_URL` explicitly overridden to `workbench_test`, confirmed disposable via
`scripts.db_safety.require_disposable_database` before anything was seeded. A direct query
against the real development database (`workbench`) after the session, from outside any test
fixture, confirms `calibration_job` does not even exist as a table there — definitive evidence
this increment's live verification never touched it.

A one-off scratch seed script (never committed) built one real job: a model with one species
(`S1`) and one independent parameter (`k1`) in an exact exponential-decay Antimony model
(`ds/dt = -k1*s`), one experiment with three real dataset rows (`t=0,1,2`, `condition_id=ctrl`),
mapped and reviewed to a captured `CalibrationJobRevision`. `uvicorn` (port 8000),
`scripts/calibration_scenario_evaluation_worker.py` (2s poll interval), and `vite dev` (port
5173) were brought up against that same database, exactly as `docs/16`/`docs/17`'s own
established live-verification convention. A real Chromium browser (Playwright, pointed directly
at an already-installed `chromium-1148` binary — the npm package's own expected revision was
unavailable, and this machine's `playwright install` extraction hangs, per this project's own
documented workaround) drove the actual running servers.

Every observed result below is this script's own printed output or a screenshot it captured,
never an assumption:

| Step | Observed result |
|---|---|
| Navigate to the job's "3. Review & readiness" step, open the revision | Snapshot JSON renders; "Execution capability: Not yet execution-ready: Whole-model execution is not yet available for calibration" still shown, unchanged |
| Fill `condition_id=ctrl`, `k1=2.0`, click "Evaluate scenario" | "Runs: Pending" renders immediately |
| Wait for the out-of-process background worker (no manual refresh) | "Succeeded — SUCCESS" renders automatically via polling |
| Observed-vs-predicted table | `obs_S1`: row 1 observed `10`/predicted `10`; row 2 observed `6.065`/predicted `1.3533528692641947`; row 3 observed `3.679`/predicted `0.18315639887456137` |
| Predictions checked against the closed-form solution | `10*exp(-2*1) = 1.353352869...`, `10*exp(-2*2) = 0.183156398...` — exact match to the digits shown |
| Full page reload, reopen the identical revision/panel | The identical "Succeeded — SUCCESS" result and table render again, immediately — read back, never re-run |

This exercises the full task-required "submit → progress → results → refresh/reopen" path, and
confirms — visually, not merely by code inspection — that the new scenario-evaluation capability
and the pre-existing, still-disabled calibration (fitting) execution capability render and
behave as two genuinely independent things on the same screen.

## 9. Remaining limitations, disclosed rather than papered over

- **An `INTERVENTION` binding with no relevant catalog available at all** (curator-declared,
  the documented gap `docs/29`/`docs/31` already disclose for `PARAMETER_OVERRIDE`) cannot be
  resolved to `SPECIES`/`PARAMETER` at evaluation time, and is rejected with an actionable
  error rather than guessed. Closing this would require a real whole-model parameter/species
  catalog to always exist, which is still only conditionally available today.
- **Duplicate-active-run detection is best-effort**, not a database-level guarantee (§5) — a
  genuine race between two near-simultaneous, byte-identical submissions could in principle
  both succeed in creating a run. Accepted as a disclosed limitation, consistent with how this
  increment's own migration explains why a single-table partial unique index (the mechanism
  `module_set_member_id` uses) is not available here.
- **One experiment, one condition, one call** — exactly the task's own stated unit of
  evaluation. Cross-arm linking, joint multi-experiment trajectories, and anything resembling
  an optimization loop remain explicitly out of scope, reserved for Agent 4.
- **The background worker's own crash-recovery behavior is unchanged from, and identically
  disclosed to, `module_set_simulation_worker.py`'s own**: a run already claimed (`RUNNING`)
  when the worker process is killed outright is not automatically recovered.

## 10. Scope discipline

No optimizer, fitting loop, or module-boundary workflow was introduced in any of the three
repositories touched. `execution_capability`/`WHOLE_MODEL_EXECUTION` is untouched and still
reports calibration (fitting) execution as unavailable, with the identical named reason, on the
same screen the new "Evaluate scenario" panel now sits beside — confirmed by direct inspection
of the live-verification screenshots in §8, not merely by code review. Agent 2 is never invoked
by any part of this increment (the pinned model's own Antimony text, already captured by its
species catalog, is reused directly, exactly as `app.orchestration
.model_antimony_verification_harness_client` already established as this project's convention).
