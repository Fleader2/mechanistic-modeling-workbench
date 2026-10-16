"""HierarchyCheckpoint persistence: store the harness's own checkpoint payload verbatim, and
read back the current (highest-``sequence``, unconsumed) one for a run.

No scientific logic lives here: this module never parses, interprets, or re-derives anything
inside ``payload`` -- it only stores the exact dict the harness reported and hands it back
unchanged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.hierarchy_checkpoint import HierarchyCheckpoint


def create_hierarchy_checkpoint(
    *,
    run_record_id: UUID,
    sequence: int,
    checkpoint_payload: dict,
    session: Session,
) -> HierarchyCheckpoint:
    """Persist one checkpoint payload (the harness's own
    ``app.harness.hierarchical_recursion.serialize_checkpoint(...)`` dict) for ``run_record_id``
    at ``sequence``.

    Always a fresh insert -- ``(run_record_id, sequence)`` is unique, so calling this twice for
    the identical ``sequence`` raises ``IntegrityError`` rather than silently duplicating a
    checkpoint (the caller, ``app.orchestration.hierarchical_review_orchestrator``, is
    responsible for computing the next ``sequence`` correctly).
    """
    row = HierarchyCheckpoint(
        run_record_id=run_record_id,
        sequence=sequence,
        checkpoint_version=checkpoint_payload["checkpoint_version"],
        policy_version=checkpoint_payload["policy_version"],
        hierarchy_id=checkpoint_payload["hierarchy_id"],
        payload=json.dumps(checkpoint_payload),
    )
    session.add(row)
    session.flush()
    return row


def get_current_checkpoint_for_run(
    session: Session, run_record_id: UUID
) -> HierarchyCheckpoint | None:
    """The run's own current checkpoint -- the row with the maximum ``sequence`` -- or ``None``
    if the run has never paused. Read-only. Does not filter by ``consumed_at``: a caller that
    needs to know whether it is still resumable checks that field itself (see
    ``app.orchestration.hierarchical_review_orchestrator.resume_hierarchical_run``)."""
    stmt = (
        select(HierarchyCheckpoint)
        .where(HierarchyCheckpoint.run_record_id == run_record_id)
        .order_by(HierarchyCheckpoint.sequence.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def mark_checkpoint_consumed(session: Session, checkpoint_id: UUID) -> HierarchyCheckpoint:
    """Mark one checkpoint as consumed (a resume attempt has been submitted against it).

    Raises ``ValueError`` if the checkpoint does not exist or was already consumed -- a second
    resume attempt against the identical checkpoint is a stale/duplicate submission, never
    silently accepted (idempotent review submission is instead achieved one layer up, by never
    re-deciding an already-decided pending item -- see
    ``app.persistence.hierarchy_review_decision.submit_review_decision``).
    """
    row = session.get(HierarchyCheckpoint, checkpoint_id)
    if row is None:
        raise ValueError(f"no HierarchyCheckpoint with id {checkpoint_id}")
    if row.consumed_at is not None:
        raise ValueError(f"HierarchyCheckpoint {checkpoint_id} was already consumed")
    row.consumed_at = datetime.now(UTC)
    session.flush()
    return row


__all__ = [
    "create_hierarchy_checkpoint",
    "get_current_checkpoint_for_run",
    "mark_checkpoint_consumed",
]
