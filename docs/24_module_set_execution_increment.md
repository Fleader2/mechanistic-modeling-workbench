# Module-Set Edited-Module Materialization Increment: Boundary Review and Simulation for an Edited Member

Builds on `docs/20_module_set_domain_contract.md` (domain contract, now updated in place for
this increment -- see its third revision note) and `docs/23_module_set_manual_editing_increment.md`
(module renaming and reaction-membership editing within a draft). Spans three repositories --
`mechanistic-modeling-workbench` (this repo), `agent-integration-harness`, and
`agent2-antimony-builder` -- per the task's explicit cross-repo authorization.

Scope, exactly as asked: a saved module-set version's own member, whether its reaction
membership was ever edited or not, can now be boundary-reviewed and, once ready, simulated
through a real, edited-selection-aware Agent 2 rematerialization + Agent 3 round trip, run in
the background, with durable results. The completion target was **execution of edited
modules**, not merely detecting that they were edited -- blocking an edited module from ever
simulating was explicitly rejected as an acceptable end state. Figma was not touched; no
calibration/validation/aggregation/split-merge was added; nothing was committed or pushed, in
any of the three repositories.

## 1. Phase A -- the dependency audit, and why no Agent 2 change was needed

Before writing any code, the actual blocker had to be identified: Agent 2's
`materialize_submodel` (`agent2-antimony-builder/app/agent2/submodel_materialization/
materialization.py`) already recomputes a *full* dependency closure (species, parameters,
compartments, rules, events, observables) from a bare `frozenset[str]` of reaction ids, via
`compute_dependency_closure` in `closure.py` -- which validates unknown ids and raises a plain
`ValueError`, exactly the behavior an edited, reaction-only selection needs. **Agent 2 required
zero changes** -- confirmed by an empty `git status` in `agent2-antimony-builder` throughout
this entire increment.

The real gap was one level up, in the Harness's existing *unedited*-module materialization path:
`run_agent2_materialize_module_handoff.py` trusts whatever species/parameter memberships it is
handed verbatim, with no closure recompute. Feeding it a reaction-only edited selection directly
would have silently produced a wrong artifact (no species/parameters at all, since none were
ever supplied). The fix is a new insertion point, not a change to the existing, still-used
entrypoint: `materialize_submodel` runs *between* "attach" and "build handoff," in a new runner
that never touches the old one or its callers.

Boundary-candidate derivation needed **no changes at all**, edited or not: it reads
reaction-participant topology directly from the rebuilt full network's own `reactions_by_id`,
never from an attach payload's absent species/parameter memberships -- confirmed by reading
`run_agent2_derive_boundary_candidates.py` in full.

Source-model availability was also not a blocker: no full `ModelSpecification` is persisted to
disk after a hierarchical run, but `agent1_view_path`/`stage1_synthetic_source` (recorded in the
originating `RunRecord.artifact_reference`, durably retained) deterministically rebuilds it --
the same mechanism `resolve_stage1_inputs` already relies on for every other module-scoped
harness call in this codebase.

## 2. Phase A implementation (Harness repository)

All new, nothing modified in any file an existing caller depends on:

- `app/harness/runners/run_agent2_rematerialize_module.py` -- mirrors
  `run_agent2_materialize_module_handoff.py`, but calls `materialize_submodel(model,
  attached_modularization_id, target_module_id)` first and builds the handoff from *its* result,
  never the original attach payload. Catches `ModuleCalibrationReferenceError` into a
  `readiness_blocked_reason` rather than crashing (materialized-but-not-yet-simulatable is an
  expected, non-exceptional state). Outputs lineage (`retained_reaction_ids`,
  `retained_species_ids`, `retained_parameter_ids`, etc.) and `unresolved_dependencies`.
- `app/harness/module_rematerialization.py` / `scripts/run_workbench_module_rematerialization_
  request.py` -- the idempotent-replay-by-`run_id` workflow + canonical entrypoint, mirroring
  `module_boundary_derivation.py`'s own established pattern exactly.
