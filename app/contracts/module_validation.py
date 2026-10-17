"""The Workbench <-> Integration Harness module-validation invocation/result contract
(Module-Level Agent5 Validation and Experimental Design increment).

This repository's own, independently-maintained copy of the shape
``agent-integration-harness/app/harness/workbench_contracts.py``'s own
``WorkbenchModuleValidationRequest``/``WorkbenchModuleValidationResult`` also define -- never
imported across repositories (see ``docs/01_workbench_architecture.md``). Mirrors
``app.contracts.module_calibration``'s own identical structure exactly, for a genuinely
separate operation: validating one already-calibrated hierarchy module's own frozen parameter
estimates against independent held-out experimental data through Agent 2 then Agent 5 -- never
Agent 3/Agent 4 (a prior, already-succeeded calibration's own report is reused, never
recomputed), never the whole root model.
``app.orchestration.module_validation_orchestrator`` is what actually constructs and sends a
request and parses/persists a result; nothing in this module performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Must match the harness's own ``WORKBENCH_MODULE_VALIDATION_CONTRACT_VERSION`` exactly, or
#: the canonical entrypoint rejects the request with ``CONTRACT_VERSION_MISMATCH`` before
#: running anything.
CONTRACT_VERSION = "workbench-module-validation-v1"


@dataclass(frozen=True, slots=True)
class ModuleValidationRequest:
    """What the Workbench sends to ask the harness to validate one already-calibrated
    hierarchy module.

    ``attach_payload`` is this repository's own stored copy of a
    ``HierarchyNodeSummary.attach_payload``, with the module's own resolved boundary ports
    already merged in as ``module_ports`` -- passed back verbatim, never reconstructed or
    edited. ``agent4_report`` is the full, verbatim report dict a prior, already-succeeded
    module-calibration ``RunRecord`` produced -- Agent 3/Agent 4 are never re-invoked by this
    request. ``validation_request`` is Agent 5's own ``ValidationRequest`` dict shape
    (``request_id``/``validation_observations``/``candidate_experiments``/...), built and
    validated by ``app.orchestration.module_validation_orchestrator`` before this request is
    ever sent.
    """

    contract_version: str
    run_id: str
    project_id: str
    subproject_id: str
    attach_payload: dict
    module_id: str
    agent4_report: dict
    validation_request: dict
    agent1_organism_id: str | None = None
    input_artifact_references: dict[str, str] = field(default_factory=dict)
    correlation_id: str | None = None
    notes: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleValidationError:
    """Structured error information for a failed/rejected run."""

    code: str
    message: str
    stage_name: str | None = None


#: Plain string status values (``ModuleValidationResult.status``) -- intentionally not an
#: ``Enum``, matching ``app.contracts.module_calibration``'s own identical choice.
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModuleValidationResult:
    """What the harness reports back for one ``ModuleValidationRequest``."""

    contract_version: str
    run_id: str
    status: str
    module_id: str | None
    modularization_id: str | None
    #: The full, materialized Agent2->Agent3 handoff dict -- never a bare summary.
    module_handoff: dict | None
    #: Agent 5's own full ``Agent5Report`` dict, read verbatim -- never compressed.
    agent5_report: dict | None
    started_at: str | None
    completed_at: str | None
    error: ModuleValidationError | None
    summary: str
    warnings: tuple[str, ...] = ()
    replayed: bool = False


def request_to_dict(request: ModuleValidationRequest) -> dict:
    """Serialize a ``ModuleValidationRequest`` to a plain, JSON-ready dict."""
    return {
        "contract_version": request.contract_version,
        "run_id": request.run_id,
        "project_id": request.project_id,
        "subproject_id": request.subproject_id,
        "attach_payload": dict(request.attach_payload),
        "module_id": request.module_id,
        "agent4_report": dict(request.agent4_report),
        "validation_request": dict(request.validation_request),
        "agent1_organism_id": request.agent1_organism_id,
        "input_artifact_references": dict(request.input_artifact_references),
        "correlation_id": request.correlation_id,
        "notes": request.notes,
        "submitted_at": request.submitted_at,
    }


def result_from_dict(data: dict) -> ModuleValidationResult:
    """Parse a plain dict (as read from the harness's own output JSON) into a
    ``ModuleValidationResult``."""
    error_data = data.get("error")
    error = (
        None
        if error_data is None
        else ModuleValidationError(
            code=error_data["code"],
            message=error_data["message"],
            stage_name=error_data.get("stage_name"),
        )
    )
    return ModuleValidationResult(
        contract_version=data["contract_version"],
        run_id=data["run_id"],
        status=data["status"],
        module_id=data.get("module_id"),
        modularization_id=data.get("modularization_id"),
        module_handoff=data.get("module_handoff"),
        agent5_report=data.get("agent5_report"),
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        error=error,
        summary=data.get("summary", ""),
        warnings=tuple(data.get("warnings", ())),
        replayed=bool(data.get("replayed", False)),
    )


__all__ = [
    "CONTRACT_VERSION",
    "FAILED",
    "SUCCEEDED",
    "ModuleValidationError",
    "ModuleValidationRequest",
    "ModuleValidationResult",
    "request_to_dict",
    "result_from_dict",
]
