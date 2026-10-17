"""Module-Level Agent4 Calibration: the service layer a caller uses to request, execute, and
retrieve an Agent4 calibration run for a selected, ``SIMULATION_READY`` hierarchy module, with
an immutable, versioned snapshot of exactly what was used captured for every attempt.

No scientific logic lives here: Agent 4's own calibration outcome is read verbatim from the
harness's own report. This module only resolves a module's own stored provenance and resolved
boundary ports into a request, validates it against data this Workbench already durably owns
(never a fabricated measurement/parameter/boundary value), captures an immutable snapshot of
the exact inputs, moves a ``RunRecord`` through its own existing, unchanged state machine
(``app.persistence.run_record``), and records the result.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.module_calibration import (
    CONTRACT_VERSION,
    ModuleCalibrationRequest,
)
from app.models.enums import ModuleExecutionKind, RunStage, RunStatus
from app.models.model_module import ModelModule
from app.models.run_record import RunRecord
from app.orchestration.module_boundary_orchestrator import build_module_ports_payload
from app.orchestration.module_calibration_harness_client import invoke_module_calibration
from app.persistence.dataset_reference import get_dataset_reference
from app.persistence.model_module import (
    build_attach_payload,
    get_model_module,
    known_component_ids_by_type,
)
from app.persistence.module_boundary_port import list_boundary_ports_for_module
from app.persistence.module_execution_snapshot import compute_module_artifact_hash, create_snapshot
from app.persistence.run_record import (
    complete_run,
    create_run_record,
    get_run_record,
    resolve_stage1_inputs,
    start_run,
)

_VALID_TARGET_KINDS = {"PARAMETER": "PARAMETER", "INITIAL_CONDITION": "SPECIES"}


class ModuleCalibrationValidationError(ValueError):
    """Raised when ``calibration_request`` is incomplete or names a target/species/dataset
    this module or project does not actually have -- never fabricated, always rejected before
    any harness call is ever made (task instructions §3)."""


def _validate_calibration_request(calibration_request: dict, module: ModelModule) -> None:
    """Reject an incomplete or scientifically unsupported calibration request before it ever
    reaches the harness -- validated against this module's own durably-recorded membership
    (never a harness round-trip, never a fabricated id).

    Raises ``ModuleCalibrationValidationError``.
    """
    if not calibration_request.get("request_id"):
        raise ModuleCalibrationValidationError(
            "calibration_request requires a non-empty request_id"
        )

    targets = calibration_request.get("targets")
    if not targets:
        raise ModuleCalibrationValidationError(
            "calibration_request requires at least one calibration target"
        )
    known = known_component_ids_by_type(module)
    for target in targets:
        target_kind = target.get("target_kind")
        if target_kind not in _VALID_TARGET_KINDS:
            raise ModuleCalibrationValidationError(
                f"calibration target has an unsupported target_kind {target_kind!r} -- must "
                f"be one of {sorted(_VALID_TARGET_KINDS)}"
            )
        component_type = _VALID_TARGET_KINDS[target_kind]
        target_id = target.get("target_id")
        if not target_id or target_id not in known.get(component_type, set()):
            raise ModuleCalibrationValidationError(
                f"calibration target {target_id!r} ({target_kind}) is not a member of module "
                f"{module.module_id!r}"
            )

    observation_set = calibration_request.get("observations") or {}
    observations = observation_set.get("observations")
    if not observations:
        raise ModuleCalibrationValidationError(
            "calibration_request requires at least one observation"
        )
    known_species = known.get("SPECIES", set())
    for observation in observations:
        species_id = observation.get("target_species_id")
        if not species_id or species_id not in known_species:
            raise ModuleCalibrationValidationError(
                f"observation target species {species_id!r} is not a member of module "
                f"{module.module_id!r}"
            )
        time_points = observation.get("time_points") or []
        values = observation.get("values") or []
        if not time_points or not values:
            raise ModuleCalibrationValidationError(
                f"observation {observation.get('observation_id')!r} has no time_points/values "
                "-- a calibration target must have real experimental measurements, never a "
                "placeholder"
            )
        if len(time_points) != len(values):
            raise ModuleCalibrationValidationError(
                f"observation {observation.get('observation_id')!r} has mismatched "
                f"time_points/values lengths ({len(time_points)} vs {len(values)})"
            )


def _boundary_ports_snapshot(session: Session, model_module_id: UUID) -> list[dict]:
    ports = list_boundary_ports_for_module(session, model_module_id)
    return [
        {
            "port_id": p.port_id,
            "species_id": p.species_id,
            "direction": p.direction.value,
            "treatment_type": p.treatment_type.value,
            "resolution_status": p.resolution_status.value,
            "initial_value": str(p.initial_value) if p.initial_value is not None else None,
            "unit": p.unit,
            "value_source": p.value_source,
            "decided_by": p.decided_by,
            "decided_at": p.decided_at.isoformat() if p.decided_at else None,
        }
        for p in ports
    ]


def _dataset_references_snapshot(
    session: Session, dataset_reference_ids: list[UUID], *, project_id: UUID
) -> list[dict]:
    snapshot = []
    for dataset_reference_id in dataset_reference_ids:
        dataset_reference = get_dataset_reference(session, dataset_reference_id)
        if dataset_reference is None:
            raise ModuleCalibrationValidationError(
                f"no DatasetReference with id {dataset_reference_id}"
            )
        if dataset_reference.project_id != project_id:
            raise ModuleCalibrationValidationError(
                f"DatasetReference {dataset_reference_id} does not belong to project {project_id}"
            )
        snapshot.append(
            {
                "dataset_reference_id": str(dataset_reference.id),
                "name": dataset_reference.name,
                "dataset_type": dataset_reference.dataset_type,
                "artifact_reference": dataset_reference.artifact_reference,
                "checksum": dataset_reference.checksum,
                "version_label": dataset_reference.version_label,
            }
        )
    return snapshot


def request_module_calibration(
    *,
    model_module_id: UUID,
    subproject_id: UUID,
    project_id: UUID,
    calibration_request: dict,
    session: Session,
    dataset_reference_ids: list[UUID] | None = None,
    prior_simulation_run_record_id: UUID | None = None,
    correlation_id: str | None = None,
    notes: str | None = None,
    run_record_id: UUID | None = None,
) -> RunRecord:
    """Request a real Agent 4 calibration of one accepted hierarchy module's own standalone
    executable artifact against Workbench-supplied experimental data (reusing the harness's
    own module-calibration canonical entrypoint -- never a whole-model Agent 4 run, and never
    Agent 2/Agent 3/Agent 4's own logic duplicated here).

    **Gated on execution readiness**, identical to ``model_module_orchestrator
    .request_module_simulation``'s own gate: raises ``ValueError`` unless ``module.execution
    _status`` is already ``SIMULATION_READY``.

    **Validated before any harness call**: raises ``ModuleCalibrationValidationError`` for an
    incomplete request (no targets/observations), a target/observation naming a
    parameter/species this module does not have, or a ``dataset_reference_ids`` entry that
    does not exist or belongs to a different project -- never a harness round-trip needed to
    reject a request this Workbench already has enough information to reject.

    **Immutable execution snapshot**: an ``app.models.module_execution_snapshot
    .ModuleExecutionSnapshot`` row is created for this run (keyed 1:1 by the new ``RunRecord``'s
    own id) *before* the harness is invoked -- capturing the exact resolved boundary ports,
    calibration configuration, referenced datasets, and a content hash of the Agent 2
    materialization input -- so a snapshot exists even if the harness call itself fails, and a
    later change to any boundary decision or dataset never alters it.

    **Duplicate/replayed run handling**, identical to ``request_module_simulation``'s own: when
    ``run_record_id`` names an existing, already-terminal ``RunRecord``, that row is returned
    unchanged -- the harness is never invoked again, and no second snapshot is created.

    Recorded as ``RunStage.AGENT4`` with ``model_module_id`` set.
    """
    module = get_model_module(session, model_module_id)
    if module is None:
        raise ValueError(f"no ModelModule with id {model_module_id}")
    if module.execution_status.value != "SIMULATION_READY":
        raise ValueError(
            f"ModelModule {model_module_id} is {module.execution_status.value}, not "
            "SIMULATION_READY -- resolve its boundary ports first "
            "(app.orchestration.module_boundary_orchestrator)"
        )

    if run_record_id is not None:
        existing = get_run_record(session, run_record_id)
        if existing is None:
            raise ValueError(f"no RunRecord with id {run_record_id}")
        if existing.status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
            return existing

    _validate_calibration_request(calibration_request, module)

    dataset_references_snapshot = (
        _dataset_references_snapshot(session, dataset_reference_ids, project_id=project_id)
        if dataset_reference_ids
        else None
    )
    if prior_simulation_run_record_id is not None:
        prior_run = get_run_record(session, prior_simulation_run_record_id)
        if (
            prior_run is None
            or prior_run.stage is not RunStage.AGENT3
            or (prior_run.model_module_id != module.id)
        ):
            raise ValueError(
                f"prior_simulation_run_record_id {prior_simulation_run_record_id} is not an "
                f"AGENT3 simulation RunRecord for module {model_module_id}"
            )

    source_run_record = get_run_record(session, module.run_record_id)
    assert source_run_record is not None
    agent1_organism_id, stage1_synthetic_source = resolve_stage1_inputs(source_run_record)

    if run_record_id is not None:
        run_record = get_run_record(session, run_record_id)
        assert run_record is not None
    else:
        run_record = create_run_record(
            subproject_id=subproject_id,
            stage=RunStage.AGENT4,
            session=session,
            model_id=module.root_model_id,
        )
        run_record.model_module_id = module.id
        session.flush()

    run_record = start_run(run_record_id=run_record.id, session=session)

    attach_payload = build_attach_payload(module)
    module_ports_payload = build_module_ports_payload(module, session)
    attach_payload["module_ports"] = module_ports_payload
    module_artifact_hash = compute_module_artifact_hash(
        {"attach_payload": attach_payload, "module_ports": module_ports_payload}
    )

    snapshot_payload: dict = {
        "boundary_ports": _boundary_ports_snapshot(session, module.id),
        "calibration_config": calibration_request,
        "dataset_references": dataset_references_snapshot,
        "contract_versions": {"workbench_module_calibration_contract_version": CONTRACT_VERSION},
        # Boundary-Condition Pinning increment: the exact Agent 2 materialization input this
        # run actually used, carried verbatim so a *later* module-validation request can pin
        # its own materialization to these identical values rather than this module's own
        # current (and possibly since-revised) boundary state. Never read back and mutated --
        # only ever copied forward byte-for-byte by a reader.
        "attach_payload": attach_payload,
        "module_ports_payload": module_ports_payload,
    }
    if prior_simulation_run_record_id is not None:
        snapshot_payload["prior_simulation_run_record_id"] = str(prior_simulation_run_record_id)

    input_artifact_references: dict[str, str] = {}
    if stage1_synthetic_source is not None:
        input_artifact_references["stage1_synthetic_source"] = stage1_synthetic_source

    request = ModuleCalibrationRequest(
        contract_version=CONTRACT_VERSION,
        run_id=str(run_record.id),
        project_id=str(project_id),
        subproject_id=str(subproject_id),
        attach_payload=attach_payload,
        module_id=module.module_id,
        calibration_request=calibration_request,
        agent1_organism_id=agent1_organism_id,
        input_artifact_references=input_artifact_references,
        correlation_id=correlation_id,
        notes=notes,
        submitted_at=datetime.now(UTC).isoformat(),
    )

    result, client_error = invoke_module_calibration(request)

    if client_error is not None:
        create_snapshot(
            model_module_id=module.id,
            run_record_id=run_record.id,
            execution_kind=ModuleExecutionKind.CALIBRATION,
            module_artifact_hash=module_artifact_hash,
            snapshot_payload=snapshot_payload,
            session=session,
        )
        return complete_run(
            run_record_id=run_record.id,
            status=RunStatus.FAILED,
            session=session,
            error_summary=f"{client_error.code}: {client_error.message}",
        )

    assert result is not None  # invoke_module_calibration's own contract

    if result.module_handoff is not None:
        snapshot_payload["module_handoff_summary"] = {
            "model_id": result.module_handoff.get("model_id"),
            "species_count": len(result.module_handoff.get("species", [])),
            "reaction_count": len(result.module_handoff.get("reactions", [])),
            "parameter_count": len(result.module_handoff.get("parameters", [])),
        }
        snapshot_payload["parameters"] = result.module_handoff.get("parameters", [])
        snapshot_payload["species"] = result.module_handoff.get("species", [])

    create_snapshot(
        model_module_id=module.id,
        run_record_id=run_record.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        module_artifact_hash=module_artifact_hash,
        snapshot_payload=snapshot_payload,
        session=session,
    )

    artifact_payload = json.dumps(
        {
            "module_id": result.module_id,
            "modularization_id": result.modularization_id,
            "agent4_report": result.agent4_report,
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


def list_calibration_runs(session: Session, model_module_id: UUID) -> list[RunRecord]:
    """Every Agent4 calibration ``RunRecord`` for one module, newest first. Read-only."""
    stmt = (
        select(RunRecord)
        .where(RunRecord.model_module_id == model_module_id, RunRecord.stage == RunStage.AGENT4)
        .order_by(RunRecord.created_at.desc())
    )
    return list(session.scalars(stmt))


__all__ = [
    "ModuleCalibrationValidationError",
    "list_calibration_runs",
    "request_module_calibration",
]
