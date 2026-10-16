"""HierarchyCheckpoint: durable, verbatim-opaque storage of one paused hierarchical-recursion
run's own harness-owned resume state.

See ``docs/05_hierarchical_review_resume.md``. One ``RunRecord`` (``stage=RunStage.HARNESS``)
paused for human review owns any number of these over its lifetime -- append-only, one new row
per pause (the first pause, then one more per subsequent resume-then-re-pause cycle), ordered
by ``sequence``. ``payload`` is the harness's own
``app.harness.hierarchical_recursion.serialize_checkpoint(...)`` dict, stored exactly as
received: the Workbench never reinterprets, reconstructs, or re-derives anything inside it --
only passes it back unchanged to the harness's own
``resume_hierarchical_recursive_modularization`` on resume. ``checkpoint_version``/
``policy_version``/``hierarchy_id`` are denormalized, read-only copies of three of that
payload's own top-level fields, carried as their own columns purely so a UI/service can
inspect/filter them without parsing JSON -- never a second source of truth for them.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.run_record import RunRecord


class HierarchyCheckpoint(Base):
    """One harness-owned ``HierarchyCheckpoint`` snapshot, persisted verbatim under the
    ``RunRecord`` that produced it."""

    __tablename__ = "hierarchy_checkpoint"
    __table_args__ = (
        UniqueConstraint(
            "run_record_id", "sequence", name="uq_hierarchy_checkpoint_run_record_id_sequence"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    run_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("run_record.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: 0 for the first pause of this run; incremented once per subsequent resume-then-re-pause
    #: cycle. The *current* checkpoint for a run is the row with the maximum ``sequence``.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Denormalized copies of ``payload``'s own top-level fields -- see module docstring.
    checkpoint_version: Mapped[str] = mapped_column(String, nullable=False)
    policy_version: Mapped[str] = mapped_column(String, nullable=False)
    hierarchy_id: Mapped[str] = mapped_column(String, nullable=False)

    #: The harness's own ``serialize_checkpoint(...)`` dict, JSON-encoded verbatim. Opaque:
    #: never parsed or interpreted by this repository except to pass back, unchanged, to the
    #: harness's own resume call.
    payload: Mapped[str] = mapped_column(Text, nullable=False)

    #: ``NULL`` while this checkpoint is still the current, resumable one for its run; set once
    #: a resume attempt has actually been submitted against it -- a second resume submission
    #: against an already-consumed checkpoint is rejected as stale (see
    #: ``app.persistence.hierarchy_checkpoint.mark_checkpoint_consumed``).
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run_record: Mapped[RunRecord] = relationship()


__all__ = ["HierarchyCheckpoint"]
