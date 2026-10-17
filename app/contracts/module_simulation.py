"""The Workbench <-> Integration Harness module-simulation invocation/result contract
(Executable-Module Materialization increment).

This repository's own, independently-maintained copy of the shape
``agent-integration-harness/app/harness/workbench_contracts.py``'s own
``WorkbenchModuleSimulationRequest``/``WorkbenchModuleSimulationResult`` also define -- never
imported across repositories (see ``docs/01_workbench_architecture.md``). A third, genuinely
separate contract from both ``app.contracts.harness`` (the fixed five-agent ``FULL_PIPELINE``)
and ``app.contracts.hierarchical_recursion`` (the hierarchy search itself): this one names
simulating one already-accepted hierarchy module -- not the whole root model -- through Agent 2
(re-materialize that module's own standalone executable artifact) then Agent 3.
``app.orchestration.model_module_orchestrator`` is what actually constructs and sends a
request and parses/persists a result; nothing in this module performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Must match the harness's own ``WORKBENCH_MODULE_SIMULATION_CONTRACT_VERSION`` exactly, or
#: the canonical entrypoint rejects the request with ``CONTRACT_VERSION_MISMATCH`` before
#: running anything.
CONTRACT_VERSION = "workbench-module-simulation-v1"


@dataclass(frozen=True, slots=True)
class ModuleSimulationRequest:
    """What the Workbench sends to ask the harness to simulate one accepted hierarchy module.

    ``attach_payload`` is this repository's own stored copy of a
    ``HierarchyNodeSummary.attach_payload`` (``app.models.model_module.ModelModule
    .attach_payload``), passed back verbatim -- never reconstructed or edited.
    """

    contract_version: str
    run_id: str
    project_id: str
    subproject_id: str
    attach_payload: dict
    module_id: str
    agent1_organism_id: str | None = None
    input_artifact_references: dict[str, str] = field(default_factory=dict)
    correlation_id: str | None = None
    notes: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleSimulationError:
    """Structured error information for a failed/rejected run."""

    code: str
    message: str
    stage_name: str | None = None


#: Plain string status values (``ModuleSimulationResult.status``) -- intentionally not an
#: ``Enum`` here: this contract only ever constructs/parses them from the harness's own
#: already-validated ``WorkbenchRunStatus.value``, and has no need for a third ``CANCELLED``
#: value the way ``app.contracts.hierarchical_recursion.HierarchicalRunStatus`` does.
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModuleSimulationResult:
    """What the harness reports back for one ``ModuleSimulationRequest``."""

    contract_version: str
    run_id: str
    status: str
    module_id: str | None
    modularization_id: str | None
    module_handoff_summary: dict | None
    #: Agent 3's own full ``Agent3Report`` dict, read verbatim -- never reshaped here.
    agent3_report: dict | None
    started_at: str | None
    completed_at: str | None
    error: ModuleSimulationError | None
    summary: str
    warnings: tuple[str, ...] = ()
    replayed: bool = False


def request_to_dict(request: ModuleSimulationRequest) -> dict:
    """Serialize a ``ModuleSimulationRequest`` to a plain, JSON-ready dict."""
    return {
        "contract_version": request.contract_version,
        "run_id": request.run_id,
        "project_id": request.project_id,
        "subproject_id": request.subproject_id,
        "attach_payload": dict(request.attach_payload),
        "module_id": request.module_id,
        "agent1_organism_id": request.agent1_organism_id,
        "input_artifact_references": dict(request.input_artifact_references),
        "correlation_id": request.correlation_id,
        "notes": request.notes,
        "submitted_at": request.submitted_at,
    }


def result_from_dict(data: dict) -> ModuleSimulationResult:
    """Parse a plain dict (as read from the harness's own output JSON) into a
    ``ModuleSimulationResult``."""
    error_data = data.get("error")
    error = (
        None
        if error_data is None
        else ModuleSimulationError(
            code=error_data["code"],
            message=error_data["message"],
            stage_name=error_data.get("stage_name"),
        )
    )
    return ModuleSimulationResult(
        contract_version=data["contract_version"],
        run_id=data["run_id"],
        status=data["status"],
        module_id=data.get("module_id"),
        modularization_id=data.get("modularization_id"),
        module_handoff_summary=data.get("module_handoff_summary"),
        agent3_report=data.get("agent3_report"),
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
    "ModuleSimulationError",
    "ModuleSimulationRequest",
    "ModuleSimulationResult",
    "request_to_dict",
    "result_from_dict",
]
