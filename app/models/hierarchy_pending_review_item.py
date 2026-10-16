"""HierarchyPendingReviewItem: one module awaiting human review, as its own first-class,
queryable row -- never only an entry inside the opaque ``HierarchyCheckpoint.payload`` blob a
UI would have to parse to render anything.

See ``docs/05_hierarchical_review_resume.md``. One ``HierarchyCheckpoint`` owns any number of
these, copied verbatim from that checkpoint's own ``pending_review_modules`` entries at pause
time -- this table never re-derives or re-scores anything.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.hierarchy_checkpoint import HierarchyCheckpoint


class HierarchyPendingReviewItem(Base):
    """One pending-review module of one ``HierarchyCheckpoint``."""

    __tablename__ = "hierarchy_pending_review_item"
    __table_args__ = (
        UniqueConstraint(
            "hierarchy_checkpoint_id",
            "pending_id",
            name="uq_hierarchy_pending_review_item_checkpoint_id_pending_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    hierarchy_checkpoint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("hierarchy_checkpoint.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: The harness's own ``pending_id`` string -- the stable identifier a review decision is
    #: keyed by, unique within one checkpoint, never globally (content-addressed module ids can
    #: recur across different parent nodes).
    pending_id: Mapped[str] = mapped_column(Text, nullable=False)
    #: The harness's own ``node_id`` of the parent node this module belongs to.
    parent_node_id: Mapped[str] = mapped_column(Text, nullable=False)
    #: The content-addressed module id awaiting review.
    module_id: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    reaction_count: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    hierarchy_checkpoint: Mapped[HierarchyCheckpoint] = relationship()


__all__ = ["HierarchyPendingReviewItem"]
