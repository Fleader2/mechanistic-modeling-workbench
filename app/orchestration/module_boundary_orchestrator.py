"""Boundary-Condition Semantics: the service layer a caller uses to derive candidate boundary
ports for an accepted hierarchy module, record/inspect human treatment decisions, evaluate a
module's own execution readiness, and build the resolved ``module_ports`` payload Agent 2's
materialization path consumes.

No scientific logic lives here: Agent 2's own reaction-participant topology is what actually
decides which species are boundary candidates (via the harness); a human (or, in a future
increment, Agent4/5) decision is what actually decides a candidate's own treatment. This module
only routes to the harness, persists idempotently (``app.persistence.module_boundary_port``),
and evaluates one small, pure, explicitly-documented execution-readiness rule.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.module_boundary_derivation import (
    CONTRACT_VERSION,
    ModuleBoundaryDerivationRequest,
)
from app.models.enums import ModelModuleExecutionStatus, ModuleBoundaryTreatmentType
from app.models.model_module import ModelModule
from app.models.module_boundary_port import ModuleBoundaryPort
from app.orchestration.module_boundary_derivation_harness_client import (
    invoke_module_boundary_derivation,
)
from app.persistence.model_module import build_attach_payload, get_model_module
from app.persistence.module_boundary_port import (
    get_boundary_port,
    list_boundary_ports_for_module,
    persist_candidate_boundary_ports,
)
from app.persistence.module_boundary_port import (
    submit_boundary_decision as _persist_submit_boundary_decision,
)
from app.persistence.run_record import get_run_record, resolve_stage1_inputs

#: Treatment types that let Agent 2 build this module as a standalone executable artifact --
#: the one mapping to ``ModulePort.externally_controlled=True`` the harness's own
#: ``run_agent2_materialize_module_handoff.py`` already consumes. Never ``DYNAMIC_COUPLING``/
#: ``UNRESOLVED``: Agent 2 itself never fabricates a boundary condition, so a module leaning on
#: either of those stays genuinely non-standalone.
_STANDALONE_CAPABLE_TREATMENTS = (
    ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
    ModuleBoundaryTreatmentType.PRESCRIBED_INPUT,
)


class ModuleBoundaryDerivationError(ValueError):
    """Raised when the harness could not be reached or itself reported failure deriving
    boundary candidates for a module -- never for an empty candidate list (a module with no
    cross-boundary species is a genuine, disclosed outcome, not an error)."""


def evaluate_module_execution_status(
    model_module: ModelModule, session: Session
) -> ModelModuleExecutionStatus:
    """Recompute, persist, and return one ``ModelModule``'s own execution status from its
    current ``ModuleBoundaryPort`` rows.

    Pure, explicit rule (task instructions §6): ``VIEW_ONLY`` if no boundary ports exist yet;
    else ``SIMULATION_READY`` if every port is resolved to a standalone-capable treatment
    (``EXTERNALLY_CONTROLLED``/``PRESCRIBED_INPUT``); else ``REQUIRES_BOUNDARY_REVIEW`` (at
    least one port is still ``UNRESOLVED`` or resolved to the non-standalone
    ``DYNAMIC_COUPLING``). Always re-derived from the ports actually on file, never cached
    stale -- calling this after every derive/decide keeps ``model_module.execution_status``
    truthful without a separate invalidation mechanism.
    """
    ports = list_boundary_ports_for_module(session, model_module.id)
    if not ports:
        status = ModelModuleExecutionStatus.VIEW_ONLY
    elif all(p.treatment_type in _STANDALONE_CAPABLE_TREATMENTS for p in ports):
        status = ModelModuleExecutionStatus.SIMULATION_READY
    else:
        status = ModelModuleExecutionStatus.REQUIRES_BOUNDARY_REVIEW

    model_module.execution_status = status
    session.flush()
    return status


def derive_boundary_ports(
    *,
    model_module_id: UUID,
    project_id: UUID,
    subproject_id: UUID,
    session: Session,
    correlation_id: str | None = None,
) -> list[ModuleBoundaryPort]:
    """Ask the harness to derive candidate boundary species for one accepted hierarchy module
    from Agent 2's own reaction-participant topology, persist the newly-found candidates
    idempotently, and re-evaluate the module's own execution status.

    Returns only the newly-created ``ModuleBoundaryPort`` rows (``persist_candidate_boundary
    _ports``'s own established return convention) -- an already-known candidate (automatic or
    manually-decided) is never touched, satisfying idempotent re-derivation (task instructions
    §10). Raises ``ModuleBoundaryDerivationError`` if the harness itself could not be reached or
    reported a genuine failure -- never for a module with zero cross-boundary species (an empty
    list is a valid, successful result).
    """
    module = get_model_module(session, model_module_id)
    if module is None:
        raise ValueError(f"no ModelModule with id {model_module_id}")

    source_run_record = get_run_record(session, module.run_record_id)
    assert source_run_record is not None
    agent1_organism_id, stage1_synthetic_source = resolve_stage1_inputs(source_run_record)

    input_artifact_references: dict[str, str] = {}
    if stage1_synthetic_source is not None:
        input_artifact_references["stage1_synthetic_source"] = stage1_synthetic_source

    request = ModuleBoundaryDerivationRequest(
        contract_version=CONTRACT_VERSION,
        run_id=f"boundary-derivation::{model_module_id}::{datetime.now(UTC).timestamp():.6f}",
        project_id=str(project_id),
        subproject_id=str(subproject_id),
        attach_payload=build_attach_payload(module),
        module_id=module.module_id,
        agent1_organism_id=agent1_organism_id,
        input_artifact_references=input_artifact_references,
        correlation_id=correlation_id,
        submitted_at=datetime.now(UTC).isoformat(),
    )

    result, client_error = invoke_module_boundary_derivation(request)
    if client_error is not None:
        raise ModuleBoundaryDerivationError(
            f"could not reach the harness for boundary derivation: "
            f"{client_error.code}: {client_error.message}"
        )
    assert result is not None  # invoke_module_boundary_derivation's own contract
    if result.status != "SUCCEEDED":
        message = result.summary if result.error is None else result.error.message
        raise ModuleBoundaryDerivationError(f"boundary derivation failed: {message}")

    created = persist_candidate_boundary_ports(
        model_module_id=model_module_id, candidates=list(result.candidates), session=session
    )
    evaluate_module_execution_status(module, session)
    return created


def submit_boundary_decision(
    *,
    port_id: UUID,
    treatment_type: ModuleBoundaryTreatmentType,
    session: Session,
    initial_value: Decimal | str | None = None,
    unit: str | None = None,
    value_source: str | None = None,
    decided_by: str | None = None,
    notes: str | None = None,
) -> ModuleBoundaryPort:
    """Record one human treatment decision for a boundary port, then re-evaluate that port's
    own module's execution status.

    A thin orchestration wrapper around ``app.persistence.module_boundary_port
    .submit_boundary_decision`` -- validation/raising behavior is entirely that function's own
    (unknown port, ``UNRESOLVED`` target, mismatched ``initial_value``). This wrapper's only
    added responsibility is keeping ``ModelModule.execution_status`` truthful immediately after
    the decision, so a caller never has to remember to call ``evaluate_module_execution_status``
    separately.
    """
    port = _persist_submit_boundary_decision(
        port_id=port_id,
        treatment_type=treatment_type,
        session=session,
        initial_value=initial_value,
        unit=unit,
        value_source=value_source,
        decided_by=decided_by,
        notes=notes,
    )
    module = session.get(ModelModule, port.model_module_id)
    assert module is not None  # the port's own FK guarantees this
    evaluate_module_execution_status(module, session)
    return port


def list_boundary_ports(session: Session, model_module_id: UUID) -> list[ModuleBoundaryPort]:
    """Every ``ModuleBoundaryPort`` for one module. Read-only."""
    return list_boundary_ports_for_module(session, model_module_id)


def get_boundary_port_with_provenance(session: Session, port_id: UUID) -> ModuleBoundaryPort:
    """One ``ModuleBoundaryPort`` row, with its own provenance fields
    (``provenance_notes``/``decided_by``/``decided_at``/``derived_automatically``) already
    present as plain columns -- no separate assembly step. Raises ``ValueError`` if it does not
    exist."""
    port = get_boundary_port(session, port_id)
    if port is None:
        raise ValueError(f"no ModuleBoundaryPort with id {port_id}")
    return port


def build_module_ports_payload(model_module: ModelModule, session: Session) -> list[dict]:
    """The ``module_ports`` list to merge into an ``attach_payload`` sent to the harness's
    module-simulation entrypoint -- the exact shape
    ``run_agent2_materialize_module_handoff.py`` already parses
    (``{"port_id", "module_id", "species_id", "direction", "externally_controlled",
    "initial_value", "unit"}``).

    Only a resolved, standalone-capable port (``EXTERNALLY_CONTROLLED``/``PRESCRIBED_INPUT``)
    is ever included with ``externally_controlled=True`` -- a ``DYNAMIC_COUPLING``/
    ``UNRESOLVED`` port is omitted entirely rather than included as a non-controlling entry,
    since Agent 2 has no use for a boundary port it is not told to treat as a fixed/prescribed
    value. Called only for a ``SIMULATION_READY`` module (see
    ``app.orchestration.model_module_orchestrator.request_module_simulation``'s own gate), so
    in practice every port on file is already standalone-capable -- this filter is still
    applied explicitly rather than assumed, so the function's own contract holds even if called
    earlier.
    """
    ports = list_boundary_ports_for_module(session, model_module.id)
    return [
        {
            "port_id": port.port_id,
            "module_id": model_module.module_id,
            "species_id": port.species_id,
            "direction": port.direction.value,
            "externally_controlled": True,
            "initial_value": (str(port.initial_value) if port.initial_value is not None else None),
            "unit": port.unit,
        }
        for port in ports
        if port.treatment_type in _STANDALONE_CAPABLE_TREATMENTS
    ]


__all__ = [
    "ModuleBoundaryDerivationError",
    "build_module_ports_payload",
    "derive_boundary_ports",
    "evaluate_module_execution_status",
    "get_boundary_port_with_provenance",
    "list_boundary_ports",
    "submit_boundary_decision",
]
