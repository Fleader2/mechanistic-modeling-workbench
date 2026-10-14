# Workbench <-> Harness Contract

See `docs/01_workbench_architecture.md` for the repository-boundary
diagram this implements, and
`agent-integration-harness/docs/07_workbench_harness_contract.md` for
that repository's own copy of this document (the two are written
independently, kept in sync by hand -- neither repository imports the
other's Python package).

## Contract types

`app/contracts/harness.py`:

* `HarnessInvocationRequest` -- sent to the harness. `contract_version`,
  `run_id`, `project_id`, `subproject_id`, `task_type`,
  `requested_entry_stage` are required; `model_id`,
  `model_build_request_id`, `agent1_organism_id`,
  `input_artifact_references`, `correlation_id`, `notes`,
  `submitted_at` are optional.
* `HarnessRunResult` -- received back. `run_id`, `status`
  (`SUCCEEDED`/`FAILED`/`CANCELLED`), `stages_executed`,
  `output_artifact_references`, `model_artifact_reference`,
  `agent_contract_versions`, `started_at`, `completed_at`, `error`
  (structured), `summary`, `warnings`, `replayed`, `contract_version`.

`CONTRACT_VERSION` (`"workbench-harness-v1"`) must match the harness's
own `WORKBENCH_HARNESS_CONTRACT_VERSION` exactly, or the harness's
canonical entrypoint rejects the request before invoking any agent. This
is a different version number from any agent's own scientific contract
(`AGENT1_CONTRACT_VERSION`, `agent2-downstream-v1`, ...) -- the Workbench
never enforces or interprets those; that stays the harness's job.

## Canonical execution path

`app.orchestration.run_orchestrator.submit_subproject_run` is the one,
documented entrypoint for running the five-agent workflow from the
Workbench:

1. create (or replay) a `RunRecord`;
2. transition it `PENDING -> RUNNING`
   (`app.persistence.run_record.start_run`);
3. build a `HarnessInvocationRequest`;
4. invoke the harness's own canonical entrypoint
   (`app.orchestration.harness_client.invoke_harness`, a real subprocess
   call to `agent-integration-harness/scripts/run_workbench_request.py`
   in that repository's own venv -- the harness is located as a sibling
   repository under the same parent directory, the identical convention
   the harness itself uses to locate Agents 1-5);
5. parse the `HarnessRunResult`;
6. store `output_artifact_references`/`model_artifact_reference` (as an
   opaque JSON string on `RunRecord.artifact_reference`, and, when a
   `model_id` was supplied and the run succeeded, onto that `Model` row's
   own `artifact_reference`) and metadata (`contract_version`,
   `result_summary`/`error_summary`, and, since the Scoped-Build Support
   increment, `warnings` -- see below);
7. transition to `SUCCEEDED` or `FAILED`
   (`app.persistence.run_record.complete_run`).

The Workbench never imports the harness's Python package, never reaches
into any agent's database, and never re-implements any part of the
harness's own subprocess-orchestration or contract-version-enforcement
logic -- `app.orchestration` only adapts the harness's own existing,
documented CLI contract to `RunRecord`'s own lifecycle.

## Run lifecycle

```text
RunRecord.status:  PENDING -> RUNNING -> SUCCEEDED
                                      \-> FAILED
```

No `CANCELLED` path exists yet -- the harness's own subprocess chain runs
synchronously to completion or failure, with no cancellation mechanism,
so `RunStatus` (and `HarnessRunStatus`) define the value for forward
compatibility only.

**Duplicate/replayed run handling exists at two independent layers:**

* **Workbench layer.** `submit_subproject_run(..., run_record_id=<id>)`,
  when that `RunRecord` is already terminal (`SUCCEEDED`/`FAILED`),
  returns it unchanged without calling the harness at all.
* **Harness layer.** Even a genuinely new Workbench process invoking the
  harness with a `run_id` the harness has already completed gets back the
  identical cached result (`replayed=True`), never a re-execution -- see
  the harness's own documentation.

A `RunRecord` stuck in `RUNNING` (e.g. a crashed prior attempt) is **not**
automatically resumed or retried: calling `submit_subproject_run` again
with that `run_record_id` raises `ValueError`, a deterministic, disclosed
limitation rather than a silent retry. Starting a genuinely new attempt
requires omitting `run_record_id` (a new `RunRecord`, a new `run_id`).

## Artifact ownership and policy

* Every artifact-reference string the Workbench stores is an **opaque
  pointer** -- an absolute filesystem path into the harness's own
  `artifacts/runs/<run_id>/` directory. The Workbench never reads,
  parses, or duplicates the content at that path; it only stores the
  string.
