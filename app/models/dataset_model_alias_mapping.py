"""DatasetModelAliasMappingRevision, DatasetModelAliasMappingAssignment: a scientist's own
assignment of each time-series dataset measurement column to an exact, real Antimony species
identifier (or an explicit decision to skip it), for one specific
(``TimeSeriesDataset``, ``Model``) pair. See ``docs/27_model_specific_alias_mapping
_increment.md``.

**Revisions, never in-place edits.** Every save creates a new, immutable
``DatasetModelAliasMappingRevision`` row (``revision_number`` incrementing per
(``time_series_dataset_id``, ``model_id``) pair) -- a complete snapshot of every one of the
dataset's own measurement columns' status, never a sparse diff. "Current" is simply the row
with the highest ``revision_number`` for that pair (``app.persistence
.dataset_model_alias_mapping.get_current_mapping_revision``); no separate pointer row is
needed. A save pinned to a stale ``expected_revision_number`` (someone/something else saved a
newer revision first) is rejected, mirroring the Module-Set Edited-Module Materialization
increment's own identical ``expected_review_version`` discipline exactly.

**Pinned to one specific, verified species catalog.** ``model_species_catalog_id`` records
*which* ``ModelSpeciesCatalog`` (never just ``model_id`` alone) every target id in this
revision was validated against -- a revision can only ever be created while that catalog's own
``status`` is ``AVAILABLE`` (enforced in ``app.persistence.dataset_model_alias_mapping``, never
here); there is no "mapping saved against an unavailable catalog" state to represent.

Immutable once created: no persistence function in this repository ever issues an ``UPDATE``
against either table.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AliasMappingAssignmentStatus, AliasMappingUnitFinding
from app.models.model import Model
from app.models.model_species_catalog import ModelSpeciesCatalog
from app.models.time_series_dataset import TimeSeriesDataset

_ALIAS_MAPPING_ASSIGNMENT_STATUS = Enum(
    AliasMappingAssignmentStatus, name="alias_mapping_assignment_status", create_type=False
)
_ALIAS_MAPPING_UNIT_FINDING = Enum(
    AliasMappingUnitFinding, name="alias_mapping_unit_finding", create_type=False
)


class DatasetModelAliasMappingRevision(Base):
    """One immutable, complete snapshot of every measurement column's own mapping status for
    one (dataset, model) pair, at one point in time."""

    __tablename__ = "dataset_model_alias_mapping_revision"
    __table_args__ = (
        UniqueConstraint(
            "time_series_dataset_id",
            "model_id",
            "revision_number",
            name="uq_alias_mapping_revision_dataset_model_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    time_series_dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("time_series_dataset.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: Which specific, verified catalog every target id in this revision was validated
    #: against -- see module docstring.
    model_species_catalog_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_species_catalog.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    #: 1, 2, 3, ... per (time_series_dataset_id, model_id) pair -- never reused, never reset.
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)

    saved_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    time_series_dataset: Mapped[TimeSeriesDataset] = relationship()
    model: Mapped[Model] = relationship()
    model_species_catalog: Mapped[ModelSpeciesCatalog] = relationship()
    assignments: Mapped[list[DatasetModelAliasMappingAssignment]] = relationship(
        back_populates="revision",
        order_by="DatasetModelAliasMappingAssignment.column_name",
        passive_deletes=True,
    )


class DatasetModelAliasMappingAssignment(Base):
    """One measurement column's own mapping status within one revision -- every measurement
    column of the dataset gets exactly one row in every revision, never silently omitted."""

    __tablename__ = "dataset_model_alias_mapping_assignment"
    __table_args__ = (
        UniqueConstraint(
            "revision_id", "column_name", name="uq_alias_mapping_assignment_revision_column"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dataset_model_alias_mapping_revision.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: The dataset's own exact, original measurement-column name, verbatim -- never the
    #: structural columns (sample_id/condition_id/time/replicates), which are not species-
    #: mapping targets at all and never appear here (enforced by construction: this value is
    #: always one of the dataset's own ``TimeSeriesMeasurementColumn.column_name`` values,
    #: which never include a structural column in the first place).
    column_name: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[AliasMappingAssignmentStatus] = mapped_column(
        _ALIAS_MAPPING_ASSIGNMENT_STATUS, nullable=False
    )

    #: Set only when ``status == ASSIGNED`` -- the real, compiled Antimony species identifier
    #: this column's own data is. Always validated, at save time, against the pinned catalog's
    #: own ``ModelSpecies.antimony_species_id`` set -- never an unverified string.
    target_antimony_species_id: Mapped[str | None] = mapped_column(Text)

    #: Set only when ``status == ASSIGNED`` -- ``app.units.compare_units`` run between this
    #: column's own declared unit and the target species' own unit, collapsed to the one
    #: three-way distinction task instructions asked for. ``unit_comparison_detail`` retains
    #: the full, un-collapsed ``compare_units`` result (JSON), never discarded.
    unit_finding: Mapped[AliasMappingUnitFinding | None] = mapped_column(
        _ALIAS_MAPPING_UNIT_FINDING
    )
    unit_comparison_detail: Mapped[str | None] = mapped_column(Text)

    revision: Mapped[DatasetModelAliasMappingRevision] = relationship(
        back_populates="assignments"
    )


__all__ = ["DatasetModelAliasMappingAssignment", "DatasetModelAliasMappingRevision"]
