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
   `result_summary`/`error_summary`);
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

## The disclosed `ModelBuildRequest` -> Agent 2 gap

`model_build_request_id` can be passed through `submit_subproject_run` to
the harness, which records it in the result's own `warnings` but does
**not** act on it: Agent 2 has no mechanism to accept a scoped/partial
build request, so every run currently builds against Agent 1's full
curated knowledge view, unscoped. This increment does **not** invent a
new Agent 2 scientific contract to close that gap -- doing so here would
be exactly the kind of unreviewed scope creep the architecture audit
exists to prevent. Closing it is future work, requiring either an
extension to `Agent1CuratedKnowledgeViewContract` or a new,
explicitly-designed Workbench -> Agent 2 contract (see
`app/contracts/agent2_build_request.py`'s own placeholder shape, which
remains exactly that -- a placeholder, not something any code path
constructs or sends yet).