- `app/harness/module_set_simulation.py` / `scripts/run_workbench_module_set_simulation_request.py`
  -- calls the rematerialization workflow as a library call (requiring non-empty `module_ports`,
  since this contract's whole purpose is simulation, never a quiet materialize-only fallback),
  then runs the unchanged `run_agent3.py` on the result.
- New contracts in `app/harness/workbench_contracts.py`
  (`WORKBENCH_MODULE_REMATERIALIZATION_CONTRACT_VERSION = "workbench-module-rematerialization-v1"`,
  `WORKBENCH_MODULE_SET_SIMULATION_CONTRACT_VERSION = "workbench-module-set-simulation-v1"`) and
  policy versions in `app/harness/version.py`
  (`MODULE_REMATERIALIZATION_WORKFLOW_POLICY_VERSION`, `MODULE_SET_SIMULATION_WORKFLOW_POLICY_VERSION`).
- Tests: `tests/harness/test_workbench_module_rematerialization_contract.py` (12 tests --
  round-trips, every rejection class, legacy-unedited-selection-unchanged, and the central
  scientific proof: moving a reaction between two synthetic modules changes each one's own
  `retained_parameter_ids` correctly) and `tests/harness/test_workbench_module_set_simulation_
  contract.py` (7 tests, including one **real, end-to-end Agent 2 + Agent 3 subprocess
  execution** against a 2-of-3-reaction edited selection, confirming `reaction_count == 2` and
  `retained_reaction_ids == ["reaction-1", "reaction-2"]`).
- Full harness suite: 238 passed (excluding one unrelated, pre-existing fixture test this
  increment never touched). `ruff format`/`ruff check`: clean.
- **Note on harness repo status:** `git status` in `agent-integration-harness` also shows two
  pre-existing, harmless reformatting-only diffs (`docs/09_recursive_module_evaluation_
  orchestration.md`, `tests/harness/test_module_calibration_workflow.py`) -- line-wrap-only
  changes from this increment's own repo-wide `ruff format .` pass, touching code this increment
  never otherwise changed. Left as-is rather than reverted, since reverting would require a
  destructive `git checkout` on files outside this increment's own scope.

## 3. Phase B design decisions (this repository)

- **Reused `ModuleExecutionSnapshot`** (schema-ready since the Calibration increment, its
  `ModuleExecutionKind.SIMULATION` value never wired up before) for the pinned, immutable
  execution-input snapshot, rather than a new table. `execution_kind=SIMULATION`,
  `model_module_id=member.model_module_id`, and `snapshot_payload` JSON carries
  `{module_set_member_id, reaction_component_ids, resolved_boundary_ports, solver_settings,
  saved_by}`.
- **Reused `RunRecord`'s existing PENDING → RUNNING → SUCCEEDED/FAILED state machine**
  (`create_run_record`/`start_run`/`complete_run`, completely unmodified) as the job/run entity,
  `stage=RunStage.AGENT3`, plus one new nullable `module_set_member_id` FK column.
- **A genuinely new, separate review table pair** rather than reusing the module-level
  `ModuleBoundaryPort`: `module_set_member_review` (one row per member, `review_version` as the
  optimistic-concurrency token) and `module_set_member_boundary_port` (candidate/decided ports,
  scoped to a review, reusing the existing `ModulePortDirection`/`ModuleBoundaryTreatmentType`/
  `ModuleBoundaryResolutionStatus` enums). `ModuleSetMember`/`ModuleSetVersion` themselves are
  **never** mutated by anything in this increment -- they stay exactly as immutable as `docs/21`
  established.
- **No solver-settings configurability exists in the current Agent3/Harness contract at all.**
  `SubmitModuleSetSimulationRequest.solver_settings` is accepted and stored but never actually
  varies the harness call -- disclosed honestly as empty/unconfigurable rather than invented.
- **A true DB-level duplicate-submission guard**: a partial unique index,
  `uq_run_record_one_active_run_per_module_set_member` on `run_record.module_set_member_id
  WHERE module_set_member_id IS NOT NULL AND status IN ('PENDING', 'RUNNING')`, mirroring
  increment 21's own `uq_module_set_draft_open_per_set` pattern -- not merely an application-
  level check that a race could slip past.
- **A dedicated out-of-process background worker**, not an inline synchronous call, is the
  first thing in this codebase's history to need one: every other harness call here runs inside
  its own triggering HTTP request. `scripts/module_set_simulation_worker.py` polls, claims one
  `PENDING` run at a time via `SELECT ... FOR UPDATE SKIP LOCKED` (with an explicit,
  documented, same-function `session.commit()` -- the one deliberate exception to this
  codebase's "caller commits" convention, since the claim must be atomically visible to other
  workers immediately), and processes it with its own fresh session, never one an API request
  used. `--once` processes at most one run and exits (used by this report's own live
  verification); otherwise it polls until SIGINT/SIGTERM, finishing its current run first.
  **Disclosed limitation, not an oversight:** a worker `SIGKILL`/crash/machine-restart while a
  run is `RUNNING` leaves it durably stuck, with no lease/heartbeat/timeout/automatic-recovery
  mechanism anywhere -- recovering it today requires an operator to re-queue it by hand. This
  increment's own test suite proves the *first* half of that claim directly (a claimed run stays
  `RUNNING` for a second, independent session with no worker ever finishing it) rather than
  merely asserting it.

