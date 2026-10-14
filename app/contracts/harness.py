"""The Workbench <-> Integration Harness invocation/result contract.

This is the Workbench's own, independently-maintained copy of the shape
``agent-integration-harness/app/harness/workbench_contracts.py`` also
defines. The two are never imported across repositories -- see
``docs/01_workbench_architecture.md`` -- so this module's own
``CONTRACT_VERSION`` is what keeps the two in sync; a mismatch is
detected by the harness's own canonical entrypoint
(``scripts/run_workbench_request.py``) and reported back as a structured
``FAILED`` result, never silently accepted.

See ``docs/03_workbench_harness_contract.md`` for the full design
rationale, the canonical entrypoint's execution semantics, the disclosed
``ModelBuildRequest`` -> Agent 2 gap, and the artifact-reference policy.
``app.orchestration.run_orchestrator`` is what actually constructs and
sends a ``HarnessInvocationRequest`` and parses a ``HarnessRunResult`` --
nothing in this module performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

#: Must match ``agent-integration-harness``'s own
#: ``WORKBENCH_HARNESS_CONTRACT_VERSION`` exactly, or the canonical
#: entrypoint rejects the request with ``CONTRACT_VERSION_MISMATCH``
#: before invoking any agent.
CONTRACT_VERSION = "workbench-harness-v1"

#: The only ``requested_entry_stage`` the harness's canonical entrypoint
#: currently implements -- there is no partial/entry-stage execution mode
#: anywhere in the harness today. See the harness's own
#: ``workbench_contracts.SUPPORTED_ENTRY_STAGE`` module docstring.
SUPPORTED_ENTRY_STAGE = "FULL_PIPELINE"


class HarnessRunStatus(StrEnum):
    """The outcome of one Workbench-invoked harness run."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    #: Defined for forward compatibility; never produced by the current
    #: harness canonical entrypoint (no cancellation mechanism exists).
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class HarnessInvocationRequest:
    """What the Workbench sends to ask the harness to run the five-agent
    workflow for one subproject.

    ``input_artifact_references`` is a plain ``{name: path}`` mapping the
    harness's own canonical entrypoint reads directly from disk -- never a
    new scientific contract invented here. Recognized keys:
    ``"stage4_request"``/``"stage5_request"`` (required -- Agent 4's/Agent
    5's own request JSON, produced by the caller or a human, never by the
    Workbench itself), and ``"stage1_synthetic_source"`` (test/dev only).

    ``model_build_request_id``, when supplied, is accepted and recorded by
    the harness but **not yet acted on** -- Agent 2 has no mechanism to
    consume a scoped build request yet. This is a disclosed gap, not a
    silent no-op; see ``docs/03_workbench_harness_contract.md``.
    """

    contract_version: str
    run_id: str
    project_id: str
    subproject_id: str
    task_type: str
    requested_entry_stage: str
    model_id: str | None = None
    model_build_request_id: str | None = None
    agent1_organism_id: str | None = None
    input_artifact_references: dict[str, str] = field(default_factory=dict)
    correlation_id: str | None = None
    notes: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True, slots=True)
class HarnessRunError:
    """Structured error information for a failed/rejected run."""

    code: str
    message: str
    stage_name: str | None = None


@dataclass(frozen=True, slots=True)
class HarnessRunResult:
    """What the harness reports back for one ``HarnessInvocationRequest``.

    Maps directly onto ``app.persistence.run_record.complete_run``'s own
    keyword arguments -- ``app.orchestration.run_orchestrator`` is the one
    place that performs that mapping.
    """

    contract_version: str
    run_id: str
    status: HarnessRunStatus
    stages_executed: tuple[str, ...]
    output_artifact_references: dict[str, str]
    model_artifact_reference: str | None
    agent_contract_versions: dict[str, str | None]
    started_at: str | None
    completed_at: str | None
    error: HarnessRunError | None
    summary: str
    warnings: tuple[str, ...] = ()
    replayed: bool = False


def request_to_dict(request: HarnessInvocationRequest) -> dict:
    """Serialize a ``HarnessInvocationRequest`` to a plain, JSON-ready dict."""
    return {
        "contract_version": request.contract_version,
        "run_id": request.run_id,
        "project_id": request.project_id,
        "subproject_id": request.subproject_id,
        "task_type": request.task_type,
        "requested_entry_stage": request.requested_entry_stage,
        "model_id": request.model_id,
        "model_build_request_id": request.model_build_request_id,
        "agent1_organism_id": request.agent1_organism_id,
        "input_artifact_references": dict(request.input_artifact_references),
        "correlation_id": request.correlation_id,
        "notes": request.notes,
        "submitted_at": request.submitted_at,
    }


def result_from_dict(data: dict) -> HarnessRunResult:
    """Parse a plain dict (as read from the harness's own output JSON) into
    a ``HarnessRunResult``.
    """
    error_data = data.get("error")
    error = (
        None
        if error_data is None
        else HarnessRunError(
            code=error_data["code"],
            message=error_data["message"],
            stage_name=error_data.get("stage_name"),
        )
    )
    return HarnessRunResult(
        contract_version=data["contract_version"],
        run_id=data["run_id"],
        status=HarnessRunStatus(data["status"]),
        stages_executed=tuple(data.get("stages_executed", ())),
        output_artifact_references=dict(data.get("output_artifact_references") or {}),
        model_artifact_reference=data.get("model_artifact_reference"),
        agent_contract_versions=dict(data.get("agent_contract_versions") or {}),
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        error=error,
        summary=data.get("summary", ""),
        warnings=tuple(data.get("warnings", ())),
        replayed=bool(data.get("replayed", False)),
    )


__all__ = [
    "CONTRACT_VERSION",
    "SUPPORTED_ENTRY_STAGE",
    "HarnessInvocationRequest",
    "HarnessRunError",
    "HarnessRunResult",
    "HarnessRunStatus",
    "request_to_dict",
    "result_from_dict",
]
