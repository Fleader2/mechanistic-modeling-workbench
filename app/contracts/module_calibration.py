"""The Workbench <-> Integration Harness module-calibration invocation/result contract
(Module-Level Agent4 Calibration with Immutable Execution-Condition Provenance increment).

This repository's own, independently-maintained copy of the shape
``agent-integration-harness/app/harness/workbench_contracts.py``'s own
``WorkbenchModuleCalibrationRequest``/``WorkbenchModuleCalibrationResult`` also define -- never
imported across repositories (see ``docs/01_workbench_architecture.md``). Mirrors
``app.contracts.module_simulation``'s own identical structure exactly, for a genuinely separate
operation: calibrating one already-accepted hierarchy module's own standalone executable
artifact through Agent 2, Agent 3, then Agent 4 against Workbench-supplied experimental data --
never the whole root model. ``app.orchestration.module_calibration_orchestrator`` is what
actually constructs and sends a request and parses/persists a result; nothing in this module
performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Must match the harness's own ``WORKBENCH_MODULE_CALIBRATION_CONTRACT_VERSION`` exactly, or
#: the canonical entrypoint rejects the request with ``CONTRACT_VERSION_MISMATCH`` before
#: running anything.
CONTRACT_VERSION = "workbench-module-calibration-v1"


@dataclass(frozen=True, slots=True)
class ModuleCalibrationRequest:
    """What the Workbench sends to ask the harness to calibrate one accepted hierarchy module.

    ``attach_payload`` is this repository's own stored copy of a
    ``HierarchyNodeSummary.attach_payload``, with the module's own resolved boundary ports
    already merged in as ``module_ports`` -- passed back verbatim, never reconstructed or
    edited. ``calibration_request`` is Agent 4's own ``CalibrationRequest`` dict shape
    (``targets``/``observations``/``optimizer``/...), built and validated by
    ``app.orchestration.module_calibration_orchestrator`` before this request is ever sent.
    """

    contract_version: str
    run_id: str
    project_id: str
    subproject_id: str
    attach_payload: dict
    module_id: str
    calibration_request: dict
    agent1_organism_id: str | None = None
    input_artifact_references: dict[str, str] = field(default_factory=dict)
    correlation_id: str | None = None
    notes: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleCalibrationError:
    """Structured error information for a failed/rejected run."""

    code: str
    message: str
    stage_name: str | None = None


#: Plain string status values (``ModuleCalibrationResult.status``) -- intentionally not an
#: ``Enum``, matching ``app.contracts.module_simulation``'s own identical choice: this contract
#: only ever constructs/parses them from the harness's own already-validated
#: ``WorkbenchRunStatus.value``.
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModuleCalibrationResult:
    """What the harness reports back for one ``ModuleCalibrationRequest``."""

    contract_version: str
    run_id: str
    status: str
    module_id: str | None
    modularization_id: str | None
    #: The full, materialized Agent2->Agent3 handoff dict -- never a bare summary; the
    #: immutable execution snapshot needs real parameter/initial-condition fidelity.
    module_handoff: dict | None
    #: Agent 3's own full ``Agent3Report`` dict, read verbatim.
    agent3_report: dict | None
    #: Agent 4's own full ``Agent4Report`` dict, read verbatim -- never compressed.
    agent4_report: dict | None
    started_at: str | None
    completed_at: str | None
    error: ModuleCalibrationError | None
    summary: str
    warnings: tuple[str, ...] = ()
    replayed: bool = False


def request_to_dict(request: ModuleCalibrationRequest) -> dict:
    """Serialize a ``ModuleCalibrationRequest`` to a plain, JSON-ready dict."""
    return {
        "contract_version": request.contract_version,
        "run_id": request.run_id,
        "project_id": request.project_id,
        "subproject_id": request.subproject_id,
        "attach_payload": dict(request.attach_payload),
        "module_id": request.module_id,
        "calibration_request": dict(request.calibration_request),
        "agent1_organism_id": request.agent1_organism_id,
        "input_artifact_references": dict(request.input_artifact_references),
        "correlation_id": request.correlation_id,
        "notes": request.notes,
        "submitted_at": request.submitted_at,
    }


def result_from_dict(data: dict) -> ModuleCalibrationResult:
    """Parse a plain dict (as read from the harness's own output JSON) into a
    ``ModuleCalibrationResult``."""
    error_data = data.get("error")
    error = (
        None
        if error_data is None
        else ModuleCalibrationError(
            code=error_data["code"],
            message=error_data["message"],
            stage_name=error_data.get("stage_name"),
        )
    )
    return ModuleCalibrationResult(
        contract_version=data["contract_version"],
        run_id=data["run_id"],
        status=data["status"],
        module_id=data.get("module_id"),
        modularization_id=data.get("modularization_id"),
        module_handoff=data.get("module_handoff"),
        agent3_report=data.get("agent3_report"),
        agent4_report=data.get("agent4_report"),
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
    "ModuleCalibrationError",
    "ModuleCalibrationRequest",
    "ModuleCalibrationResult",
    "request_to_dict",
    "result_from_dict",
]
