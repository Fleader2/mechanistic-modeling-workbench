"""Module-Set Edited-Module Materialization increment, Phase B: the service layer a caller
uses to derive boundary candidates for one module-set member's own current reaction selection,
submit a simulation, and (the background worker's own job) actually run one.

No scientific logic lives here: Agent 2's own reaction-participant topology still decides which
species are boundary candidates (reused, unmodified, via the identical harness contract
``app.orchestration.module_boundary_orchestrator`` already uses); a human decision still
decides a candidate's own treatment; Agent 2's own ``materialize_submodel`` still decides the
real dependency closure once simulation is actually requested. This module only builds the
REACTION-only attach payload from a member's own saved selection, routes to the harness,
persists idempotently, and evaluates one small, pure, explicitly-documented readiness rule.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.module_boundary_derivation import (
    CONTRACT_VERSION as BOUNDARY_DERIVATION_CONTRACT_VERSION,
)
from app.contracts.module_boundary_derivation import ModuleBoundaryDerivationRequest
from app.contracts.module_rematerialization import (
    CONTRACT_VERSION as REMATERIALIZATION_CONTRACT_VERSION,
)
from app.contracts.module_rematerialization import ModuleRematerializationRequest
from app.contracts.module_set_simulation import (
    CONTRACT_VERSION as MODULE_SET_SIMULATION_CONTRACT_VERSION,
)
from app.contracts.module_set_simulation import ModuleSetSimulationRequest
from app.models.enums import RunStatus
from app.models.module_set import ModuleSetMember
from app.models.module_set_execution import ModuleSetMemberBoundaryPort
from app.models.run_record import RunRecord
from app.orchestration.module_boundary_derivation_harness_client import (
    invoke_module_boundary_derivation,
)
from app.orchestration.module_rematerialization_harness_client import (
    invoke_module_rematerialization,
)
from app.orchestration.module_set_simulation_harness_client import invoke_module_set_simulation
from app.persistence.module_set import effective_reaction_component_ids
from app.persistence.module_set_execution import (
    get_execution_snapshot_for_run,
    get_or_create_review,
    persist_candidate_boundary_ports,
)
from app.persistence.run_record import complete_run, get_run_record, resolve_stage1_inputs


class ModuleSetMemberBoundaryDerivationError(ValueError):
    """Raised when the harness could not be reached or itself reported failure deriving
    boundary candidates -- never for an empty candidate list (a genuine, disclosed outcome)."""


class ModuleSetMemberRematerializationError(ValueError):
    """Raised when the harness could not be reached or itself reported failure rebuilding a
    member's own reaction selection (an unknown reaction id, most commonly -- should be
    unreachable for an already-saved module-set member, since increment 23's own editing
    validation already rejects an unknown id before save, but checked here defensively rather
    than assumed)."""


def _reaction_only_attach_payload(member: ModuleSetMember, *, modularization_id: str) -> dict:
    """The synthetic ``{"modularization_id", "module_ids", "memberships"}`` dict naming
    exactly this member's own current, saved reaction selection -- REACTION-type memberships
    only, built fresh every call from the member's own *effective* reaction ids (its own
    ``reaction_component_ids`` when edited, else derived from its resolved ``ModelModule``'s
    own ``attach_payload`` -- see ``effective_reaction_component_ids``), never stored or reused
    across calls."""
    reaction_ids = effective_reaction_component_ids(member)
    module_id = member.model_module.module_id
    return {
        "modularization_id": modularization_id,
        "module_ids": [module_id],
        "memberships": [
            {"module_id": module_id, "component_type": "REACTION", "component_id": rid}
            for rid in reaction_ids
        ],
    }


def _resolve_stage1_inputs_for_member(member: ModuleSetMember, session: Session) -> tuple:
    source_run_record = get_run_record(session, member.model_module.run_record_id)
    assert source_run_record is not None  # ModelModule.run_record_id is NOT NULL
    return resolve_stage1_inputs(source_run_record)


def derive_boundary_candidates(
    *,
    module_set_member: ModuleSetMember,
    project_id: UUID,
    subproject_id: UUID,
    session: Session,
    correlation_id: str | None = None,
) -> list[ModuleSetMemberBoundaryPort]:
    """Ask the harness to derive candidate boundary species for one module-set member's own
    current, saved reaction selection, persist the newly-found candidates idempotently.

    Reuses the module-boundary-derivation harness contract entirely unmodified -- confirmed by
    direct code inspection that its own structural algorithm reads reaction-participant
    topology from the rebuilt full network, never from the attach payload's own (absent, for a
    reaction-only selection) species/parameter memberships, so it already works correctly here
    with zero Harness/Agent 2 changes.
    """
    review = get_or_create_review(session, module_set_member.id)
    agent1_organism_id, stage1_synthetic_source = _resolve_stage1_inputs_for_member(
        module_set_member, session
    )
    input_artifact_references: dict[str, str] = {}
    if stage1_synthetic_source is not None:
        input_artifact_references["stage1_synthetic_source"] = stage1_synthetic_source

    modularization_id = f"module-set-member::{module_set_member.id}"
    request = ModuleBoundaryDerivationRequest(
        contract_version=BOUNDARY_DERIVATION_CONTRACT_VERSION,
        run_id=f"module-set-boundary-derivation::{module_set_member.id}::"
        f"{datetime.now(UTC).timestamp():.6f}",
        project_id=str(project_id),
        subproject_id=str(subproject_id),
        attach_payload=_reaction_only_attach_payload(
            module_set_member, modularization_id=modularization_id
        ),
        module_id=module_set_member.model_module.module_id,
        agent1_organism_id=agent1_organism_id,
        input_artifact_references=input_artifact_references,
        correlation_id=correlation_id,
        submitted_at=datetime.now(UTC).isoformat(),
    )

    result, client_error = invoke_module_boundary_derivation(request)
    if client_error is not None:
        raise ModuleSetMemberBoundaryDerivationError(
            f"could not reach the harness for boundary derivation: "
            f"{client_error.code}: {client_error.message}"
        )
    assert result is not None
    if result.status != "SUCCEEDED":
        message = result.summary if result.error is None else result.error.message
        raise ModuleSetMemberBoundaryDerivationError(f"boundary derivation failed: {message}")

    return persist_candidate_boundary_ports(
        review_id=review.id, candidates=list(result.candidates), session=session
    )


def preview_rematerialization(
    *,
    module_set_member: ModuleSetMember,
    project_id: UUID,
    subproject_id: UUID,
    session: Session,
    correlation_id: str | None = None,
) -> dict:
    """Rebuild this member's own current reaction selection structure-only (no boundary
    treatments supplied) -- used by the pre-run summary to show exactly what will be
    simulated (species/reaction/parameter counts, lineage) without yet invoking Agent 3.

    Raises ``ModuleSetMemberRematerializationError`` on a genuine failure (an unknown reaction
    id -- see this module's own class docstring for why that should be unreachable for an
    already-saved member, but is still checked, never assumed).
    """
    agent1_organism_id, stage1_synthetic_source = _resolve_stage1_inputs_for_member(
        module_set_member, session
    )
    input_artifact_references: dict[str, str] = {}
    if stage1_synthetic_source is not None:
        input_artifact_references["stage1_synthetic_source"] = stage1_synthetic_source

    modularization_id = f"module-set-member::{module_set_member.id}"
    request = ModuleRematerializationRequest(
        contract_version=REMATERIALIZATION_CONTRACT_VERSION,
        run_id=f"module-set-rematerialization-preview::{module_set_member.id}::"
        f"{datetime.now(UTC).timestamp():.6f}",
        project_id=str(project_id),
        subproject_id=str(subproject_id),
        attach_payload=_reaction_only_attach_payload(
            module_set_member, modularization_id=modularization_id
        ),
        module_id=module_set_member.model_module.module_id,
        agent1_organism_id=agent1_organism_id,
        input_artifact_references=input_artifact_references,
        correlation_id=correlation_id,
        submitted_at=datetime.now(UTC).isoformat(),
    )

    result, client_error = invoke_module_rematerialization(request)
    if client_error is not None:
        raise ModuleSetMemberRematerializationError(
            f"could not reach the harness for materialization preview: "
            f"{client_error.code}: {client_error.message}"
        )
    assert result is not None
    if result.status != "SUCCEEDED":
        message = result.summary if result.error is None else result.error.message
        raise ModuleSetMemberRematerializationError(f"materialization preview failed: {message}")

    return {"lineage": result.lineage, "unresolved_dependencies": result.unresolved_dependencies}


def _complete_run_unless_already_terminalized(
    run_id: UUID, session: Session, **complete_run_kwargs
) -> RunRecord:
    """Call ``complete_run`` unless something else (``scripts/recover_stuck_module_set_runs
    .py``, manually, while this worker was still mid-flight on the same run) already moved this
    run out of ``RUNNING`` first.

    Closes the one real race a manual stuck-run recovery procedure introduces: a worker that
    was never actually dead, still working on a run a human just force-failed as "presumed
    crashed." Re-reads the row's *current* status immediately before writing rather than
    trusting the ``run`` object this function was handed (which may be stale by the time a
    600s harness call returns) -- if it is no longer ``RUNNING``, this worker's own result is
    discarded (never written over whatever already-terminal status is there) and the existing
    row is returned unchanged. This never causes a duplicate harness execution (recovery itself
    never calls the harness; this is the only harness call for this run either way) and never
    leaves a misleadingly-``RUNNING`` row un-terminalized (recovery already terminalized it).
    """
    current = session.get(RunRecord, run_id)
    assert current is not None
    if current.status is not RunStatus.RUNNING:
        print(
            f"module_set_execution_orchestrator: run {run_id} is already {current.status.value} "
            "(terminalized by something else while this worker was processing it -- "
            "discarding this worker's own result rather than overwriting it)"
        )
        return current
    return complete_run(run_record_id=run_id, session=session, **complete_run_kwargs)


def process_one_pending_run(run: RunRecord, session: Session) -> RunRecord:
    """The background worker's own unit of work: given an already-``RUNNING`` module-set-
    scoped ``RunRecord`` (claimed by ``claim_next_pending_module_set_run``), invoke the harness
    against its own pinned ``ModuleExecutionSnapshot`` and complete the run.

    Builds the attach payload and ``module_ports`` from the *snapshot's own frozen payload*,
    never from the live member -- the entire point of pinning: a later membership edit
    elsewhere (impossible here, since the member's own version is immutable, but the principle
    holds regardless) could never retroactively change what this specific run actually
    simulates.
    """
    snapshot = get_execution_snapshot_for_run(session, run.id)
    assert snapshot is not None  # submit_module_set_simulation always creates one
    payload = json.loads(snapshot.snapshot_payload)

    member = session.get(ModuleSetMember, run.module_set_member_id)
    assert member is not None
    agent1_organism_id, stage1_synthetic_source = _resolve_stage1_inputs_for_member(member, session)
    input_artifact_references: dict[str, str] = {}
    if stage1_synthetic_source is not None:
        input_artifact_references["stage1_synthetic_source"] = stage1_synthetic_source

    modularization_id = f"module-set-member::{member.id}"
    module_id = member.model_module.module_id
    attach_payload = {
        "modularization_id": modularization_id,
        "module_ids": [module_id],
        "memberships": [
            {"module_id": module_id, "component_type": "REACTION", "component_id": rid}
            for rid in payload["reaction_component_ids"]
        ],
    }

    request = ModuleSetSimulationRequest(
        contract_version=MODULE_SET_SIMULATION_CONTRACT_VERSION,
        run_id=str(run.id),
        project_id=str(run.subproject.project_id),
        subproject_id=str(run.subproject_id),
        attach_payload=attach_payload,
        module_id=module_id,
        module_ports=tuple(payload["resolved_boundary_ports"]),
        agent1_organism_id=agent1_organism_id,
        input_artifact_references=input_artifact_references,
        submitted_at=datetime.now(UTC).isoformat(),
    )

    result, client_error = invoke_module_set_simulation(request)
    if client_error is not None:
        return _complete_run_unless_already_terminalized(
            run.id,
            session,
            status=RunStatus.FAILED,
            error_summary=f"{client_error.code}: {client_error.message}",
        )

    assert result is not None
    artifact_payload = json.dumps(
        {
            "module_id": result.module_id,
            "module_handoff_summary": result.module_handoff_summary,
            "lineage": result.lineage,
            "agent3_report": result.agent3_report,
        }
    )
    warnings_payload = json.dumps(list(result.warnings)) if result.warnings else None

    if result.status == "SUCCEEDED":
        return _complete_run_unless_already_terminalized(
            run.id,
            session,
            status=RunStatus.SUCCEEDED,
            contract_version=result.contract_version,
            artifact_reference=artifact_payload,
            result_summary=result.summary,
            warnings=warnings_payload,
        )

    error_message = result.summary if result.error is None else result.error.message
    return _complete_run_unless_already_terminalized(
        run.id,
        session,
        status=RunStatus.FAILED,
        contract_version=result.contract_version,
        artifact_reference=artifact_payload,
        error_summary=error_message,
        warnings=warnings_payload,
    )


__all__ = [
    "ModuleSetMemberBoundaryDerivationError",
    "ModuleSetMemberRematerializationError",
    "derive_boundary_candidates",
    "preview_rematerialization",
    "process_one_pending_run",
]