## 4. Migration

`migrations/versions/0015_module_set_execution.py` (`0014_module_set_editing` → `0015`): new
tables `module_set_member_review`, `module_set_member_boundary_port`; `run_record.
module_set_member_id` (nullable FK, `RESTRICT`) plus the partial unique index described above.
Round-trip (`upgrade` → `downgrade` → `upgrade`) verified as part of the full migration-history
replay this increment's own durability tests perform.

## 5. Backend surface added

- **Persistence** (`app/persistence/module_set_execution.py`): `get_or_create_review`,
  `persist_candidate_boundary_ports` (idempotent -- never overwrites an existing decision),
  `submit_boundary_decision` (optimistic-concurrency-checked, raises
  `ModuleSetMemberReviewStaleError` on mismatch), `evaluate_readiness` (returns
  `ReadinessFinding`s; empty means ready -- explicitly documented as never proving whole-model
  coverage or biological validity, only that Agent 2 has enough resolved structural information
  to build a standalone artifact), `build_resolved_module_ports_payload`,
  `submit_module_set_simulation` (stale-review → not-ready → duplicate-active, checked in that
  order, each its own typed exception), `claim_next_pending_module_set_run`,
  `get_execution_snapshot_for_run`, `list_runs_for_module_set_member`.
- **A new shared helper**, `effective_reaction_component_ids` (`app/persistence/module_set.py`):
  a member's own real, current reaction selection regardless of whether it was ever edited --
  its own `reaction_component_ids` when set, or derived fresh from its `ModelModule`'s
  `attach_payload` otherwise (`NULL` means "never edited," never "empty"). Added because this
  increment's own first version of `submit_module_set_simulation`/boundary-derivation payload
  construction fell back to an **empty list** for an unedited member -- caught by this
  increment's own persistence tests before it ever reached the harness (an unedited member would
  otherwise have been simulated as if it had zero reactions).
- **Orchestration** (`app/orchestration/module_set_execution_orchestrator.py`):
  `derive_boundary_candidates` (builds a reaction-only attach payload from the member's
  effective selection, calls the unmodified boundary-derivation harness client, persists
  candidates), `process_one_pending_run` (the worker's unit of work -- rebuilds everything from
  the run's own *pinned snapshot*, never the live member, so a later edit to another member can
  never retroactively change what an already-submitted run actually executes).
- **Harness clients**: `module_rematerialization_harness_client.py` (300s timeout),
  `module_set_simulation_harness_client.py` (600s timeout -- two real subprocess rounds),
  mirroring the existing `module_simulation_harness_client.py` exactly.
- **API** (`app/api/v1/routes/projects.py`, six new routes under
  `.../module-sets/{id}/versions/{version}/members/{member_id}/`):
  `POST boundary-review/derive`, `GET boundary-review`, `POST boundary-review/ports/{port_id}/
  decision`, `POST simulations` (201, PENDING), `GET simulations`, `GET simulations/{run_id}`.
  All scoped under the **version** path -- a draft has no execution route at all, by routing,
  not by a runtime check (verified by a dedicated test, §6).

## 6. Test evidence

