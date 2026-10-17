"""Module-Level Agent5 Validation and Experimental Design: the service layer a caller uses to
request, execute, and retrieve an Agent5 validation run for a selected, already-calibrated
hierarchy module, with an immutable, versioned snapshot of exactly what was used captured for
every attempt.

No scientific logic lives here: Agent 5's own validation/experimental-design outcome is read
verbatim from the harness's own report. This module only resolves a module's own stored
provenance, a *prior, already-succeeded* calibration run's own frozen parameter estimates, and
the caller's own independent validation data into a request, validates it against data this
Workbench already durably owns (never a fabricated measurement or calibrated-parameter
override), captures an immutable snapshot of the exact inputs, moves a ``RunRecord`` through
its own existing, unchanged state machine (``app.persistence.run_record``), and records the
result.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.module_validation import (
    CONTRACT_VERSION,
    ModuleValidationRequest,
)
from app.models.enums import ModuleExecutionKind, RunStage, RunStatus
from app.models.model_module import ModelModule
from app.models.run_record import RunRecord
from app.orchestration.module_boundary_orchestrator import build_module_ports_payload
from app.orchestration.module_validation_harness_client import invoke_module_validation
from app.persistence.dataset_reference import get_dataset_reference
from app.persistence.model_module import (
    build_attach_payload,
    get_model_module,
    known_component_ids_by_type,
)
from app.persistence.module_boundary_port import list_boundary_ports_for_module
from app.persistence.module_execution_snapshot import (
    compute_module_artifact_hash,
    create_snapshot,
    get_snapshot_for_run,
    read_snapshot_payload,
)
from app.persistence.run_record import (
    complete_run,
    create_run_record,
    get_run_record,
    resolve_stage1_inputs,
    start_run,
)
from app.units import find_observation_unit_conflict


class ModuleValidationValidationError(ValueError):
    """Raised when a validation request is incomplete, names an unknown species, or reuses a
    dataset reference the originating calibration run already consumed -- never fabricated,
    always rejected before any harness call is ever made (task instructions §2)."""


def _validate_validation_request(
    validation_request: dict, module: ModelModule, session: Session
) -> None:
    """Reject an incomplete or scientifically unsupported validation request before it ever
    reaches the harness -- validated against this module's own durably-recorded membership
    (never a harness round-trip, never a fabricated id).

    **Pre-flight dimensional check** (Structured Units and Dimensional-Consistency Validation
    increment, task instructions §6): identical to ``module_calibration_orchestrator``'s own --
    an observation's optional ``"unit"`` key is checked against the target species' own
    already-resolved boundary-port unit (if any) and against every other observation's own
    declared unit for the identical species, rejecting on a genuine dimensional incompatibility
    before any harness call.

    Raises ``ModuleValidationValidationError``.
    """
    if not validation_request.get("request_id"):
        raise ModuleValidationValidationError("validation_request requires a non-empty request_id")

    observation_set = validation_request.get("validation_observations") or {}
    observations = observation_set.get("observations")
    if not observations:
        raise ModuleValidationValidationError(
            "validation_request requires at least one independent validation observation"
        )
    known = known_component_ids_by_type(module)
    known_species = known.get("SPECIES", set())
    known_parameters = known.get("PARAMETER", set())
    for observation in observations:
        species_id = observation.get("target_species_id")
        if not species_id or species_id not in known_species:
            raise ModuleValidationValidationError(
                f"validation observation target species {species_id!r} is not a member of "
                f"module {module.module_id!r}"
            )
        time_points = observation.get("time_points") or []
        values = observation.get("values") or []
        if not time_points or not values:
            raise ModuleValidationValidationError(
                f"validation observation {observation.get('observation_id')!r} has no "
                "time_points/values -- an independent validation observation must be a real "
                "experimental measurement, never a placeholder"
            )
        if len(time_points) != len(values):
            raise ModuleValidationValidationError(
                f"validation observation {observation.get('observation_id')!r} has mismatched "
                f"time_points/values lengths ({len(time_points)} vs {len(values)})"
            )

    boundary_units_by_species = {
        p.species_id: p.unit for p in list_boundary_ports_for_module(session, module.id) if p.unit
    }
    conflict = find_observation_unit_conflict(observations, boundary_units_by_species)
    if conflict is not None:
        other_unit = conflict.get("boundary_unit", conflict.get("other_observation_unit"))
        raise ModuleValidationValidationError(
            f"validation observation for species {conflict['species_id']!r} declares a unit "
            f"{conflict['observation_unit']!r} dimensionally incompatible with {other_unit!r} "
            "-- never automatically reconciled or converted"
        )

    for candidate in validation_request.get("candidate_experiments") or ():
        target_id = candidate.get("target_id")
        if target_id and target_id not in known_species | known_parameters:
            raise ModuleValidationValidationError(
                f"candidate experiment target {target_id!r} is not a member of module "
                f"{module.module_id!r}"
            )


def _resolve_pinned_materialization_input(
    session: Session, calibration_run_record_id: UUID
) -> tuple[dict, list[dict], list[dict], str, UUID]:
    """The exact Agent 2 materialization input (``attach_payload`` and its own merged
    ``module_ports``) -- and the frozen ``boundary_ports`` summary alongside it -- the
    originating calibration run actually used, read back verbatim from that run's own
    immutable ``ModuleExecutionSnapshot`` (Boundary-Condition Pinning increment, task
    instructions §1/§2). Never re-derived from this module's own *current* (and possibly
    since-revised) boundary ports or ``attach_payload`` -- a validation run must reflect the
    conditions that produced the calibration it is validating, not whatever the module's own
    live state happens to be at validation time (task instructions §6).

    Returns ``(attach_payload, module_ports_payload, boundary_ports, module_artifact_hash,
    calibration_snapshot_id)``. Raises ``ModuleValidationValidationError`` -- never silently
    falling back to the module's current state (task instructions §5) -- if the calibration
    run has no snapshot at all, or if that snapshot predates this increment's own additive
    ``attach_payload``/``module_ports_payload`` fields.
    """
    calibration_snapshot = get_snapshot_for_run(session, calibration_run_record_id)
    if calibration_snapshot is None:
        raise ModuleValidationValidationError(
            f"calibration run {calibration_run_record_id} has no ModuleExecutionSnapshot -- "
            "cannot reconstruct the calibrated module execution conditions"
        )
    payload = read_snapshot_payload(calibration_snapshot)
    attach_payload = payload.get("attach_payload")
    module_ports_payload = payload.get("module_ports_payload")
    if attach_payload is None or module_ports_payload is None:
        raise ModuleValidationValidationError(
            f"calibration run {calibration_run_record_id}'s own snapshot does not carry a "
            "pinned attach_payload/module_ports_payload -- cannot reconstruct the calibrated "
            "module execution conditions (likely a snapshot captured before boundary-condition "
            "pinning was introduced)"
        )
    return (
        attach_payload,
        module_ports_payload,
        payload.get("boundary_ports", []),
        calibration_snapshot.module_artifact_hash,
        calibration_snapshot.id,
    )


def _resolve_calibration_report(
    session: Session, calibration_run_record_id: UUID, *, model_module_id: UUID
) -> dict:
    """The full, verbatim ``agent4_report`` dict a prior, already-succeeded module-calibration
    run produced for *this* module -- never recomputed, never substituted for a different
    module's own calibration. Raises ``ValueError`` if no such valid calibration result
    exists."""
    calibration_run = get_run_record(session, calibration_run_record_id)
    if (
        calibration_run is None
        or calibration_run.stage is not RunStage.AGENT4
        or calibration_run.model_module_id != model_module_id
        or calibration_run.status is not RunStatus.SUCCEEDED
    ):
        raise ValueError(
            f"calibration_run_record_id {calibration_run_record_id} is not a SUCCEEDED Agent4 "
            f"calibration RunRecord for module {model_module_id}"
        )
    try:
        artifact = json.loads(calibration_run.artifact_reference)
        agent4_report = artifact["agent4_report"]
    except (TypeError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError(
            f"calibration RunRecord {calibration_run_record_id}'s own artifact_reference does "
            f"not carry a parseable agent4_report: {exc!r}"
        ) from exc
    return agent4_report


def _check_datasets_are_independent_of_calibration(
    session: Session,
    *,
    calibration_run_record_id: UUID,
    validation_dataset_reference_ids: list[UUID],
) -> None:
    """Raise if any dataset reused for validation was also recorded as a calibration input in
    the originating calibration run's own immutable snapshot -- task instructions §2:
    "distinguish independent validation observations from calibration observations". Silently
    skipped (never raised) if the calibration run predates snapshotting or recorded no dataset
    references of its own -- there is nothing to cross-check against."""
    if not validation_dataset_reference_ids:
        return
    calibration_snapshot = get_snapshot_for_run(session, calibration_run_record_id)
    if calibration_snapshot is None:
        return
    calibration_dataset_ids = {
        d["dataset_reference_id"]
        for d in (read_snapshot_payload(calibration_snapshot).get("dataset_references") or ())
    }
    overlap = {str(i) for i in validation_dataset_reference_ids} & calibration_dataset_ids
    if overlap:
        raise ModuleValidationValidationError(
            f"dataset reference(s) {sorted(overlap)} were already used as calibration input "
            "for this module -- validation requires independent data, never the same dataset "
            "used to fit the parameters it is validating"
        )


def _dataset_references_snapshot(
    session: Session, dataset_reference_ids: list[UUID], *, project_id: UUID
) -> list[dict]:
    snapshot = []
    for dataset_reference_id in dataset_reference_ids:
        dataset_reference = get_dataset_reference(session, dataset_reference_id)
        if dataset_reference is None:
            raise ModuleValidationValidationError(
                f"no DatasetReference with id {dataset_reference_id}"
            )
        if dataset_reference.project_id != project_id:
            raise ModuleValidationValidationError(
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


def request_module_validation(
    *,
    model_module_id: UUID,
    subproject_id: UUID,
    project_id: UUID,
    calibration_run_record_id: UUID,
    validation_request: dict,
    session: Session,
    dataset_reference_ids: list[UUID] | None = None,
    correlation_id: str | None = None,
    notes: str | None = None,
    run_record_id: UUID | None = None,
    pin_to_calibration_snapshot: bool = True,
) -> RunRecord:
    """Request a real Agent 5 validation of one already-calibrated hierarchy module's own
    frozen parameter estimates against independent, held-out experimental data (reusing the
    harness's own module-validation canonical entrypoint -- never a whole-model Agent 5 run,
    and never Agent 2/Agent 5's own logic duplicated here).

    **Pinned to the calibration's own conditions by default** (Boundary-Condition Pinning
    increment, task instructions §1-§6): when ``pin_to_calibration_snapshot`` is ``True`` (the
    default), the Agent 2 materialization input (``attach_payload``/``module_ports``) and the
    boundary-ports summary recorded in the validation's own snapshot are both read back
    verbatim from the *originating calibration run's own* immutable ``ModuleExecutionSnapshot``
    -- never from this module's own current, possibly since-revised boundary state. A module
    boundary decision changed after calibration therefore never alters a validation run based
    on that calibration. Pass ``False`` only for an explicit, intentional future workflow that
    genuinely wants to validate against the module's *current* live conditions instead -- not
    used by anything in this repository today.

    **Gated on execution readiness and a valid prior calibration**, extending
    ``model_module_orchestrator.request_module_simulation``'s own gate: raises ``ValueError``
    unless ``module.execution_status`` is already ``SIMULATION_READY``, and unless
    ``calibration_run_record_id`` names an existing, ``SUCCEEDED`` ``RunStage.AGENT4``
    ``RunRecord`` for this exact module. Agent 3/Agent 4 are never re-invoked -- that prior
    run's own frozen ``agent4_report`` is read and passed straight through to Agent 5.

    **Validated before any harness call**: raises ``ModuleValidationValidationError`` for an
    incomplete request (no independent observations), an observation naming a species this
    module does not have, a candidate experiment naming an unknown target, a
    ``dataset_reference_ids`` entry that does not exist or belongs to a different project, or
    (task instructions §2) a dataset reference that was already recorded as calibration input
    for this same module's own originating calibration run.

    **Immutable execution snapshot**: a ``ModuleExecutionSnapshot`` row
    (``execution_kind=VALIDATION``) is created for this run *before* the harness is invoked --
    capturing the exact resolved boundary ports, the calibration run's own frozen
    ``calibrated_parameters``, a reference to the originating calibration run, the validation
    configuration, and any referenced datasets -- so a snapshot exists even if the harness call
    itself fails, and a later change to any boundary decision, the calibration result, or a
    dataset never alters it.

    **Duplicate/replayed run handling**, identical to ``request_module_calibration``'s own:
    when ``run_record_id`` names an existing, already-terminal ``RunRecord``, that row is
    returned unchanged -- the harness is never invoked again, and no second snapshot is
    created.

    Recorded as ``RunStage.AGENT5`` with ``model_module_id`` set.
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

    agent4_report = _resolve_calibration_report(
        session, calibration_run_record_id, model_module_id=module.id
    )
    _validate_validation_request(validation_request, module, session)
    if dataset_reference_ids:
        _check_datasets_are_independent_of_calibration(
            session,
            calibration_run_record_id=calibration_run_record_id,
            validation_dataset_reference_ids=dataset_reference_ids,
        )

    dataset_references_snapshot = (
        _dataset_references_snapshot(session, dataset_reference_ids, project_id=project_id)
        if dataset_reference_ids
        else None
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
            stage=RunStage.AGENT5,
            session=session,
            model_id=module.root_model_id,
        )
        run_record.model_module_id = module.id
        session.flush()

    run_record = start_run(run_record_id=run_record.id, session=session)

    calibration_snapshot_id: UUID | None = None
    pinned_module_artifact_hash: str | None = None
    if pin_to_calibration_snapshot:
        (
            pinned_attach_payload,
            module_ports_payload,
            boundary_ports_for_snapshot,
            pinned_module_artifact_hash,
            calibration_snapshot_id,
        ) = _resolve_pinned_materialization_input(session, calibration_run_record_id)
        attach_payload = dict(pinned_attach_payload)  # own copy; never mutate the snapshot's own
        attach_payload["module_ports"] = module_ports_payload
        module_artifact_hash = compute_module_artifact_hash(
            {"attach_payload": attach_payload, "module_ports": module_ports_payload}
        )
        if module_artifact_hash != pinned_module_artifact_hash:
            # The exact bytes read back from the calibration's own snapshot must hash
            # identically to what that snapshot itself recorded -- anything else means the
            # pinned conditions could not be faithfully reconstructed, and this must fail
            # clearly rather than proceed on data that may not actually match (task
            # instructions §5).
            raise ModuleValidationValidationError(
                f"pinned materialization input for calibration run {calibration_run_record_id} "
                "does not reproduce its own recorded module_artifact_hash -- cannot "
                "reconstruct the calibrated module execution conditions"
            )
    else:
        attach_payload = build_attach_payload(module)
        module_ports_payload = build_module_ports_payload(module, session)
        attach_payload["module_ports"] = module_ports_payload
        module_artifact_hash = compute_module_artifact_hash(
            {"attach_payload": attach_payload, "module_ports": module_ports_payload}
        )
        boundary_ports_for_snapshot = _boundary_ports_snapshot(session, module.id)

    snapshot_payload: dict = {
        "boundary_ports": boundary_ports_for_snapshot,
        "calibration_run_record_id": str(calibration_run_record_id),
        "calibration_snapshot_id": (
            str(calibration_snapshot_id) if calibration_snapshot_id is not None else None
        ),
        "pinned_to_calibration_snapshot": pin_to_calibration_snapshot,
        "pinned_module_artifact_hash": pinned_module_artifact_hash,
        "calibrated_parameters": agent4_report.get("calibration", {}).get(
            "parameter_estimates", []
        ),
        "validation_config": validation_request,
        "dataset_references": dataset_references_snapshot,
        "contract_versions": {"workbench_module_validation_contract_version": CONTRACT_VERSION},
    }

    input_artifact_references: dict[str, str] = {}
    if stage1_synthetic_source is not None:
        input_artifact_references["stage1_synthetic_source"] = stage1_synthetic_source

    request = ModuleValidationRequest(
        contract_version=CONTRACT_VERSION,
        run_id=str(run_record.id),
        project_id=str(project_id),
        subproject_id=str(subproject_id),
        attach_payload=attach_payload,
        module_id=module.module_id,
        agent4_report=agent4_report,
        validation_request=validation_request,
        agent1_organism_id=agent1_organism_id,
        input_artifact_references=input_artifact_references,
        correlation_id=correlation_id,
        notes=notes,
        submitted_at=datetime.now(UTC).isoformat(),
    )

    result, client_error = invoke_module_validation(request)

    if client_error is not None:
        create_snapshot(
            model_module_id=module.id,
            run_record_id=run_record.id,
            execution_kind=ModuleExecutionKind.VALIDATION,
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

    assert result is not None  # invoke_module_validation's own contract

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
        execution_kind=ModuleExecutionKind.VALIDATION,
        module_artifact_hash=module_artifact_hash,
        snapshot_payload=snapshot_payload,
        session=session,
    )

    artifact_payload = json.dumps(
        {
            "module_id": result.module_id,
            "modularization_id": result.modularization_id,
            "calibration_run_record_id": str(calibration_run_record_id),
            "agent5_report": result.agent5_report,
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


def list_validation_runs(session: Session, model_module_id: UUID) -> list[RunRecord]:
    """Every Agent5 validation ``RunRecord`` for one module, newest first. Read-only."""
    stmt = (
        select(RunRecord)
        .where(RunRecord.model_module_id == model_module_id, RunRecord.stage == RunStage.AGENT5)
        .order_by(RunRecord.created_at.desc())
    )
    return list(session.scalars(stmt))


__all__ = [
    "ModuleValidationValidationError",
    "list_validation_runs",
    "request_module_validation",
]
