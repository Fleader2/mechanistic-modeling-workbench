"""The Workbench <-> Integration Harness module-set-simulation invocation/result contract
(Module-Set Edited-Module Materialization increment, Phase B).

This repository's own, independently-maintained copy of the shape
``agent-integration-harness/app/harness/workbench_contracts.py``'s own
``WorkbenchModuleSetSimulationRequest``/``WorkbenchModuleSetSimulationResult`` also define --
never imported across repositories. Names simulating a module-set member's own current,
possibly-edited reaction selection -- correct rebuild through the identical mechanism
``app.contracts.module_rematerialization`` uses, then unchanged Agent 3.
``app.orchestration.module_set_simulation_harness_client`` is what actually sends a request
and parses a result; nothing in this module performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Must match the harness's own ``WORKBENCH_MODULE_SET_SIMULATION_CONTRACT_VERSION`` exactly.
CONTRACT_VERSION = "workbench-module-set-simulation-v1"


@dataclass(frozen=True, slots=True)
class ModuleSetSimulationRequest:
    """What the Workbench sends to ask the harness to simulate one module-set member's own
    current, possibly-edited reaction selection. ``module_ports`` is required here (never
    optional, unlike the rematerialization contract's own structure-only mode): this
    contract's entire purpose is producing a real Agent 3 simulation.
    """

    contract_version: str
    run_id: str
    project_id: str
    subproject_id: str
    attach_payload: dict
    module_id: str
    module_ports: tuple[dict, ...]
    agent1_organism_id: str | None = None
    input_artifact_references: dict[str, str] = field(default_factory=dict)
    correlation_id: str | None = None
    notes: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleSetSimulationError:
    """Structured error information for a failed/rejected run."""

    code: str
    message: str
    stage_name: str | None = None


SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModuleSetSimulationResult:
    """What the harness reports back for one ``ModuleSetSimulationRequest``."""

    contract_version: str
    run_id: str
    status: str
    module_id: str | None
    module_handoff_summary: dict | None
    lineage: dict | None
    #: Agent 3's own full ``Agent3Report`` dict, read verbatim -- never reshaped here.
    agent3_report: dict | None
    started_at: str | None
    completed_at: str | None
    error: ModuleSetSimulationError | None
    summary: str
    warnings: tuple[str, ...] = ()
    replayed: bool = False


def request_to_dict(request: ModuleSetSimulationRequest) -> dict:
    """Serialize a ``ModuleSetSimulationRequest`` to a plain, JSON-ready dict."""
    return {
        "contract_version": request.contract_version,
        "run_id": request.run_id,
        "project_id": request.project_id,
        "subproject_id": request.subproject_id,
        "attach_payload": dict(request.attach_payload),
        "module_id": request.module_id,
        "module_ports": list(request.module_ports),
        "agent1_organism_id": request.agent1_organism_id,
        "input_artifact_references": dict(request.input_artifact_references),
        "correlation_id": request.correlation_id,
        "notes": request.notes,
        "submitted_at": request.submitted_at,
    }


def result_from_dict(data: dict) -> ModuleSetSimulationResult:
    """Parse a plain dict (as read from the harness's own output JSON) into a
    ``ModuleSetSimulationResult``."""
    error_data = data.get("error")
    error = (
        None
        if error_data is None
        else ModuleSetSimulationError(
            code=error_data["code"],
            message=error_data["message"],
            stage_name=error_data.get("stage_name"),
        )
    )
    return ModuleSetSimulationResult(
        contract_version=data["contract_version"],
        run_id=data["run_id"],
        status=data["status"],
        module_id=data.get("module_id"),
        module_handoff_summary=data.get("module_handoff_summary"),
        lineage=data.get("lineage"),
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
    "ModuleSetSimulationError",
    "ModuleSetSimulationRequest",
    "ModuleSetSimulationResult",
    "request_to_dict",
    "result_from_dict",
]
