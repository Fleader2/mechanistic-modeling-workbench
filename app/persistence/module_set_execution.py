"""Module-Set Edited-Module Materialization increment, Phase B: persistence for one module-set
member's own boundary review (``ModuleSetMemberReview``/``ModuleSetMemberBoundaryPort``) and
simulation run submission (``RunRecord``/``ModuleExecutionSnapshot``, both reused unchanged).

No scientific logic lives here -- mirrors ``app.persistence.module_boundary_port``'s own
"store already-decided fields, enforce this increment's own idempotency rules" discipline
exactly, scoped to a review instead of a real ``model_module_id``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
    ModuleBoundaryResolutionStatus,
    ModuleBoundaryTreatmentType,
    ModuleExecutionKind,
    ModulePortDirection,
    RunStage,
    RunStatus,
)
from app.models.module_execution_snapshot import ModuleExecutionSnapshot
from app.models.module_set import ModuleSetMember
from app.models.module_set_execution import ModuleSetMemberBoundaryPort, ModuleSetMemberReview
from app.models.run_record import RunRecord
from app.persistence.module_set import effective_reaction_component_ids
from app.persistence.run_record import create_run_record

#: The one treatment-type set that lets Agent 2 build a standalone executable artifact --
#: identical to ``module_boundary_orchestrator``'s own ``_STANDALONE_CAPABLE_TREATMENTS``.
_STANDALONE_CAPABLE_TREATMENTS = (
    ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
    ModuleBoundaryTreatmentType.PRESCRIBED_INPUT,
)

#: Active (non-terminal) run statuses -- used both for the duplicate-submission pre-check and
#: for the partial unique index this increment's own migration adds.
_ACTIVE_RUN_STATUSES = (RunStatus.PENDING, RunStatus.RUNNING)


class ModuleSetMemberReviewStaleError(ValueError):
    """Raised when a boundary-decision or simulation submission's own ``expected_review_
    version`` no longer matches the review's current value -- someone/something else acted on
    this member's review first. Carries the review's current, true value so the caller can
    refetch and retry."""

    def __init__(self, review: ModuleSetMemberReview, expected_review_version: int) -> None:
        self.review = review
        self.expected_review_version = expected_review_version
        super().__init__(
            f"ModuleSetMemberReview {review.id} is at review_version {review.review_version}, "
            f"not {expected_review_version} -- it changed since last read"
        )


class ModuleSetMemberNotReadyError(ValueError):
    """Raised when a simulation is submitted for a member whose review is not ready -- the
    direct-execution-bypassing-readiness rejection the task explicitly requires. Carries every
    blocking finding."""

    def __init__(self, findings: list[ReadinessFinding]) -> None:
        self.findings = findings
        super().__init__(f"module-set member is not ready to simulate: {len(findings)} finding(s)")


class ModuleSetMemberSimulationAlreadyActiveError(ValueError):
    """Raised when a simulation is submitted for a member that already has an active
    (``PENDING``/``RUNNING``) run -- duplicate-submission protection. Carries the existing,
    active ``RunRecord``."""

    def __init__(self, existing_run: RunRecord) -> None:
        self.existing_run = existing_run
        super().__init__(
            f"module-set member already has an active run ({existing_run.id}, "
            f"status={existing_run.status.value})"
        )


@dataclass(frozen=True)
class ReadinessFinding:
    """One actionable, blocking reason a module-set member cannot yet be simulated."""

    code: Literal["UNRESOLVED_BOUNDARY_PORT", "NO_BOUNDARY_PORTS_DERIVED"]
    message: str
    species_id: str | None = None
    direction: str | None = None


def get_or_create_review(session: Session, module_set_member_id: UUID) -> ModuleSetMemberReview:
    """The one ``ModuleSetMemberReview`` row for this member, creating it (at
    ``review_version=0``, never derived yet) on first access. Never creates a second row for
    the same member (the migration's own unique constraint on ``module_set_member_id`` backs
    this up at the database level too)."""
    review = session.execute(
        select(ModuleSetMemberReview).where(
            ModuleSetMemberReview.module_set_member_id == module_set_member_id
        )
    ).scalar_one_or_none()
    if review is not None:
        return review
    review = ModuleSetMemberReview(module_set_member_id=module_set_member_id)
    session.add(review)
    session.flush()
    return review


def _port_id(review_id: UUID, species_id: str, direction: ModulePortDirection) -> str:
    return f"msm-port::{review_id}::{species_id}::{direction.value}"


def persist_candidate_boundary_ports(
    *, review_id: UUID, candidates: list[dict], session: Session
) -> list[ModuleSetMemberBoundaryPort]:
    """Create (and return only) the newly-created ``ModuleSetMemberBoundaryPort`` rows for
    every ``{"species_id", "direction"}`` candidate not already represented for this review --
    always ``UNRESOLVED``/``PENDING_REVIEW``. An already-decided row is never touched, the
    identical idempotent-re-derivation discipline ``persist_candidate_boundary_ports`` (the
    real-module equivalent) already established."""
    existing_keys = {
        (row.species_id, row.direction)
        for row in session.execute(
            select(
                ModuleSetMemberBoundaryPort.species_id, ModuleSetMemberBoundaryPort.direction
            ).where(ModuleSetMemberBoundaryPort.review_id == review_id)
        )
    }

    created: list[ModuleSetMemberBoundaryPort] = []
    for candidate in candidates:
        direction = ModulePortDirection(candidate["direction"])
        species_id = candidate["species_id"]
        if (species_id, direction) in existing_keys:
            continue
        row = ModuleSetMemberBoundaryPort(
            review_id=review_id,
            species_id=species_id,
            direction=direction,
            treatment_type=ModuleBoundaryTreatmentType.UNRESOLVED,
            resolution_status=ModuleBoundaryResolutionStatus.PENDING_REVIEW,
        )
        session.add(row)
        session.flush()
        created.append(row)
        existing_keys.add((species_id, direction))

    review = session.get(ModuleSetMemberReview, review_id)
    assert review is not None
    review.derived_at = datetime.now(UTC)
    session.flush()
    return created


def submit_boundary_decision(
    *,
    port_id: UUID,
    treatment_type: ModuleBoundaryTreatmentType,
    expected_review_version: int,
    session: Session,
    initial_value: Decimal | str | None = None,
    unit: str | None = None,
    decided_by: str | None = None,
) -> ModuleSetMemberBoundaryPort:
    """Record one treatment decision for one ``ModuleSetMemberBoundaryPort``, then advance its
    own review's ``review_version`` -- the stale-submission check every caller must pass first.

    Raises ``ValueError`` if the port does not exist, or ``treatment_type`` is ``UNRESOLVED``
    (submitting a decision always resolves something). Raises ``ModuleSetMemberReviewStaleError``
    if ``expected_review_version`` no longer matches. A value is never fabricated --
    ``initial_value`` stays ``None`` unless explicitly supplied.
    """
    row = session.get(ModuleSetMemberBoundaryPort, port_id)
    if row is None:
        raise ValueError(f"no ModuleSetMemberBoundaryPort with id {port_id}")
    review = session.get(ModuleSetMemberReview, row.review_id)
    assert review is not None  # the port's own FK guarantees this
    if review.review_version != expected_review_version:
        raise ModuleSetMemberReviewStaleError(review, expected_review_version)
    if treatment_type is ModuleBoundaryTreatmentType.UNRESOLVED:
        raise ValueError("submit_boundary_decision cannot resolve a port to UNRESOLVED")
    if initial_value is not None and treatment_type not in _STANDALONE_CAPABLE_TREATMENTS:
        raise ValueError(
            f"initial_value is only meaningful for EXTERNALLY_CONTROLLED/PRESCRIBED_INPUT, "
            f"not {treatment_type}"
        )

    row.treatment_type = treatment_type
    row.resolution_status = ModuleBoundaryResolutionStatus.RESOLVED
    row.initial_value = Decimal(initial_value) if initial_value is not None else None
    row.unit = unit
    row.decided_by = decided_by
    row.decided_at = datetime.now(UTC)
    review.review_version += 1
    session.flush()
    return row


def list_boundary_ports_for_review(
    session: Session, review_id: UUID
) -> list[ModuleSetMemberBoundaryPort]:
    """Every ``ModuleSetMemberBoundaryPort`` for one review, ordered for deterministic
    display. Read-only."""
    stmt = (
        select(ModuleSetMemberBoundaryPort)
        .where(ModuleSetMemberBoundaryPort.review_id == review_id)
        .order_by(
            ModuleSetMemberBoundaryPort.species_id.asc(),
            ModuleSetMemberBoundaryPort.direction.asc(),
        )
    )
    return list(session.scalars(stmt))


def evaluate_readiness(session: Session, review_id: UUID) -> list[ReadinessFinding]:
    """Every current blocking finding for one review -- empty means ready to simulate.

    Pure rule, mirroring ``evaluate_module_execution_status``'s own: no ports derived yet is
    itself blocking (``NO_BOUNDARY_PORTS_DERIVED``); any port not resolved to a standalone-
    capable treatment is blocking (``UNRESOLVED_BOUNDARY_PORT``, one per port). Never claims
    readiness proves whole-model coverage or biological validity -- it only means Agent 2 has
    enough resolved structural information to build a standalone artifact.
    """
    ports = list_boundary_ports_for_review(session, review_id)
    if not ports:
        return [
            ReadinessFinding(
                code="NO_BOUNDARY_PORTS_DERIVED",
                message=(
                    "Boundary candidates have not been derived yet for this module's current "
                    "reaction selection."
                ),
            )
        ]
    findings = [
        ReadinessFinding(
            code="UNRESOLVED_BOUNDARY_PORT",
            message=f"Species {port.species_id!r} ({port.direction.value}) has no resolved, "
            "standalone-capable boundary treatment.",
            species_id=port.species_id,
            direction=port.direction.value,
        )
        for port in ports
        if port.treatment_type not in _STANDALONE_CAPABLE_TREATMENTS
    ]
    return findings


def build_resolved_module_ports_payload(
    session: Session, review_id: UUID, *, module_id: str
) -> list[dict]:
    """The ``module_ports`` list to send the harness for simulation -- the exact shape
    ``run_agent2_rematerialize_module.py`` parses (``{"port_id", "module_id", "species_id",
    "direction", "externally_controlled", "initial_value", "unit"}``, identically to
    ``build_module_ports_payload``'s own established shape -- ``module_id`` is required by the
    harness's own ``ModulePort`` construction, not optional). Only a resolved,
    standalone-capable port is ever included, mirroring ``build_module_ports_payload``'s own
    identical filter."""
    ports = list_boundary_ports_for_review(session, review_id)
    return [
        {
            "port_id": f"msm-port::{review_id}::{port.species_id}::{port.direction.value}",
            "module_id": module_id,
            "species_id": port.species_id,
            "direction": port.direction.value,
            "externally_controlled": True,
            "initial_value": (str(port.initial_value) if port.initial_value is not None else None),
            "unit": port.unit,
        }
        for port in ports
        if port.treatment_type in _STANDALONE_CAPABLE_TREATMENTS
    ]


def submit_module_set_simulation(
    *,
    session: Session,
    module_set_member: ModuleSetMember,
    subproject_id: UUID,
    expected_review_version: int,
    solver_settings: dict | None = None,
    saved_by: str | None = None,
) -> RunRecord:
    """Create a new ``PENDING`` ``RunRecord`` plus its own immutable, pinned
    ``ModuleExecutionSnapshot`` for simulating one module-set member's own current reaction
    selection and resolved boundary treatments -- committed fast; the actual Agent 2/Agent 3
    round trip happens later, out of this request, in the background worker.

    Raises ``ModuleSetMemberReviewStaleError`` if ``expected_review_version`` is stale.
    Raises ``ModuleSetMemberNotReadyError`` if ``evaluate_readiness`` finds any blocking
    finding -- the server-side gate a direct execution request can never bypass. Raises
    ``ModuleSetMemberSimulationAlreadyActiveError`` if this member already has an active
    (``PENDING``/``RUNNING``) run -- the application-level half of duplicate-submission
    protection; the migration's own partial unique index is the database-level half, for the
    unavoidable race between this check and the ``INSERT`` below.
    """
    review = get_or_create_review(session, module_set_member.id)
    if review.review_version != expected_review_version:
        raise ModuleSetMemberReviewStaleError(review, expected_review_version)

    findings = evaluate_readiness(session, review.id)
    if findings:
        raise ModuleSetMemberNotReadyError(findings)

    existing_active = session.execute(
        select(RunRecord).where(
            RunRecord.module_set_member_id == module_set_member.id,
            RunRecord.status.in_(_ACTIVE_RUN_STATUSES),
        )
    ).scalar_one_or_none()
    if existing_active is not None:
        raise ModuleSetMemberSimulationAlreadyActiveError(existing_active)

    run = create_run_record(
        subproject_id=subproject_id,
        stage=RunStage.AGENT3,
        session=session,
        model_id=module_set_member.model_module.root_model_id,
    )
    run.model_module_id = module_set_member.model_module_id
    run.module_set_member_id = module_set_member.id
    session.flush()

    reaction_component_ids = effective_reaction_component_ids(module_set_member)
    resolved_ports = build_resolved_module_ports_payload(
        session, review.id, module_id=module_set_member.model_module.module_id
    )
    snapshot_payload = json.dumps(
        {
            "module_set_member_id": str(module_set_member.id),
            "reaction_component_ids": reaction_component_ids,
            "resolved_boundary_ports": resolved_ports,
            "solver_settings": solver_settings or {},
            "saved_by": saved_by,
        }
    )
    snapshot = ModuleExecutionSnapshot(
        model_module_id=module_set_member.model_module_id,
        run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        module_artifact_hash=f"module-set-member::{module_set_member.id}::review-v{review.review_version}",
        snapshot_payload=snapshot_payload,
    )
    session.add(snapshot)
    session.flush()
    return run


def claim_next_pending_module_set_run(session: Session) -> RunRecord | None:
    """Atomically claim the oldest ``PENDING`` module-set-scoped run for processing --
    transitions it to ``RUNNING`` and commits immediately, so no two worker iterations (or
    worker processes) can ever claim the same run. Returns ``None`` if none is waiting.

    ``PENDING`` -> ``RUNNING`` is a real, committed state transition *before* any harness call
    is ever made -- the identical "visible progress before the long-running part starts"
    discipline ``start_run`` already establishes; a worker crash after this point leaves the
    run durably ``RUNNING`` (see ``docs/24_module_set_execution_increment.md``'s own disclosed
    restart/interruption behavior).
    """
    run = session.execute(
        select(RunRecord)
        .where(RunRecord.module_set_member_id.is_not(None), RunRecord.status == RunStatus.PENDING)
        .order_by(RunRecord.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if run is None:
        return None
    run.status = RunStatus.RUNNING
    run.started_at = datetime.now(UTC)
    session.commit()
    return run


def get_execution_snapshot_for_run(
    session: Session, run_record_id: UUID
) -> ModuleExecutionSnapshot | None:
    """The one ``ModuleExecutionSnapshot`` for a run, or ``None``. Read-only."""
    return session.execute(
        select(ModuleExecutionSnapshot).where(
            ModuleExecutionSnapshot.run_record_id == run_record_id
        )
    ).scalar_one_or_none()


def list_runs_for_module_set_member(
    session: Session, module_set_member_id: UUID
) -> list[RunRecord]:
    """Every simulation run ever submitted for one module-set member, newest first. Read-only
    -- a failed or completed run is never deleted, so a scientist can always see what was
    actually attempted."""
    stmt = (
        select(RunRecord)
        .where(RunRecord.module_set_member_id == module_set_member_id)
        .order_by(RunRecord.created_at.desc())
    )
    return list(session.scalars(stmt))


__all__ = [
    "ModuleSetMemberNotReadyError",
    "ModuleSetMemberReviewStaleError",
    "ModuleSetMemberSimulationAlreadyActiveError",
    "ReadinessFinding",
    "build_resolved_module_ports_payload",
    "claim_next_pending_module_set_run",
    "evaluate_readiness",
    "get_execution_snapshot_for_run",
    "get_or_create_review",
    "list_boundary_ports_for_review",
    "list_runs_for_module_set_member",
    "persist_candidate_boundary_ports",
    "submit_boundary_decision",
    "submit_module_set_simulation",
]
