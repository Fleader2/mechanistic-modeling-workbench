"""TimeSeriesDataset, TimeSeriesMeasurementColumn, TimeSeriesDatasetRow: a saved,
structured import of a time-series experimental dataset workbook (Downloadable Two-Tab Excel
Template increment). See ``docs/25_time_series_dataset_import_increment.md``.

``TimeSeriesDataset`` is 1:1 with a ``DatasetReference`` row (reused as this import's own
catalog entry -- see that model's own module docstring), carrying every structured Metadata-tab
field. Every one of those fields is nullable: a blank field is an honest, disclosed gap (its
own non-blocking finding in ``validation_findings``), never fabricated, never a reason this row
cannot exist (task instructions: "do not invent sample identities, replicate assignments,
dates, or units"). Immutable once created -- no ``updated_at`` column, and no persistence
function in this repository ever issues an ``UPDATE`` against any of these three tables
(task instructions: "explicit save, and read-only reopening").

``TimeSeriesMeasurementColumn`` and ``TimeSeriesDatasetRow`` are pure decomposition of one
import event, with no independent existence apart from their own ``TimeSeriesDataset`` --
``CASCADE``, mirroring ``module_boundary_port``'s own identical precedent. ``TimeSeriesDataset``
itself is ``RESTRICT`` from ``DatasetReference`` -- a durable, independently-meaningful
scientific record, the same precedent ``ModuleExecutionSnapshot`` already set.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
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
from app.models.dataset_reference import DatasetReference
from app.models.enums import MeasurementValueStatus

_MEASUREMENT_VALUE_STATUS = Enum(
    MeasurementValueStatus, name="measurement_value_status", create_type=False
)


class TimeSeriesDataset(Base):
    """One saved time-series dataset import -- 1:1 with its own ``DatasetReference`` catalog
    entry, immutable once created."""

    __tablename__ = "time_series_dataset"
    __table_args__ = (
        UniqueConstraint(
            "dataset_reference_id", name="uq_time_series_dataset_dataset_reference_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    dataset_reference_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dataset_reference.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    template_version: Mapped[str] = mapped_column(String, nullable=False)

    #: As literally present in the Metadata tab -- ``None`` if left blank (the catalog's own
    #: ``DatasetReference.name`` carries the display name actually used, which falls back to
    #: the uploaded filename when this is ``None``; see ``app.persistence.time_series_dataset``).
    dataset_name: Mapped[str | None] = mapped_column(String)
    #: A raw string, deliberately never a ``Date`` column -- enforcing a parseable date format
    #: would mean either fabricating one or rejecting an honest, ambiguous entry (task
    #: instructions: "do not invent ... dates").
    experimental_date: Mapped[str | None] = mapped_column(String)
    organism: Mapped[str | None] = mapped_column(String)
    cell_type: Mapped[str | None] = mapped_column(String)
    strain: Mapped[str | None] = mapped_column(String)
    experiment_type: Mapped[str | None] = mapped_column(String)
    measurement_type: Mapped[str | None] = mapped_column(String)
    scientific_objective: Mapped[str | None] = mapped_column(Text)
    conditions_treatments: Mapped[str | None] = mapped_column(Text)
    assay: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[str | None] = mapped_column(Text)
    processing_normalization: Mapped[str | None] = mapped_column(Text)
    time_unit: Mapped[str | None] = mapped_column(String)

    #: JSON string: ``[{"condition_id": ..., "description": ...}, ...]`` from the Metadata
    #: tab's own Condition / treatment legend sub-table. ``None`` if that sub-table was empty.
    condition_legend: Mapped[str | None] = mapped_column(Text)

    #: JSON string: every ``app.time_series.parser.Finding`` computed at save time, persisted
    #: verbatim -- a reopen shows exactly what was found *then*, never silently re-derived
    #: against a parser that may have since changed.
    validation_findings: Mapped[str] = mapped_column(Text, nullable=False)

    saved_by: Mapped[str | None] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    dataset_reference: Mapped[DatasetReference] = relationship()
    measurement_columns: Mapped[list[TimeSeriesMeasurementColumn]] = relationship(
        back_populates="dataset", order_by="TimeSeriesMeasurementColumn.display_order"
    )
    rows: Mapped[list[TimeSeriesDatasetRow]] = relationship(
        back_populates="dataset", order_by="TimeSeriesDatasetRow.row_index"
    )


class TimeSeriesMeasurementColumn(Base):
    """One Data-tab measurement column -- its exact, original header text, never renamed or
    matched to a model/species name (task instructions: "preserve original measurement-column
    names exactly ... model-specific alias mapping is a later increment")."""

    __tablename__ = "time_series_measurement_column"
    __table_args__ = (
        UniqueConstraint(
            "time_series_dataset_id",
            "column_name",
            name="uq_time_series_measurement_column_dataset_id_column_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    time_series_dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("time_series_dataset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    column_name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Original left-to-right position in the Data tab (0-based) -- preserved for faithful
    #: round-trip display, never alphabetized or otherwise reordered.
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    #: ``False`` means this column appeared in the Data tab but had no matching row in the
    #: Metadata tab's own measurement column definitions -- its unit is genuinely unknown, not
    #: merely unrecorded here.
    declared_in_metadata: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    dataset: Mapped[TimeSeriesDataset] = relationship(back_populates="measurement_columns")


class TimeSeriesDatasetRow(Base):
    """One Data-tab data row -- one timepoint/sample observation."""

    __tablename__ = "time_series_dataset_row"
    __table_args__ = (
        UniqueConstraint(
            "time_series_dataset_id",
            "row_index",
            name="uq_time_series_dataset_row_dataset_id_row_index",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    time_series_dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("time_series_dataset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Original row order in the Data tab (0-based, counting only non-blank rows) -- preserved
    #: for faithful round-trip display.
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Raw, as-uploaded identifiers -- ``None`` if that Data-tab column was absent entirely
    #: ("where applicable"; task instructions), never fabricated.
    sample_id: Mapped[str | None] = mapped_column(String)
    condition_id: Mapped[str | None] = mapped_column(String)
    biological_replicate: Mapped[str | None] = mapped_column(String)
    technical_replicate: Mapped[str | None] = mapped_column(String)

    time_status: Mapped[MeasurementValueStatus] = mapped_column(
        _MEASUREMENT_VALUE_STATUS, nullable=False
    )
    time_value: Mapped[Decimal | None] = mapped_column(Numeric)
    time_raw: Mapped[str | None] = mapped_column(String)

    #: JSON string: ``{"<exact column name>": {"status": ..., "value": float|null, "raw":
    #: string|null}, ...}`` -- one entry per ``TimeSeriesMeasurementColumn`` of this dataset.
    measurements: Mapped[str] = mapped_column(Text, nullable=False)

    dataset: Mapped[TimeSeriesDataset] = relationship(back_populates="rows")


__all__ = ["TimeSeriesDataset", "TimeSeriesDatasetRow", "TimeSeriesMeasurementColumn"]
