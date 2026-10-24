"""InitialConditionsAliasMappingRevision, InitialConditionsAliasMappingAssignment: a scientist's
own assignment of each initial-conditions dataset row's own ``target_name`` to an exact, real
Antimony species or independent parameter identifier (or an explicit decision to skip it), for
one specific (``InitialConditionsDataset``, ``Model``) pair. Initial-Conditions Dataset Import
increment -- see ``docs/36_initial_conditions_dataset_import_increment.md``.

Mirrors ``app.models.dataset_model_alias_mapping`` exactly in spirit (immutable revisions, never
in-place edits; "current" is simply the highest ``revision_number``), with two real
differences, both load-bearing:

* **Maps row *values*, not column headers.** The time-series alias mapping assigns a model
  species to one of the dataset's own *measurement columns* (the dataset is wide-format: one
  column per species). This dataset is long-format (one row per target), so the thing being
  mapped is each distinct ``target_name`` value actually present in the dataset's own rows --
  ``DatasetModelAliasMappingAssignment.column_name`` here becomes ``target_name``.
* **Targets a species or an independent parameter, never species alone.** ``target_kind``
  records which real, verified catalog ``target_id`` was actually confirmed against
  (``app.models.enums.InitialConditionsAliasMappingTargetKind``) -- never left implicit, and
  never silently resolved when a name happens to collide between the two catalogs (see
  ``app.persistence.initial_conditions_alias_mapping``).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    AliasMappingAssignmentStatus,
    AliasMappingUnitFinding,
    InitialConditionsAliasMappingTargetKind,
)
from app.models.initial_conditions_dataset import InitialConditionsDataset
from app.models.model import Model
from app.models.model_parameter_catalog import ModelParameterCatalog
from app.models.model_species_catalog import ModelSpeciesCatalog

_ALIAS_MAPPING_ASSIGNMENT_STATUS = Enum(
    AliasMappingAssignmentStatus, name="alias_mapping_assignment_status", create_type=False
)
_ALIAS_MAPPING_UNIT_FINDING = Enum(
    AliasMappingUnitFinding, name="alias_mapping_unit_finding", create_type=False
)
_INITIAL_CONDITIONS_ALIAS_MAPPING_TARGET_KIND = Enum(
    InitialConditionsAliasMappingTargetKind,
    name="initial_conditions_alias_mapping_target_kind",
    create_type=False,
)


class InitialConditionsAliasMappingRevision(Base):
    """One immutable, complete snapshot of every distinct ``target_name``'s own mapping status
    for one (dataset, model) pair, at one point in time."""

    __tablename__ = "initial_conditions_alias_mapping_revision"
    __table_args__ = (
        UniqueConstraint(
            "initial_conditions_dataset_id",
            "model_id",
            "revision_number",
            name="uq_ic_alias_mapping_revision_dataset_model_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    initial_conditions_dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("initial_conditions_dataset.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: Which specific, verified species catalog every ``SPECIES``-kind target id in this
    #: revision was validated against -- ``None`` only if that catalog was not ``AVAILABLE`` at
    #: save time (a revision may still be created from the parameter catalog alone; see
    #: ``app.persistence.initial_conditions_alias_mapping``).
    model_species_catalog_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_species_catalog.id", ondelete="RESTRICT"),
        index=True,
    )
    #: The parameter-catalog mirror of ``model_species_catalog_id`` -- ``None`` only if that
    #: catalog was not ``AVAILABLE`` at save time.
    model_parameter_catalog_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_parameter_catalog.id", ondelete="RESTRICT"),
        index=True,
    )

    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)

    saved_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    initial_conditions_dataset: Mapped[InitialConditionsDataset] = relationship()
    model: Mapped[Model] = relationship()
    model_species_catalog: Mapped[ModelSpeciesCatalog | None] = relationship()
    model_parameter_catalog: Mapped[ModelParameterCatalog | None] = relationship()
    assignments: Mapped[list[InitialConditionsAliasMappingAssignment]] = relationship(
        back_populates="revision",
        order_by="InitialConditionsAliasMappingAssignment.target_name",
        passive_deletes=True,
    )


class InitialConditionsAliasMappingAssignment(Base):
    """One distinct ``target_name``'s own mapping status within one revision -- every distinct
    ``target_name`` actually present in the dataset's own rows gets exactly one row in every
    revision."""

    __tablename__ = "initial_conditions_alias_mapping_assignment"
    __table_args__ = (
        UniqueConstraint(
            "revision_id", "target_name", name="uq_ic_alias_mapping_assignment_revision_target"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("initial_conditions_alias_mapping_revision.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: The dataset's own exact, original ``target_name`` value, verbatim.
    target_name: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[AliasMappingAssignmentStatus] = mapped_column(
        _ALIAS_MAPPING_ASSIGNMENT_STATUS, nullable=False
    )

    #: Set only when ``status == ASSIGNED`` -- which real, verified catalog ``target_id`` was
    #: confirmed against. Never inferred when both ``status`` fields are unset.
    target_kind: Mapped[InitialConditionsAliasMappingTargetKind | None] = mapped_column(
        _INITIAL_CONDITIONS_ALIAS_MAPPING_TARGET_KIND
    )
    #: Set only when ``status == ASSIGNED`` -- the real, compiled Antimony species or
    #: independent-parameter identifier this ``target_name`` actually is.
    target_id: Mapped[str | None] = mapped_column(Text)

    unit_finding: Mapped[AliasMappingUnitFinding | None] = mapped_column(
        _ALIAS_MAPPING_UNIT_FINDING
    )
    unit_comparison_detail: Mapped[str | None] = mapped_column(Text)

    revision: Mapped[InitialConditionsAliasMappingRevision] = relationship(
        back_populates="assignments"
    )


__all__ = [
    "InitialConditionsAliasMappingAssignment",
    "InitialConditionsAliasMappingRevision",
]
