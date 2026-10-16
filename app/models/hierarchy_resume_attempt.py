"""HierarchyResumeAttempt: a durable record of one attempt to resume one
``HierarchyCheckpoint`` (Crash-Safe Resume increment).

See ``docs/06_crash_safe_resume.md``. Exactly one attempt row exists per checkpoint
(``hierarchy_checkpoint_id`` is itself unique) -- this is the idempotency key: a repeated
resume request for the identical checkpoint always finds and reuses this same row rather than
creating a parallel one, and a retry after failure/staleness transitions this same row back to
``IN_PROGRESS`` rather than ever duplicating it.

This row's own ``IN_PROGRESS`` status is committed durably *before* the harness resume
subprocess is invoked (``app.orchestration.hierarchical_review_orchestrator
.resume_hierarchical_run``'s own deliberate, disclosed exception to this repository's general
"the caller commits" convention) -- so a crash during that external call always leaves a
truthful, recoverable trail: either this row is durably ``IN_PROGRESS`` (and nothing else from
that attempt was persisted, since the harness call and the result's own persistence happen in
one all-or-nothing transaction after this commit), or it already reached ``FAILED``, in which
case it is safe to retry.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import HierarchyResumeAttemptStatus
from app.models.hierarchy_checkpoint import HierarchyCheckpoint

_HIERARCHY_RESUME_ATTEMPT_STATUS = Enum(
    HierarchyResumeAttemptStatus, name="hierarchy_resume_attempt_status", create_type=False
)


class HierarchyResumeAttempt(Base):
    """One (and, by construction, only one) resume attempt for one ``HierarchyCheckpoint``."""

    __tablename__ = "hierarchy_resume_attempt"
    __table_args__ = (
        UniqueConstraint(
            "hierarchy_checkpoint_id", name="uq_hierarchy_resume_attempt_checkpoint_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    hierarchy_checkpoint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("hierarchy_checkpoint.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[HierarchyResumeAttemptStatus] = mapped_column(
        _HIERARCHY_RESUME_ATTEMPT_STATUS,
        nullable=False,
        default=HierarchyResumeAttemptStatus.PENDING,
        server_default=HierarchyResumeAttemptStatus.PENDING.value,
    )
    #: Incremented every time this row transitions into ``IN_PROGRESS`` -- a plain audit trail
    #: of how many times this checkpoint's own resume has been (re)tried, never itself load-
    #: bearing for any decision this system makes.
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Set (overwritten) every time this row transitions into ``IN_PROGRESS`` -- the basis for
    #: ``app.persistence.hierarchy_resume_attempt.is_attempt_stale``.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    hierarchy_checkpoint: Mapped[HierarchyCheckpoint] = relationship()


__all__ = ["HierarchyResumeAttempt"]