- **Harness repository**: 238 passed (described above).
- **This repository**, 535 passed total (487 pre-existing + 42 new + 6 added in the follow-up
  closure review, §8 below), `ruff check`/`ruff format` clean, frontend `tsc --noEmit` +
  `vite build` + 27 `node --test` tests (25 pre-existing + 2 new router tests) all clean:
  - `tests/persistence/test_module_set_execution.py` (19 tests) -- review/candidate/decision
    lifecycle, readiness evaluation, simulation submission (including the
    `effective_reaction_component_ids` regression above), the worker's claim mechanism
    (including "never claims an ordinary non-module-set run").
  - `tests/orchestration/test_module_set_execution_orchestrator.py` (5 tests, harness client
    mocked via `monkeypatch` -- the same convention `test_model_module_orchestrator.py` already
    established) -- boundary derivation's attach-payload construction, and
    `process_one_pending_run`'s three outcomes (succeeded, harness-reported failure,
    client/transport error), each completing the run rather than ever leaving it stuck.
  - `tests/api/test_module_set_execution.py` (13 tests) -- the full HTTP surface: derive/decide/
    readiness/submit/list/reopen, ownership isolation (a member from a different study 404s),
    and the explicit "a draft member has no execution route at all" routing test.
  - `tests/api/test_module_set_execution_durability.py` (5 tests, following
    `test_module_set_durability.py`'s own independent-real-session pattern exactly) -- a
    derived candidate and a submitted decision are visible from a second, independent session;
    a submitted simulation and its pinned snapshot are durable; CORS preflight for both new
    POST routes; and the worker-crash-recovery disclosure above, proven directly rather than
    merely asserted.
  - `tests/orchestration/test_module_set_run_recovery.py` (6 tests, added in the follow-up
    closure review, §8 below) -- the documented recovery procedure end-to-end against real,
    independently-committing sessions: `find_stuck_runs` age-thresholding, the recovery CLI's
    dry-run (lists, mutates nothing) and `--confirm` (durably marks `FAILED`, unblocks a fresh
    resubmission) modes, a genuinely fresh `RUNNING` run surviving `--confirm` untouched, and
    the race-safety helper discarding a "late" worker completion once recovery has already
    terminalized a run.

## 7. Live verification (real Harness/Agent2/Agent3 execution, not mocked)

Seeded a disposable `workbench_test` database (verified via `scripts/db_safety.py::require_
disposable_database` before any write, exactly as every prior increment's live verification
did) with a hierarchical run over the harness's own `tests/fixtures/synthetic_agent1_view.json`
fixture (a linear chain `S1 → S2 → S3 → S4` via `reaction-1/2/3`), two sibling modules
(`moduleA=[reaction-1]`, `moduleB=[reaction-2, reaction-3]`), saved unedited as v1, then a
second draft moving `reaction-2` into `moduleA` and saved as v2
(`moduleA=[reaction-1, reaction-2]`, the edited target). Backend (`uvicorn`) and the background
worker (`scripts/module_set_simulation_worker.py --interval 3`) were run directly against this
database; the frontend build/typecheck/test were separately confirmed clean (§5), but this
session's tooling has no browser-automation access, so the walkthrough below drives the same
HTTP surface the frontend screen calls, rather than the rendered UI itself -- disclosed
explicitly rather than silently substituted for a browser walkthrough.

**A real integration bug was found and fixed by this step, never caught by any mocked test**:
the first real submission failed with `KeyError: 'module_id'` inside the harness's own
`run_agent2_rematerialize_module.py` -- `build_resolved_module_ports_payload` was missing the
`module_id` key every `ModulePort` the harness constructs actually requires (present in the
pre-existing, structurally identical `build_module_ports_payload`, but not copied into this
increment's new function). No mocked unit test could have caught this, because every one of
them replaces the harness call itself; only a real subprocess invocation parses the JSON file
this bug corrupted. Fixed in `app/persistence/module_set_execution.py` (now takes an explicit
`module_id` parameter); a regression test
(`TestBuildResolvedModulePortsPayload::test_includes_module_id_in_the_exact_shape_the_harness_
requires`) was added directly asserting the dict's exact key set, and the full backend suite
re-confirmed green (§6's counts already include it).

With the fix in place, re-seeded and re-verified in full:

1. `GET boundary-review` on the never-derived edited member → `{ports: [], ready: false,
   findings: [NO_BOUNDARY_PORTS_DERIVED]}`.
2. `POST boundary-review/derive` → a **real** boundary-derivation harness call → exactly one
   candidate, `compound-S3::in::compartment-1` (`OUTPUT`) -- matching the Harness repository's
   own proven result for this identical edited selection (§1/§2), confirmed independently here
   through the full Workbench stack rather than assumed.
3. `POST boundary-review/ports/{id}/decision` (`EXTERNALLY_CONTROLLED`, `1.0 mM`) →
   `review_version: 1`, `ready: true`.
4. A stale decision (`expected_review_version: 0` against the now-current `1`) → `409`, with
   `current_review_version: 1` in the error context.
5. `POST simulations` (`expected_review_version: 1`) → `201 PENDING`.
6. With the worker paused (`SIGSTOP`), an immediate second submission → `409 CONFLICT`, the
   existing run's own id in the error context -- the true duplicate-submission guard, proven
   without a timing race (resuming the worker with `SIGCONT` let it complete normally
   afterward).
7. The worker (resumed) picked up each submitted run within one polling interval and completed
   it in well under a second: `status: SUCCEEDED`,
   `module_handoff_summary: {species_count: 3, reaction_count: 2, parameter_count: 2}`,
   `lineage.retained_reaction_ids: ["reaction-1", "reaction-2"]` (never `reaction-3` --
   proving the rebuilt artifact's executable membership matches the edited selection, not the
   original materialization), and a real Agent 3 report (`overall_status: SUCCESS`,
   `load_succeeded: true`, a genuine simulated time course).
8. Reopening the same run twice in a row (`GET simulations/{id}`) returned an identical,
   unchanged `completed_at` both times -- confirmed no rerun occurs on reopen.
9. The unedited v1 version's own `moduleA` member was checked throughout and remained
   completely untouched: `reaction_component_ids: ["reaction-1"]`, `membership_edited: false`,
   and its own (lazily-created, empty) boundary review showed zero ports/findings -- no
   execution activity on v2 ever leaked into v1.
10. `POST simulations` against v1's own never-derived member → `422`, with
    `NO_BOUNDARY_PORTS_DERIVED` in the findings context -- the readiness gate enforced
    identically for an unedited member.
11. A wrong-project id against the same route → `404`, identical in shape to an unrecognized
    id -- ownership isolation confirmed live, not only in the test suite.

Both services were stopped and `workbench_test` was reset to a clean migration-history baseline
afterward (`alembic downgrade base && alembic upgrade head`) -- no seeded verification data was
left behind. The real development database (`workbench`) was never started, connected to, or
referenced at any point in this increment.

## 8. Follow-up closure review (architecture, artifact consistency, worker recovery, solver
settings)

A later instruction, before any commit, required re-confirming four specific points plus one
side note. Each was investigated and (where a genuine gap existed) closed in this same session;
every claim below was verified against the actual current code, never assumed from this
document's own earlier sections.

**Architecture: does the Harness reach into Agent 2's private internals?** No -- confirmed
clean, no code change needed. `run_agent2_rematerialize_module.py`'s imports
(`app.agent2.module_calibration`, `app.agent2.module_calibration.errors`, `app.agent2.pipeline`,
`app.agent2.types`, `app.agent2.build_request`) are identical top-level public-module imports to
the two pre-existing runners (`run_agent2_materialize_module_handoff.py`,
`run_agent2_derive_boundary_candidates.py`), confirmed by grepping their own `from app.agent2`
import lines. The one genuinely new import, `app.agent2.submodel_materialization
.materialize_submodel`, is declared the sole public entry point of that package by its own
`__init__.py` docstring, and is the *identical function* Agent 2's own hierarchical-search
machinery already calls internally
(`app/agent2/candidate_orchestration/round.py:78`:
`result = materialize_submodel(model, seed_modularization_id, module_id)`). Zero private-
internal reach; Agent 2 needing no changes (§1) was already correct for this reason, not an
oversight.

**Artifact consistency: do boundary review and simulation reference the same composition, and
is everything durably retained?** Yes -- confirmed clean, no code change needed.
`derive_boundary_candidates` and `submit_module_set_simulation` each independently call the
identical `effective_reaction_component_ids(module_set_member)` for a *saved* member, whose
`reaction_component_ids` are immutable post-save (established in earlier increments) -- so
boundary review and the pinned simulation snapshot cannot structurally diverge in which
reactions/modules they describe. `build_resolved_module_ports_payload` is scoped 1:1 to the
member's own review (`get_or_create_review` enforces one review per member at the DB level).
`complete_run` persists `contract_version`/`artifact_reference`/`result_summary`/
`error_summary`/`warnings` as durable `Text`/`String` columns, never in-memory-only state, and
`ModuleExecutionSnapshot` rows are append-only -- never deleted anywhere in this codebase.

**Worker recovery: a safe, tested procedure, even though it stays manual for now.** Closed with
new code. `scripts/module_set_simulation_worker.py` has no lease/heartbeat/timeout -- a worker
killed outright (SIGKILL, crash, machine restart) mid-run leaves that run durably `RUNNING`
forever, nothing left making progress on it (already disclosed, §9 below). Added:

- `_complete_run_unless_already_terminalized(run_id, session, **complete_run_kwargs)` in
  `app/orchestration/module_set_execution_orchestrator.py`, now the single path every
  `process_one_pending_run` completion goes through (all three outcomes: client error,
  succeeded, harness-reported failure). It re-fetches the run's *current* status immediately
  before writing; if something else already terminalized it, it prints a message and returns
  the existing row unchanged instead of calling `complete_run` (which would otherwise raise).
  The shared `complete_run`/`start_run` in `app/persistence/run_record.py`, used by every other
  stage, was deliberately left unmodified -- this race-safety fix is scoped to the module-set
  orchestrator only.
- `scripts/recover_stuck_module_set_runs.py` -- a manual recovery CLI. Dry-run by default (lists
  every module-set-scoped `RUNNING` run older than `--max-age-seconds`, default 900, and writes
  nothing); `--confirm` marks each one `FAILED` with a specific, resubmission-pointing
  `error_summary`, one commit per run. The 900s default is the harness client's own 600s
  subprocess timeout plus a safety margin: a run still `RUNNING` well past that window cannot
  have a live owning worker, since a live worker's own harness call either finishes or
  self-fails within 600s. It **never calls the harness** -- it only flips a `RunRecord`'s status,
  so it can never cause a duplicate execution; the one race this leaves (a worker that was not
  actually dead, finishing mid-flight on a run just force-failed as presumed-crashed) is closed
  by the worker's own side, via `_complete_run_unless_already_terminalized`, discarding that
  late result instead of overwriting recovery's `FAILED`. Every candidate ends up `FAILED`
  with a real, accounted-for reason -- never left `RUNNING` forever, never silently deleted --
  and `FAILED` is no longer an *active* status, so a fresh, legitimate resubmission for the
  same member is unblocked immediately after recovery.
- Test evidence: `tests/orchestration/test_module_set_run_recovery.py`, 6/6 passing (§6).
- **A real bug was found and fixed while writing that test file**, not hypothetical: two bare
  `Session(bind=migrated_engine, ...).execute(...).one()` expressions were never closed,
  leaking idle-in-transaction connections that held a lock on `run_record` and deadlocked a
  *later* test file's own migration-reset `DROP INDEX` during a full-suite run (confirmed via
  `pg_stat_activity`: one backend `idle in transaction` on exactly that leaked `SELECT`, for
  over 100 minutes, blocking another backend's `active` `DROP INDEX` indefinitely). Fixed by
  wrapping both in `with Session(...) as session:`; the single test file dropped from ~5 minutes
  to 3.27s, and the full suite (535 tests) subsequently passed clean in 95.67s.

**Solver settings: already recorded and visible, no code change needed.** Investigated and
confirmed that Agent 3's actual fixed solver configuration (`integrator="cvode"`,
`absolute_tolerance=1e-10`, `relative_tolerance=1e-8`, a `0`-`1000` time horizon, `200` points)
comes entirely from Agent 3's own hardcoded `DEFAULT_SIMULATION_REQUEST`
(`agent3-simulation-diagnostics/app/agent3/pipeline.py`) -- the harness's own `run_agent3.py`
never constructs or passes a custom request at all. Those exact values are already fully
disclosed inside every completed run's own `agent3_report.simulation.request`, rendered verbatim
in the frontend's existing "Agent 3 report:" field (§9 below shows this live). This already
satisfies "fixed solver settings are acceptable provided their actual values are recorded and
visible in run provenance" with zero code changes -- a schema/API/UI change surfacing the
Workbench's own `solver_settings` submission parameter was drafted, then deliberately reverted,
because that field is accepted by `SubmitModuleSetSimulationRequest` and persisted into the
run's pinned `ModuleExecutionSnapshot`, but **never forwarded to the harness/Agent 3 request at
all** -- surfacing it would have shown an always-empty, misleading field rather than the actual
governing configuration. Recorded here as a known no-op, to be wired through in a future
increment if solver configurability is actually implemented.

## 9. Real rendered-browser verification (this session)

§7's own live verification explicitly disclosed driving the same HTTP surface the frontend
calls, not the rendered screen itself, for lack of browser-automation access at the time. This
session installed Playwright as a disposable, uncommitted dev-only tool (outside the repository
entirely, in a scratch directory -- never added as a project dependency) specifically to close
that gap. (Chromium's own install hung during extraction on this machine for unrelated
environment reasons -- worked around by extracting the already-downloaded archives with `ditto`
instead of Playwright's own bundled extractor; an environment detail, not a product finding.)

Re-seeded `workbench_test` with the identical scenario as §7 (`moduleA=[reaction-1, reaction-2]`
edited target) and ran the full stack for real: `uvicorn` (backend), the Vite dev server
(frontend, port 5173), and `scripts/module_set_simulation_worker.py` (background worker), all
against `workbench_test`.

**Happy path, driven entirely through clicks/fills/polling in the actual rendered page (never a
direct HTTP call):**

1. Initial load: boundary review correctly empty/not-ready, "Submit simulation" disabled.
2. "Derive boundary candidates" clicked → a real Harness/Agent 2 call → the same single
   candidate as §7 shown in the rendered table.
3. The port resolved via the real inline decision form (initial value, unit, "Save decision")
   → "Ready to simulate." shown, "Submit simulation" enabled.
4. **Stale review**: a second browser tab, already loaded, submits its own (now-stale) decision
   after the first tab's decision has already advanced the review version -- the UI's own
   stale-conflict message ("changed since it was loaded ... Reloading the current state.")
   appeared and the tab auto-reloaded, exactly as designed.
5. "Submit simulation" clicked; the run appeared in the run list immediately (`PENDING`).
6. **Duplicate submission**: clicking "Submit simulation" again while the run was still active
   surfaced "already has an active simulation run in progress" in the UI -- never silently
   retried.
7. The page's own 3-second polling (no manual reload anywhere in this script) carried the run
   to `Status: Succeeded`, with "Module handoff:", "Lineage:", and "Agent 3 report:" all
   rendered, `Lineage` naming both `reaction-1` and `reaction-2` and never `reaction-3`.
8. Reloading the page showed the identical completed result, unchanged.
9. Opening a brand-new tab afterward showed a byte-identical `completed_at` timestamp to before
   -- proving no rerun on reopen.

**Failure path, driven the same way, against a genuine (non-mocked) infrastructure failure:**
boundary-decision readiness is designed so that reaching "ready to simulate" always guarantees
at least one resolved, standalone-capable port (confirmed by reading `evaluate_readiness`/
`build_resolved_module_ports_payload` -- an empty `module_ports` list can never reach the
harness through the real UI), so a "scientific" Agent 3 failure could not be coaxed through
boundary-decision choices alone within this session's time budget. Instead, the harness
entrypoint script
(`agent-integration-harness/scripts/run_workbench_module_set_simulation_request.py`) was
temporarily renamed aside (restored immediately afterward; confirmed identical by size and
mtime, and that it was already untracked by git before and after) so the real, unmocked
`harness_is_available()` check genuinely fails:

1. Derived and resolved the boundary port as above → ready.
2. Hid the real harness entrypoint.
3. Submitted the simulation through the real rendered UI.
4. The worker's own polling (no manual reload) reached a genuine `Status: Failed`, with a
   clear, specific `error_summary` naming the real cause (`HARNESS_ENTRYPOINT_NOT_FOUND`) --
   never a generic or swallowed message.
5. Restored the harness entrypoint immediately.
6. Refreshing the page showed the identical `Failed` result and `error_summary`, unchanged.
7. Reopening in a brand-new tab showed a byte-identical `completed_at` to before -- no rerun of
   a `FAILED` run either.

Both services and the worker were stopped and `workbench_test` was reset to a clean migration-
history baseline afterward, identically to §7. The real development database (`workbench`) was
never started, connected to, or referenced at any point in this follow-up review either.

## 10. Frontend

No Figma screen exists anywhere for module-scoped boundary review, readiness, or simulation --
confirmed by a full search of file `4tLH4HX0rdgPxjpNB1aJOW` during this increment's own
planning (the closest precedent, "07 — Runs & Results," is a whole-model screen, explicitly out
of scope). `frontend/src/components/ModuleSetMemberExecutionScreen.tsx` is therefore a
from-scratch, functional design, disclosed as such rather than presented as matching a mock that
does not exist -- following this codebase's existing conventions (`createStaleGuard`, hand-rolled
CSS, `RouterLink`, the "Not captured" placeholder) rather than inventing new ones. It shows the
boundary-review table (species/direction structural facts alongside the decision form), a
readiness banner listing every blocking finding, a simulation-submission control (disabled until
ready), and a run list that polls (`ACTIVE_RUN_POLL_INTERVAL_MS = 3000`) any `PENDING`/`RUNNING`
run until it reaches a terminal status, rendering `module_handoff_summary`/`lineage`/
`agent3_report` explicitly labeled as simulation output, never calibration or validation. A new
"Review & simulate" link was added to `ModuleHierarchyTable`'s own per-row controls, wired only
from `ModuleSetVersionScreen` (a saved version) -- never from `ModuleSetDraftScreen`, matching
the backend's own routing-level restriction. New route:
`/projects/:id/studies/:id/module-sets/:id/versions/:n/members/:id/execution`.

Loading/empty/error/conflict states are all handled explicitly: a 404 for an unknown member, a
409 for a stale review (refetches automatically) or an already-active run (shown as an error,
never silently retried), a 422 for not-ready (every blocking finding listed), and ordinary
loading/error states for each independently-fetched piece of data (project, study, version,
review, runs).

## 11. Limitations and unresolved items, stated plainly

- **No solver-setting configurability** is exposed anywhere in the UI, because none exists yet
  in the Agent 3/Harness contract to expose -- Agent 3 always runs its own fixed baseline
  (§8). The Workbench's own `solver_settings` submission parameter is accepted and persisted
  but never forwarded to the harness; wiring it through is future work, not a current gap in
  what is disclosed (§8).
- **Readiness is a structural-sufficiency check, not a scientific-validity check.** A ready
  member can still fail a real Agent 3 run for reasons this increment's own gate cannot see
  (and, per §7 item 7 and §9's happy path, routinely does succeed when it is genuinely ready).
- **Worker crash recovery stays manual, but is now a documented, tested procedure, not an open
  gap.** A `RUNNING` run with no worker left making progress on it still stays `RUNNING` until
  an operator runs `scripts/recover_stuck_module_set_runs.py --confirm` (§8) -- no automatic
  lease/heartbeat/timeout mechanism exists yet -- but that recovery is now race-safe and
  covered by 6 passing tests, never risking a duplicate execution or a permanently misleading
  `RUNNING` state.
- **The known reaction-universe limitation inherited from `docs/23`** still holds identically
  here: validation (and, now, boundary derivation/simulation) is scoped to what a draft/version
  already knows about its own members, never independently verified against some
  ground-truth total reaction count the Workbench does not have.
- **A genuine Agent 3 "scientific" failure (as opposed to an infrastructure failure) was not
  exercised live.** §9's failure-path walkthrough used a real, non-mocked infrastructure
  failure (a missing harness entrypoint) rather than a scientific one, because readiness's own
  design (§8) guarantees at least one resolved port whenever a member is ready, closing off
  the simplest route to an empty-`module_ports` failure through legitimate UI choices alone.
- **No fundamental ambiguity in scientific closure semantics arose.** The one real surprise --
  the missing `module_id` key -- was an integration bug, not an open semantic question, and is
  already fixed, tested, and re-verified live (§7, §9).

## 12. Final repository state

`mechanistic-modeling-workbench`, `agent-integration-harness`, and `agent2-antimony-builder` are
all left **uncommitted**, per explicit instruction. `agent2-antimony-builder` has no diff at all
(confirmed throughout, including during the follow-up closure review, §8). `agent-integration-
harness` carries this increment's new files/edits plus the two pre-existing, harmless
reformatting-only diffs noted in §2; its harness-entrypoint file used for §9's failure-path
verification was confirmed restored byte-identical (size and mtime unchanged) and was already
untracked by git before this session touched it. `mechanistic-modeling-workbench` carries this
increment's migration, models, contracts, persistence, orchestration, harness clients,
background worker, API routes, schemas, frontend screen/routing/CSS, and tests, plus the
targeted `docs/20` corrections in §0 above (its third revision note), plus the follow-up
closure review's race-safety helper, recovery script, and recovery tests (§8).
