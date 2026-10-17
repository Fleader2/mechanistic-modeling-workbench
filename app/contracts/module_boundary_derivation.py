"""The Workbench <-> Integration Harness module-boundary-derivation invocation/result contract
(Boundary-Condition Semantics increment).

This repository's own, independently-maintained copy of the shape
``agent-integration-harness/app/harness/workbench_contracts.py``'s own
``WorkbenchModuleBoundaryDerivationRequest``/``WorkbenchModuleBoundaryDerivationResult`` also
define -- never imported across repositories (see ``docs/01_workbench_architecture.md``).
Mirrors ``app.contracts.module_simulation``'s own identical structure exactly, for a genuinely
separate operation: deriving *candidate* boundary species for one already-accepted hierarchy
module from Agent 2's own reaction-participant topology -- never a treatment decision, never a
simulation. ``app.orchestration.module_boundary_orchestrator`` is what actually constructs and
sends a request and parses/persists a result; nothing in this module performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Must match the harness's own ``WORKBENCH_MODULE_BOUNDARY_DERIVATION_CONTRACT_VERSION``
#: exactly, or the canonical entrypoint rejects the request with ``CONTRACT_VERSION_MISMATCH``
#: before running anything.
CONTRACT_VERSION = "workbench-module-boundary-derivation-v1"


@dataclass(frozen=True, slots=True)
class ModuleBoundaryDerivationRequest:
    """What the Workbench sends to ask the harness to derive candidate boundary species for one
    accepted hierarchy module.

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
class ModuleBoundaryDerivationError:
    """Structured error information for a failed/rejected run."""

    code: str
    message: str
    stage_name: str | None = None


SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModuleBoundaryDerivationResult:
    """What the harness reports back for one ``ModuleBoundaryDerivationRequest``."""

    contract_version: str
    run_id: str
    status: str
    module_id: str | None
    #: ``[{"species_id", "direction"}, ...]`` -- structural candidates only, never a treatment
    #: decision or a fabricated value.
    candidates: tuple[dict, ...]
    started_at: str | None
    completed_at: str | None
    error: ModuleBoundaryDerivationError | None
    summary: str
    warnings: tuple[str, ...] = ()
    replayed: bool = False


def request_to_dict(request: ModuleBoundaryDerivationRequest) -> dict:
    """Serialize a ``ModuleBoundaryDerivationRequest`` to a plain, JSON-ready dict."""
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


def result_from_dict(data: dict) -> ModuleBoundaryDerivationResult:
    """Parse a plain dict (as read from the harness's own output JSON) into a
    ``ModuleBoundaryDerivationResult``."""
    error_data = data.get("error")
    error = (
        None
        if error_data is None
        else ModuleBoundaryDerivationError(
            code=error_data["code"],
            message=error_data["message"],
            stage_name=error_data.get("stage_name"),
        )
    )
    return ModuleBoundaryDerivationResult(
        contract_version=data["contract_version"],
        run_id=data["run_id"],
        status=data["status"],
        module_id=data.get("module_id"),
        candidates=tuple(data.get("candidates", ())),
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
    "ModuleBoundaryDerivationError",
    "ModuleBoundaryDerivationRequest",
    "ModuleBoundaryDerivationResult",
    "request_to_dict",
    "result_from_dict",
]
