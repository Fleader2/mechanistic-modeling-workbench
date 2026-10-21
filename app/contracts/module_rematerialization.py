"""The Workbench <-> Integration Harness module-rematerialization invocation/result contract
(Module-Set Edited-Module Materialization increment).

This repository's own, independently-maintained copy of the shape
``agent-integration-harness/app/harness/workbench_contracts.py``'s own
``WorkbenchModuleRematerializationRequest``/``WorkbenchModuleRematerializationResult`` also
define -- never imported across repositories (see ``docs/01_workbench_architecture.md``).
Names rebuilding one module's own executable content from an explicit, possibly-edited
reaction selection -- never a pre-existing, already-decided ``attach_payload`` (that is
``app.contracts.module_simulation``'s own job, for an unedited module).
``app.orchestration.module_rematerialization_harness_client`` is what actually sends a request
and parses a result; nothing in this module performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Must match the harness's own ``WORKBENCH_MODULE_REMATERIALIZATION_CONTRACT_VERSION``
#: exactly, or the canonical entrypoint rejects the request with ``CONTRACT_VERSION_MISMATCH``
#: before running anything.
CONTRACT_VERSION = "workbench-module-rematerialization-v1"


@dataclass(frozen=True, slots=True)
class ModuleRematerializationRequest:
    """What the Workbench sends to ask the harness to rebuild one module's own executable
    content from an explicit, possibly-edited reaction selection.

    ``attach_payload`` is a synthetic ``{"modularization_id", "module_ids", "memberships"}``
    dict this repository builds fresh from a ``ModuleSetMember``/``ModuleSetDraftMember``'s own
    current ``reaction_component_ids`` -- REACTION-type memberships only, never species/
    parameters/rules/events/observables (the harness's own Agent 2 call derives those
    correctly). ``module_ports``, when given, are the scientist's own resolved boundary
    treatments for this exact selection.
    """

    contract_version: str
    run_id: str
    project_id: str
    subproject_id: str
    attach_payload: dict
    module_id: str
    module_ports: tuple[dict, ...] = ()
    agent1_organism_id: str | None = None
    input_artifact_references: dict[str, str] = field(default_factory=dict)
    correlation_id: str | None = None
    notes: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleRematerializationError:
    """Structured error information for a failed/rejected run."""

    code: str
    message: str
    stage_name: str | None = None


SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModuleRematerializationResult:
    """What the harness reports back for one ``ModuleRematerializationRequest``."""

    contract_version: str
    run_id: str
    status: str
    module_id: str | None
    #: The Agent 2 module-handoff dict -- ``None`` unless ``module_ports`` made the rebuilt
    #: module genuinely executable.
    module_handoff: dict | None
    #: Set only when ``module_handoff`` is ``None`` -- why it isn't executable yet.
    readiness_blocked_reason: str | None
    #: Exact traceability back to the parent model and the real closure this selection
    #: actually produced -- see the harness's own ``WorkbenchModuleRematerializationResult
    #: .lineage`` for the full key list.
    lineage: dict | None
    unresolved_dependencies: tuple[dict, ...] = ()
    started_at: str | None = None
    completed_at: str | None = None
    error: ModuleRematerializationError | None = None
    summary: str = ""
    warnings: tuple[str, ...] = ()
    replayed: bool = False


def request_to_dict(request: ModuleRematerializationRequest) -> dict:
    """Serialize a ``ModuleRematerializationRequest`` to a plain, JSON-ready dict."""
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


def result_from_dict(data: dict) -> ModuleRematerializationResult:
    """Parse a plain dict (as read from the harness's own output JSON) into a
    ``ModuleRematerializationResult``."""
    error_data = data.get("error")
    error = (
        None
        if error_data is None
        else ModuleRematerializationError(
            code=error_data["code"],
            message=error_data["message"],
            stage_name=error_data.get("stage_name"),
        )
    )
    return ModuleRematerializationResult(
        contract_version=data["contract_version"],
        run_id=data["run_id"],
        status=data["status"],
        module_id=data.get("module_id"),
        module_handoff=data.get("module_handoff"),
        readiness_blocked_reason=data.get("readiness_blocked_reason"),
        lineage=data.get("lineage"),
        unresolved_dependencies=tuple(data.get("unresolved_dependencies", ())),
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
    "ModuleRematerializationError",
    "ModuleRematerializationRequest",
    "ModuleRematerializationResult",
    "request_to_dict",
    "result_from_dict",
]
