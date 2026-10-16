"""HierarchyResumeAttempt persistence.

**Idempotent on ``hierarchy_checkpoint_id``** (database-enforced uniqueness, backed here by
``session.begin_nested()`` race handling identical to ``app.persistence.model.persist_model``'s
own convention): a repeated resume request for the identical checkpoint always finds and reuses
this same row.

No scientific logic lives here, and no transaction boundaries are decided here either -- every
function in this module only ``flush()``es; deciding *when* to durably ``commit()`` the
``IN_PROGRESS`` transition (the actual crash-safety mechanism) is
``app.orchestration.hierarchical_review_orchestrator.resume_hierarchical_run``'s own,
deliberate responsibility.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import HierarchyResumeAttemptStatus
from app.models.hierarchy_resume_attempt import HierarchyResumeAttempt

#: How long an ``IN_PROGRESS`` attempt may run before it is considered stale (crashed, not
#: merely slow) and therefore safe to retry. Deliberately independent of -- and somewhat more
#: generous than -- the harness's own subprocess timeout
#: (``agent-integration-harness/app/harness/recursive_candidate_search``'s sibling client
#: constant, 900s): the Workbench should never need to know that internal
#: harness implementation detail to make its own staleness judgment.
STALE_RESUME_ATTEMPT_THRESHOLD_SECONDS = 1200.0


def get_attempt_for_checkpoint(
    session: Session, hierarchy_checkpoint_id: UUID
) -> HierarchyResumeAttempt | None:
    """The attempt row for one checkpoint, or ``None`` if none has ever been created.
    Read-only."""
    return session.execute(
        select(HierarchyResumeAttempt).where(
            HierarchyResumeAttempt.hierarchy_checkpoint_id == hierarchy_checkpoint_id
        )
    ).scalar_one_or_none()


def get_or_create_resume_attempt(
    *, hierarchy_checkpoint_id: UUID, session: Session
) -> HierarchyResumeAttempt:
    """The checkpoint's own attempt row, creating a fresh ``PENDING`` one if none exists yet."""
    existing = get_attempt_for_checkpoint(session, hierarchy_checkpoint_id)
    if existing is not None:
        return existing

    try:
        with session.begin_nested():
            row = HierarchyResumeAttempt(hierarchy_checkpoint_id=hierarchy_checkpoint_id)
            session.add(row)
            session.flush()
    except IntegrityError:
        raced = get_attempt_for_checkpoint(session, hierarchy_checkpoint_id)
        if raced is not None:
            return raced
        raise

    return row


def mark_attempt_in_progress(
    attempt_id: UUID, session: Session, *, force: bool = False
) -> HierarchyResumeAttempt:
    """Transition an attempt to ``IN_PROGRESS`` -- allowed from ``PENDING``/``FAILED``
    unconditionally, and from ``IN_PROGRESS`` itself only when ``force=True`` (the caller's own
    affirmative statement that it already checked ``is_attempt_stale`` and decided this retry
    is safe -- this function itself never judges staleness). Raises ``ValueError`` for an
    unforced ``IN_PROGRESS`` -> ``IN_PROGRESS`` call, or if the attempt does not exist.

    Always bumps ``attempt_count`` and overwrites ``started_at`` with the current time, and
    clears ``error_summary``/``completed_at`` from any prior failed attempt.
    """
    row = session.get(HierarchyResumeAttempt, attempt_id)
    if row is None:
        raise ValueError(f"no HierarchyResumeAttempt with id {attempt_id}")
    if row.status is HierarchyResumeAttemptStatus.IN_PROGRESS and not force:
        raise ValueError(
            f"HierarchyResumeAttempt {attempt_id} is already IN_PROGRESS -- pass force=True "
            "only after confirming it is stale"
        )

    row.status = HierarchyResumeAttemptStatus.IN_PROGRESS
    row.attempt_count += 1
    row.started_at = datetime.now(UTC)
    row.completed_at = None
    row.error_summary = None
    session.flush()
    return row


def mark_attempt_succeeded(attempt_id: UUID, session: Session) -> HierarchyResumeAttempt:
    """Transition an attempt to ``SUCCEEDED``. Raises ``ValueError`` if it is not currently
    ``IN_PROGRESS``, or does not exist."""
    row = session.get(HierarchyResumeAttempt, attempt_id)
    if row is None:
        raise ValueError(f"no HierarchyResumeAttempt with id {attempt_id}")
    if row.status is not HierarchyResumeAttemptStatus.IN_PROGRESS:
        raise ValueError(f"HierarchyResumeAttempt {attempt_id} is {row.status}, not IN_PROGRESS")
    row.status = HierarchyResumeAttemptStatus.SUCCEEDED
    row.completed_at = datetime.now(UTC)
    session.flush()
    return row


def mark_attempt_failed(
    attempt_id: UUID, session: Session, *, error_summary: str
) -> HierarchyResumeAttempt:
    """Transition an attempt to ``FAILED`` (itself retryable -- see
    ``HierarchyResumeAttemptStatus``'s own docstring). Raises ``ValueError`` if it is not
    currently ``IN_PROGRESS``, or does not exist."""
    row = session.get(HierarchyResumeAttempt, attempt_id)
    if row is None:
        raise ValueError(f"no HierarchyResumeAttempt with id {attempt_id}")
    if row.status is not HierarchyResumeAttemptStatus.IN_PROGRESS:
        raise ValueError(f"HierarchyResumeAttempt {attempt_id} is {row.status}, not IN_PROGRESS")
    row.status = HierarchyResumeAttemptStatus.FAILED
    row.completed_at = datetime.now(UTC)
    row.error_summary = error_summary
    session.flush()
    return row


def is_attempt_stale(
    attempt: HierarchyResumeAttempt,
    *,
    now: datetime | None = None,
    threshold_seconds: float = STALE_RESUME_ATTEMPT_THRESHOLD_SECONDS,
) -> bool:
    """``True`` only for an ``IN_PROGRESS`` attempt whose own ``started_at`` is further in the
    past than ``threshold_seconds`` -- i.e. it has already run longer than any real harness
    resume call plausibly takes, so it must have crashed rather than merely being slow. A
    non-``IN_PROGRESS`` attempt is never stale (staleness is specifically about a call believed
    to still be in flight)."""
    if attempt.status is not HierarchyResumeAttemptStatus.IN_PROGRESS:
        return False
    if attempt.started_at is None:
        return False
    now = now if now is not None else datetime.now(UTC)
    return (now - attempt.started_at).total_seconds() > threshold_seconds


__all__ = [
    "STALE_RESUME_ATTEMPT_THRESHOLD_SECONDS",
    "get_attempt_for_checkpoint",
    "get_or_create_resume_attempt",
    "is_attempt_stale",
    "mark_attempt_failed",
    "mark_attempt_in_progress",
    "mark_attempt_succeeded",
]
