"""InitialConditionsDataset, InitialConditionsMeasurementColumn,
InitialConditionsMeasurementUncertaintyColumn, InitialConditionsDatasetRow: a saved, structured
import of an initial-conditions dataset workbook -- Initial-Conditions Dataset Import increment.
See ``docs/36_initial_conditions_dataset_import_increment.md``.

Mirrors ``app.models.time_series_dataset`` exactly in spirit (1:1 with its own
``DatasetReference``, immutable once created, every field nullable so a blank is an honest,
disclosed gap rather than a reason this row cannot exist), but a deliberately *separate* table
family, never a generalization of it: this dataset type has no time axis, no condition axis,
and no independent-variable columns, and its own Data tab is long-format (one row per target,
e.g. one protein or metabolite) rather than wide-format (one row per sample).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.dataset_reference import DatasetReference
from app.models.enums import UncertaintyStatisticKind

_UNCERTAINTY_STATISTIC_KIND = Enum(
    UncertaintyStatisticKind, name="uncertainty_statistic_kind", create_type=False
)


class InitialConditionsDataset(Base):
    """One saved initial-conditions dataset import -- 1:1 with its own ``DatasetReference``
    catalog entry, immutable once created."""

    __tablename__ = "initial_conditions_dataset"
    __table_args__ = (
        UniqueConstraint(
            "dataset_reference_id", name="uq_initial_conditions_dataset_dataset_reference_id"
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

    dataset_name: Mapped[str | None] = mapped_column(String)
    experimental_date: Mapped[str | None] = mapped_column(String)
    organism: Mapped[str | None] = mapped_column(String)
    #: The one field that distinguishes one cell type's own initial-conditions dataset from
    #: another's -- the same model can be evaluated against different cell types by pinning a
    #: different ``InitialConditionsDataset`` per experiment (task instructions: "a single
    #: model can be used to predict the behavior of different cell types by using a different
    #: set of initial data").
    cell_type: Mapped[str | None] = mapped_column(String)
    strain: Mapped[str | None] = mapped_column(String)
    experiment_type: Mapped[str | None] = mapped_column(String)
    measurement_type: Mapped[str | None] = mapped_column(String)
    scientific_objective: Mapped[str | None] = mapped_column(Text)
    conditions_treatments: Mapped[str | None] = mapped_column(Text)
    assay: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[str | None] = mapped_column(Text)
    processing_normalization: Mapped[str | None] = mapped_column(Text)

    #: JSON string: every ``app.initial_conditions.parser.Finding`` computed at save time,
    #: persisted verbatim -- a reopen shows exactly what was found *then*.
    validation_findings: Mapped[str] = mapped_column(Text, nullable=False)

    saved_by: Mapped[str | None] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    dataset_reference: Mapped[DatasetReference] = relationship()
    measurement_columns: Mapped[list[InitialConditionsMeasurementColumn]] = relationship(
        back_populates="dataset", order_by="InitialConditionsMeasurementColumn.display_order"
    )
    measurement_uncertainty_columns: Mapped[list[InitialConditionsMeasurementUncertaintyColumn]] = (
        relationship(
            back_populates="dataset",
            order_by="InitialConditionsMeasurementUncertaintyColumn.display_order",
        )
    )
    rows: Mapped[list[InitialConditionsDatasetRow]] = relationship(
        back_populates="dataset", order_by="InitialConditionsDatasetRow.row_index"
    )


class InitialConditionsMeasurementColumn(Base):
    """One Data-tab measurement column (e.g. "Abundance") -- its exact, original header text,
    never renamed or matched to a model/species name here."""

    __tablename__ = "initial_conditions_measurement_column"
    __table_args__ = (
        UniqueConstraint(
            "initial_conditions_dataset_id",
            "column_name",
            name="uq_ic_measurement_column_dataset_id_column_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    initial_conditions_dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("initial_conditions_dataset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    column_name: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    declared_in_metadata: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    dataset: Mapped[InitialConditionsDataset] = relationship(back_populates="measurement_columns")


class InitialConditionsMeasurementUncertaintyColumn(Base):
    """One Data-tab column explicitly declared, in the Metadata tab's own "Measurement
    uncertainty definitions" sub-table, as already-computed, observation-level uncertainty for
    one specific measurement column -- mirrors ``TimeSeriesMeasurementUncertaintyColumn``
    exactly."""

    __tablename__ = "initial_conditions_measurement_uncertainty_column"
    __table_args__ = (
        UniqueConstraint(
            "initial_conditions_dataset_id",
            "column_name",
            name="uq_ic_measurement_uncertainty_column_dataset_id_column_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    initial_conditions_dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("initial_conditions_dataset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    column_name: Mapped[str] = mapped_column(Text, nullable=False)
    measurement_column_name: Mapped[str] = mapped_column(Text, nullable=False)
    statistic_kind: Mapped[UncertaintyStatisticKind] = mapped_column(
        _UNCERTAINTY_STATISTIC_KIND, nullable=False
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)

    dataset: Mapped[InitialConditionsDataset] = relationship(
        back_populates="measurement_uncertainty_columns"
    )


class InitialConditionsDatasetRow(Base):
    """One Data-tab data row -- one target's (species/metabolite/parameter) own initial value.
    Unlike ``TimeSeriesDatasetRow`` there is no sample_id/condition_id/replicate/time axis --
    ``target_name`` is this row's own one identifying field."""

    __tablename__ = "initial_conditions_dataset_row"
    __table_args__ = (
        UniqueConstraint(
            "initial_conditions_dataset_id",
            "row_index",
            name="uq_ic_dataset_row_dataset_id_row_index",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    initial_conditions_dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("initial_conditions_dataset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    row_index: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Raw, as-uploaded target identifier -- ``None`` only if the cell was genuinely blank
    #: (disclosed as a non-blocking finding at parse time), never fabricated. Duplicate values
    #: across rows of the same dataset are allowed (also disclosed) -- see
    #: ``app.initial_conditions.parser`` module docstring.
    target_name: Mapped[str | None] = mapped_column(String)

    #: JSON string: ``{"<exact column name>": {"status": ..., "value": float|null, "raw":
    #: string|null}, ...}`` -- one entry per ``InitialConditionsMeasurementColumn``.
    measurements: Mapped[str] = mapped_column(Text, nullable=False)

    #: Identical shape to ``measurements`` -- one entry per
    #: ``InitialConditionsMeasurementUncertaintyColumn``, keyed by the measurement column name
    #: it describes.
    measurement_uncertainty: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )

    dataset: Mapped[InitialConditionsDataset] = relationship(back_populates="rows")


__all__ = [
    "InitialConditionsDataset",
    "InitialConditionsDatasetRow",
    "InitialConditionsMeasurementColumn",
    "InitialConditionsMeasurementUncertaintyColumn",
]
