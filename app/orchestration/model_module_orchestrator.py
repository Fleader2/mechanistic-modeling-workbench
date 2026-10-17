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
from app.models.enums import RunStage, RunStatus
from app.models.model_module import ModelModule
from app.models.run_record import RunRecord
from app.orchestration.module_simulation_harness_client import invoke_module_simulation
from app.persistence.model_module import (
    build_attach_payload,
    get_model_module,
    list_model_modules_for_run,
)
from app.persistence.run_record import complete_run, create_run_record, get_run_record, start_run


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


def _resolve_stage1_inputs(run_record: RunRecord) -> tuple[str | None, str | None]:
    """The hierarchy run's own original stage-1 input, recorded in its own
    ``artifact_reference`` JSON by ``app.orchestration.hierarchical_run_orchestrator
    .persist_result_and_transition``. Raises ``ValueError`` if neither was ever recorded (a
    run_record predating this increment, or one whose own artifact_reference was never
    written)."""
    if not run_record.artifact_reference:
        raise ValueError(
            f"RunRecord {run_record.id} has no recorded stage-1 input to reuse for module "
            "simulation"
        )
    try:
        data = json.loads(run_record.artifact_reference)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(
            f"RunRecord {run_record.id}'s own artifact_reference could not be parsed: {exc!r}"
        ) from exc
    organism_id = data.get("agent1_organism_id")
    synthetic_source = data.get("stage1_synthetic_source")
    if organism_id is None and synthetic_source is None:
        raise ValueError(
            f"RunRecord {run_record.id} has no recorded stage-1 input to reuse for module "
            "simulation"
        )
    return organism_id, synthetic_source


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
    """
    module = get_model_module(session, model_module_id)
    if module is None:
        raise ValueError(f"no ModelModule with id {model_module_id}")

    source_run_record = get_run_record(session, module.run_record_id)
    assert source_run_record is not None
    agent1_organism_id, stage1_synthetic_source = _resolve_stage1_inputs(source_run_record)

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

    request = ModuleSimulationRequest(
        contract_version=CONTRACT_VERSION,
        run_id=str(run_record.id),
        project_id=str(project_id),
        subproject_id=str(subproject_id),
        attach_payload=build_attach_payload(module),
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
