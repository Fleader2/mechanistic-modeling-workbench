"""Model: Workbench metadata/reference only -- never executable content.

See ``docs/02_database_schema.md`` ("Table: model") and
``docs/01_workbench_architecture.md``.

Per the architecture audit, this table is a pointer/lineage record: "model
artifact X exists, here is its version/lineage/status," never the
executable model itself. The actual executable content lives nowhere
durable yet -- it is Agent 2's transient, in-memory object, serialized once
per run as Antimony text + a JSON mirror. ``artifact_reference`` names
wherever that output currently lives (e.g. a harness run's output path);
it is an opaque string the Workbench never parses or interprets.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ModelSourceType, ModelStatus
from app.models.subproject import Subproject

if TYPE_CHECKING:
    pass

_MODEL_SOURCE_TYPE = Enum(ModelSourceType, name="model_source_type", create_type=False)
_MODEL_STATUS = Enum(ModelStatus, name="model_status", create_type=False)


class Model(Base):
    """One model artifact *reference*/version belonging to a ``Subproject``.

    A later calibration or modification never overwrites a prior ``Model``
    row -- it creates a new row, linked via ``parent_model_id``, so model
    lineage is always reproducible.
    """

    __tablename__ = "model"
    __table_args__ = (UniqueConstraint("stable_identifier", name="uq_model_stable_identifier"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    subproject_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subproject.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    stable_identifier: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)

    source_type: Mapped[ModelSourceType] = mapped_column(_MODEL_SOURCE_TYPE, nullable=False)
    status: Mapped[ModelStatus] = mapped_column(
        _MODEL_STATUS,
        nullable=False,
        default=ModelStatus.DRAFT,
        server_default=ModelStatus.DRAFT.value,
    )

    #: Opaque pointer to wherever the actual artifact (Antimony text, SBML,
    #: a harness run's output directory, ...) currently lives. Never parsed
    #: or interpreted here.
    artifact_reference: Mapped[str | None] = mapped_column(Text)

    parent_model_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("model.id", ondelete="RESTRICT"), index=True
    )
    version_label: Mapped[str | None] = mapped_column(String)

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    subproject: Mapped[Subproject] = relationship(back_populates="models")
    parent_model: Mapped[Model | None] = relationship(remote_side="Model.id")


__all__ = ["Model"]
