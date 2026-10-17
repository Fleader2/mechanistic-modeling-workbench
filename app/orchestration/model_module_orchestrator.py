"""Executable-Module Materialization: the service layer a caller uses to list/inspect accepted
hierarchy modules and request an Agent 3 simulation for a selected one.

No scientific logic lives here: Agent 3's own simulation outcome is read verbatim from the
harness's own report. This module only resolves a module's own stored provenance into a
request, moves a ``RunRecord`` through its own existing, unchanged state machine
(``app.persistence.run_record``), and records the result.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.module_simulation import (
    CONTRACT_VERSION,
    ModuleSimulationRequest,
)
from app.models.enums import ModelModuleExecutionStatus, RunStage, RunStatus
from app.models.model_module import ModelModule
from app.models.run_record import RunRecord
from app.orchestration.module_boundary_orchestrator import build_module_ports_payload
from app.orchestration.module_simulation_harness_client import invoke_module_simulation
from app.persistence.model_module import (
    build_attach_payload,
    get_model_module,
    list_model_modules_for_run,
)
from app.persistence.run_record import (
    complete_run,
    create_run_record,
    get_run_record,
    resolve_stage1_inputs,
    start_run,
)


def list_model_modules(session: Session, run_record_id: UUID) -> list[ModelModule]:
    """Every ``ModelModule`` for one hierarchy run. Read-only."""
    return list_model_modules_for_run(session, run_record_id)


def get_model_module_with_provenance(session: Session, model_module_id: UUID) -> ModelModule:
    """One ``ModelModule`` row, with its own provenance reachable via ordinary relationship
    attributes (``.hierarchy_node``, ``.parent_model_module``, ``.root_model``, ``.run_record``)
    -- no separate assembly step; the schema already carries full provenance as columns/FKs.
    Raises ``ValueError`` if it does not exist."""
    module = get_model_module(session, model_module_id)
    if module is None:
        raise ValueError(f"no ModelModule with id {model_module_id}")
    return module


def request_module_simulation(
    *,
    model_module_id: UUID,
    subproject_id: UUID,
    project_id: UUID,
    session: Session,
    correlation_id: str | None = None,
    notes: str | None = None,
    run_record_id: UUID | None = None,
) -> RunRecord:
    """Request a real Agent 3 simulation of one accepted hierarchy module's own standalone
    executable artifact (reusing the harness's own module-simulation canonical entrypoint --
    never a whole-model Agent 3 run, and never Agent 2/Agent 3's own logic duplicated here).

    **Duplicate/replayed run handling**, identical to ``submit_hierarchical_run``'s own: when
    ``run_record_id`` names an existing, already-terminal ``RunRecord``, that row is returned
    unchanged -- the harness is never invoked again. Omit ``run_record_id`` to always start a
    genuinely new simulation run.

    Recorded as ``RunStage.AGENT3`` with ``model_module_id`` set -- distinguishing this from an
    ordinary whole-model Agent 3 run inside ``FULL_PIPELINE`` (which never sets that field).

    **Boundary-Condition Semantics increment: gated on execution readiness.** Raises
    ``ValueError`` unless ``module.execution_status`` is already ``SIMULATION_READY`` (every
    boundary port resolved to a treatment that lets Agent 2 build a standalone artifact) --
    ``VIEW_ONLY``/``REQUIRES_BOUNDARY_REVIEW`` modules never reach the harness at all, never a
    silent attempt that Agent 2 would have rejected anyway. The module's own resolved
    ``ModuleBoundaryPort`` rows are merged into the ``attach_payload`` sent to the harness as
    ``module_ports`` (``app.orchestration.module_boundary_orchestrator
    .build_module_ports_payload``) -- the stored ``ModelModule.attach_payload`` column itself
    is never mutated; only this request's own copy carries the resolved ports.
    """
    module = get_model_module(session, model_module_id)
    if module is None:
        raise ValueError(f"no ModelModule with id {model_module_id}")
    if module.execution_status is not ModelModuleExecutionStatus.SIMULATION_READY:
        raise ValueError(
            f"ModelModule {model_module_id} is {module.execution_status.value}, not "
            "SIMULATION_READY -- resolve its boundary ports first "
            "(app.orchestration.module_boundary_orchestrator)"
        )

    source_run_record = get_run_record(session, module.run_record_id)
    assert source_run_record is not None
    agent1_organism_id, stage1_synthetic_source = resolve_stage1_inputs(source_run_record)

    if run_record_id is not None:
        existing = get_run_record(session, run_record_id)
        if existing is None:
            raise ValueError(f"no RunRecord with id {run_record_id}")
        if existing.status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
            return existing
        run_record = existing
    else:
        run_record = create_run_record(
            subproject_id=subproject_id,
            stage=RunStage.AGENT3,
            session=session,
            model_id=module.root_model_id,
        )
        run_record.model_module_id = module.id
        session.flush()

    run_record = start_run(run_record_id=run_record.id, session=session)

    input_artifact_references: dict[str, str] = {}
    if stage1_synthetic_source is not None:
        input_artifact_references["stage1_synthetic_source"] = stage1_synthetic_source

    attach_payload = build_attach_payload(module)
    attach_payload["module_ports"] = build_module_ports_payload(module, session)

    request = ModuleSimulationRequest(
        contract_version=CONTRACT_VERSION,
        run_id=str(run_record.id),
        project_id=str(project_id),
        subproject_id=str(subproject_id),
        attach_payload=attach_payload,
        module_id=module.module_id,
        agent1_organism_id=agent1_organism_id,
        input_artifact_references=input_artifact_references,
        correlation_id=correlation_id,
        notes=notes,
        submitted_at=datetime.now(UTC).isoformat(),
    )

    result, client_error = invoke_module_simulation(request)

    if client_error is not None:
        return complete_run(
            run_record_id=run_record.id,
            status=RunStatus.FAILED,
            session=session,
            error_summary=f"{client_error.code}: {client_error.message}",
        )

    assert result is not None  # invoke_module_simulation's own contract

    artifact_payload = json.dumps(
        {
            "module_id": result.module_id,
            "modularization_id": result.modularization_id,
            "module_handoff_summary": result.module_handoff_summary,
            "agent3_report": result.agent3_report,
        }
    )
    warnings_payload = json.dumps(list(result.warnings)) if result.warnings else None

    if result.status == "SUCCEEDED":
        return complete_run(
            run_record_id=run_record.id,
            status=RunStatus.SUCCEEDED,
            session=session,
            contract_version=result.contract_version,
            artifact_reference=artifact_payload,
            result_summary=result.summary,
            warnings=warnings_payload,
        )

    error_message = result.summary if result.error is None else result.error.message
    return complete_run(
        run_record_id=run_record.id,
        status=RunStatus.FAILED,
        session=session,
        contract_version=result.contract_version,
        artifact_reference=artifact_payload,
        error_summary=error_message,
        warnings=warnings_payload,
    )


__all__ = [
    "get_model_module_with_provenance",
    "list_model_modules",
    "request_module_simulation",
]
