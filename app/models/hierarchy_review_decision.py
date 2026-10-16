"""HierarchyReviewDecision: one user's APPROVE/REJECT decision for one
``HierarchyPendingReviewItem``.

See ``docs/05_hierarchical_review_resume.md``. ``pending_review_item_id`` is unique: exactly
one decision ever exists per pending item -- resubmitting the identical decision is an
idempotent no-op, and resubmitting a *different* decision for an already-decided item is
rejected as a conflict (see ``app.persistence.hierarchy_review_decision.submit_review_decision``
for both rules; nothing here enforces that at the database level beyond the uniqueness itself).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import HierarchyReviewDecisionValue
from app.models.hierarchy_pending_review_item import HierarchyPendingReviewItem

_HIERARCHY_REVIEW_DECISION_VALUE = Enum(
    HierarchyReviewDecisionValue, name="hierarchy_review_decision_value", create_type=False
)


class HierarchyReviewDecision(Base):
    """One reviewer decision for one ``HierarchyPendingReviewItem``."""

    __tablename__ = "hierarchy_review_decision"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    pending_review_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("hierarchy_pending_review_item.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    decision: Mapped[HierarchyReviewDecisionValue] = mapped_column(
        _HIERARCHY_REVIEW_DECISION_VALUE, nullable=False
    )
    #: Free-text identifier of who decided -- no authentication/user-account system exists yet
    #: in this Workbench, so this is never a foreign key.
    decided_by: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    pending_review_item: Mapped[HierarchyPendingReviewItem] = relationship()


__all__ = ["HierarchyReviewDecision"]
