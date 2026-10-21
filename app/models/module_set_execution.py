"""Module-Set Edited-Module Materialization increment, Phase B: boundary review and execution
for one module-set member's own current, possibly-edited reaction selection.

Deliberately separate from (and never mutating) ``ModuleSetMember``/``ModuleSetDraftMember``
(the task's own "must not rewrite saved membership" rule) and from ``ModuleBoundaryPort``
(scoped to a real, unedited ``ModelModule`` -- a module-set member's own boundary review needs
its own, independently-versioned record, since its reaction selection is a module-set-version's
own curated fact, not the real module's).

``ModuleSetMemberReview`` is the one small, mutable row per member -- never the member itself --
whose ``review_version`` is the optimistic-concurrency token a boundary-decision submission (or
a simulation submission) must echo back, mirroring ``ModuleSetDraft.edit_version``'s own
identical role from the Manual Editing increment. ``ModuleSetMemberBoundaryPort`` is this
review's own child rows -- structurally identical to ``ModuleBoundaryPort`` (reusing the
identical enums), but keyed to the review, not to a ``model_module_id``.

The actual simulation *run* reuses existing infrastructure wherever possible, not a new table:
``RunRecord`` (its own new, nullable ``module_set_member_id`` column) for the job/run state
machine, and ``ModuleExecutionSnapshot`` (``execution_kind=SIMULATION``, already schema-ready
and never previously wired up) for the immutable, pinned input snapshot -- see
``app.persistence.module_set_execution`` for exactly how each is used.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    ModuleBoundaryResolutionStatus,
    ModuleBoundaryTreatmentType,
    ModulePortDirection,
)
from app.models.module_set import ModuleSetMember

_MODULE_PORT_DIRECTION = Enum(ModulePortDirection, name="module_port_direction", create_type=False)
_MODULE_BOUNDARY_TREATMENT_TYPE = Enum(
    ModuleBoundaryTreatmentType, name="module_boundary_treatment_type", create_type=False
)
_MODULE_BOUNDARY_RESOLUTION_STATUS = Enum(
    ModuleBoundaryResolutionStatus, name="module_boundary_resolution_status", create_type=False
)


class ModuleSetMemberReview(Base):
    """One module-set member's own mutable boundary-review state -- 1:1 with
    ``ModuleSetMember``, never the member row itself. ``review_version`` is incremented on
    every successful boundary-decision submission; a caller must echo back the value it last
    observed, or the submission is rejected as stale (the identical discipline
    ``ModuleSetDraft.edit_version`` already established for membership edits)."""

    __tablename__ = "module_set_member_review"
    __table_args__ = (
        UniqueConstraint(
            "module_set_member_id", name="uq_module_set_member_review_module_set_member_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    module_set_member_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("module_set_member.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    review_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Set every time candidate boundary ports are (re)derived -- ``NULL`` until the first
    #: derivation. Re-deriving against the identical, immutable reaction selection is
    #: deterministic (confirmed by the underlying structural algorithm), so this exists for
    #: disclosure ("last checked at ...") rather than because derivation can actually drift.
    derived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    module_set_member: Mapped[ModuleSetMember] = relationship()
    ports: Mapped[list[ModuleSetMemberBoundaryPort]] = relationship(
        back_populates="review", cascade="all, delete-orphan", passive_deletes=True
    )


class ModuleSetMemberBoundaryPort(Base):
    """One boundary-condition treatment decision for one ``(review, species_id, direction)``
    triple -- structurally identical to ``ModuleBoundaryPort``, reusing its own enums, but
    scoped to a module-set member's own review rather than a real ``model_module_id``."""

    __tablename__ = "module_set_member_boundary_port"
    __table_args__ = (
        UniqueConstraint(
            "review_id",
            "species_id",
            "direction",
            name="uq_module_set_member_boundary_port_review_species_direction",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    review_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("module_set_member_review.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    species_id: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[ModulePortDirection] = mapped_column(_MODULE_PORT_DIRECTION, nullable=False)

    treatment_type: Mapped[ModuleBoundaryTreatmentType] = mapped_column(
        _MODULE_BOUNDARY_TREATMENT_TYPE,
        nullable=False,
        default=ModuleBoundaryTreatmentType.UNRESOLVED,
        server_default=ModuleBoundaryTreatmentType.UNRESOLVED.value,
    )
    resolution_status: Mapped[ModuleBoundaryResolutionStatus] = mapped_column(
        _MODULE_BOUNDARY_RESOLUTION_STATUS,
        nullable=False,
        default=ModuleBoundaryResolutionStatus.PENDING_REVIEW,
        server_default=ModuleBoundaryResolutionStatus.PENDING_REVIEW.value,
    )

    initial_value: Mapped[Decimal | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String)
    decided_by: Mapped[str | None] = mapped_column(String)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    review: Mapped[ModuleSetMemberReview] = relationship(back_populates="ports")


__all__ = ["ModuleSetMemberBoundaryPort", "ModuleSetMemberReview"]
