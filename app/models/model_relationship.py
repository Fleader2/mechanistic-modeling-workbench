"""ModelRelationship: an explicit, declared fact that two ``Model`` rows are related --
never inferred from matching names or stable identifiers. Joint Calibration Workflow design
increment (``docs/29_joint_calibration_workflow_design.md`` §3, ``docs/30
_joint_calibration_configuration_increment.md``).

Insert-only, like ``DatasetModelAliasMappingRevision``: a later declaration never edits or
supersedes an earlier one in place -- if a curator's understanding changes, a new row is added
and both remain visible, each with its own ``declared_at``/``declared_by``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ModelRelationshipKind
from app.models.model import Model

_MODEL_RELATIONSHIP_KIND = Enum(
    ModelRelationshipKind, name="model_relationship_kind", create_type=False
)


class ModelRelationship(Base):
    """One explicit, curator-declared relationship between two ``Model`` rows."""

    __tablename__ = "model_relationship"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    model_id_a: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    model_id_b: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    relationship_kind: Mapped[ModelRelationshipKind] = mapped_column(
        _MODEL_RELATIONSHIP_KIND, nullable=False
    )
    #: e.g. "no_drug" / "drug_treated" -- free text, how the curator distinguishes the two
    #: sides; never used as a matching key anywhere (docs/29's "matching names never establish
    #: identity" principle applies to these labels too).
    role_label_a: Mapped[str | None] = mapped_column(String)
    role_label_b: Mapped[str | None] = mapped_column(String)

    declared_by: Mapped[str | None] = mapped_column(String)
    declared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    model_a: Mapped[Model] = relationship(foreign_keys=[model_id_a])
    model_b: Mapped[Model] = relationship(foreign_keys=[model_id_b])


__all__ = ["ModelRelationship"]