* `RunRecord.artifact_reference` holds a JSON-encoded object:
  `{"model_artifact_reference": ..., "output_artifact_references": {...}}`
  -- the full set the harness reported, not just the one model path, so
  nothing the harness returned is lost even though the column itself is
  a single opaque `TEXT` field.
* `Model.artifact_reference` is updated, in place, only when the caller
  supplied a `model_id` and the run succeeded -- set to exactly
  `HarnessRunResult.model_artifact_reference` (Agent 2's own real output
  file path), never re-derived.
* **Ownership**: the harness repository creates and owns every file an
  artifact reference points at. The Workbench creates and owns nothing in
  that directory.
* **Mutability**: write-once by the harness's own convention; the
  Workbench never writes to or modifies any path it stores.
* **Checksums**: not duplicated here. The harness's own
  `workflow_report.json` (referenced implicitly by convention --
  `<stage_directory>/workflow_report.json`, where `stage_directory` is
  the parent of any `output_artifact_references` value) already carries
  a `sha256` of every stage's input/output file. A caller needing one
  reads that file directly rather than this summary.

## Failure semantics

| Failure | Where detected | `RunRecord` outcome |
|---|---|---|
| Harness repo/venv/entrypoint missing | `harness_client.harness_is_available` | `FAILED`, `error_summary` names the missing path |
| Subprocess fails to start / times out | `harness_client.invoke_harness` | `FAILED`, `error_summary` carries the client error code |
| Subprocess exits without an output file | `harness_client.invoke_harness` | `FAILED`, `HARNESS_OUTPUT_MISSING` |
| Output file is not valid JSON / doesn't match the result shape | `harness_client.invoke_harness` | `FAILED`, `HARNESS_OUTPUT_INVALID` |
| `contract_version` mismatch | harness's own entrypoint (pre-flight) | `FAILED`, harness-reported `CONTRACT_VERSION_MISMATCH` |
| Unsupported `requested_entry_stage` | harness's own entrypoint (pre-flight) | `FAILED`, harness-reported `UNSUPPORTED_ENTRY_STAGE` |
| Missing `stage4_request`/`stage5_request` artifact | harness's own entrypoint (pre-flight) | `FAILED`, harness-reported `MISSING_INPUT_ARTIFACT` |
| An agent stage itself fails | harness's own `run_workflow` | `FAILED`, `error_summary` = the harness's own `sufficiency_note`, naming the failing stage |
| Duplicate/replayed `run_id` | both layers (see above) | the original, cached outcome -- never re-executed |

**No silent retry exists anywhere in this path.** Every failure is
reported once, as data, on the first `RunRecord` the caller asked about;
a caller that wants to try again must explicitly start a new run (a new
`RunRecord`/`run_id`), never something `submit_subproject_run` does on
its own.

## `ModelBuildRequest` -> Agent 2 scoped builds (Scoped-Build Support increment)

`submit_subproject_run(..., model_build_request_id=<id>)` now closes the
gap an earlier increment disclosed. When given:

1. The persisted `ModelBuildRequest` (and its eight child collections) is
   loaded and serialized by
   `app.contracts.agent2_build_request.model_build_request_to_dict` into
   the exact artifact shape Agent 2's own
   `app.agent2.build_request.build_request_from_dict` parses
   (`AGENT2_BUILD_REQUEST_CONTRACT_VERSION`, `"agent2-build-request-v1"`
   -- a contract distinct from, and never confused with, this file's own
   `CONTRACT_VERSION`/`WORKBENCH_HARNESS_CONTRACT_VERSION`).
2. That serialized content is written to a private temporary file and
   added to the harness request's own
   `input_artifact_references["model_build_request"]` -- the harness
   never receives a bare id it would have no way to resolve on its own
   (it has no database access of any kind, including the Workbench's).
   The temp file is removed immediately after the harness invocation
   returns.
3. The harness forwards that file's path to Agent 2's own runner, which
   restricts its assembled network to the request's scope and reports
   any resulting warning (an unresolved reference, a contradictory
   constraint rejected outright, an unsupported pathway constraint, ...)
   back through the harness's own `WorkbenchRunResult.warnings`.
4. `RunRecord.model_build_request_id`/`RunRecord.warnings` (migration
   `0002_run_record_build_request`) persist, respectively, which request
   scoped the run and that warning list (JSON-encoded, opaque to the
   Workbench -- never parsed or interpreted here, exactly like
   `artifact_reference`).

**What the Workbench still never does:** copy Agent 2's executable model
content into its own database, interpret a `ModelBuildRequest`'s own
scoping semantics, or decide what counts as a contradictory constraint --
all of that logic lives in `agent2-antimony-builder/app/agent2
/build_request`, not here. Omitting `model_build_request_id` reproduces
every pre-existing run's exact behavior with no change whatsoever.
