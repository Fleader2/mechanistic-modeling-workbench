"""ModuleBoundaryPort: durable, first-class record of one boundary-condition treatment
decision for one species crossing a ``ModelModule``'s own boundary (Boundary-Condition
Semantics increment).

See ``docs/08_boundary_condition_semantics.md``. Mirrors Agent 2's own existing
``app.agent2.types.ModulePort`` shape (task instructions §3: "reuse existing ModulePort
semantics where possible") -- ``species_id``/``direction`` are the identical fields; this
table's own addition is the richer ``treatment_type``/``resolution_status``/provenance
columns Agent 2's own type has no need for (it only ever asks "is this externally
controlled, yes or no" -- a question this table answers only once a human has actually
resolved *which* explicit treatment applies).

``CASCADE``-deleted from ``model_module``: unlike ``model_module`` itself (a durable,
independently-referenceable execution target, ``RESTRICT`` throughout), a boundary port has no
independent meaning apart from the module it describes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    ModuleBoundaryResolutionStatus,
    ModuleBoundaryTreatmentType,
    ModulePortDirection,
)
from app.models.model_module import ModelModule

_MODULE_PORT_DIRECTION = Enum(ModulePortDirection, name="module_port_direction", create_type=False)
_MODULE_BOUNDARY_TREATMENT_TYPE = Enum(
    ModuleBoundaryTreatmentType, name="module_boundary_treatment_type", create_type=False
)
_MODULE_BOUNDARY_RESOLUTION_STATUS = Enum(
    ModuleBoundaryResolutionStatus, name="module_boundary_resolution_status", create_type=False
)


class ModuleBoundaryPort(Base):
    """One boundary-condition treatment decision for one ``(model_module, species_id,
    direction)`` triple."""

    __tablename__ = "module_boundary_port"
    __table_args__ = (
        UniqueConstraint(
            "model_module_id",
            "species_id",
            "direction",
            name="uq_module_boundary_port_module_species_direction",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    model_module_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_module.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: A stable, deterministic string -- never Agent 2's own runtime-generated port id (this
    #: row exists before any Agent 2 call is ever made); content-addressed from
    #: ``(model_module_id, species_id, direction)``, see
    #: ``app.persistence.module_boundary_port``'s own construction.
    port_id: Mapped[str] = mapped_column(Text, nullable=False)
    #: The boundary entity identity -- the content-addressed species id crossing this module's
    #: own boundary.
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

    #: Populated only for ``EXTERNALLY_CONTROLLED``/``PRESCRIBED_INPUT`` -- never fabricated
    #: when unknown (task instructions: "do not fabricate boundary values").
    initial_value: Mapped[Decimal | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String)
    #: Where ``initial_value`` (if any) came from, e.g. ``"USER_SUPPLIED"`` -- free text, never
    #: a closed vocabulary (this increment never auto-derives a value, only a candidate port).
    value_source: Mapped[str | None] = mapped_column(String)

    #: Provenance/evidence for this decision -- free text, no closed vocabulary.
    provenance_notes: Mapped[str | None] = mapped_column(Text)
    #: ``True`` only for a row this increment's own automatic derivation created and no human
    #: has touched since -- never itself overwritten by a later derivation pass (see
    #: ``app.persistence.module_boundary_port.derive_candidate_boundary_ports``'s own
    #: docstring).
    derived_automatically: Mapped[bool] = mapped_column(nullable=False, default=True)
    #: Free-text identifier of who decided -- no authentication/user-account system exists yet
    #: in this Workbench (identical convention to ``HierarchyReviewDecision.decided_by``).
    decided_by: Mapped[str | None] = mapped_column(String)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    model_module: Mapped[ModelModule] = relationship()


__all__ = ["ModuleBoundaryPort"]
