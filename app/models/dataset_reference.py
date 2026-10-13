"""DatasetReference: uploaded or external dataset catalog metadata.

See ``docs/02_database_schema.md`` ("Table: dataset_reference").

A catalog entry *about* a dataset (experimental observations, calibration
targets, validation holdout data, ...), never the dataset's own content.
Like every other cross-repo reference in this schema, any link to an
Agent-1-curated record (e.g. an ``ExperimentalContext``/
``QuantitativeObservation`` row) is a copied ``(entity_type, entity_id)``
pair, never a foreign key.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.project import Project
from app.models.subproject import Subproject


class DatasetReference(Base):
    """One catalog entry for an uploaded or externally-referenced dataset."""

    __tablename__ = "dataset_reference"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    subproject_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subproject.id", ondelete="RESTRICT"), index=True
    )

    #: Open vocabulary (e.g. "experimental_observation", "calibration_target",
    #: "validation_holdout") -- never a closed enum, since the set of dataset
    #: kinds this catalog can hold is expected to grow.
    dataset_type: Mapped[str] = mapped_column(String, nullable=False)

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    #: A copied Agent 1 entity reference (e.g. an ExperimentalContext id) --
    #: never a foreign key (see module docstring).
    agent1_entity_type: Mapped[str | None] = mapped_column(String)
    agent1_entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    biological_context_notes: Mapped[str | None] = mapped_column(Text)

    #: Opaque pointer to the dataset's own file/blob. Never parsed here.
    artifact_reference: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String)
    version_label: Mapped[str | None] = mapped_column(String)

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship()
    subproject: Mapped[Subproject | None] = relationship()


__all__ = ["DatasetReference"]
