"""DatasetModelAliasMappingRevision persistence: validate and save one complete alias-mapping
revision for one (dataset, model) pair, atomically. See
``docs/27_model_specific_alias_mapping_increment.md``.

``save_mapping_revision`` is the single write path. It always builds a *complete* snapshot --
every one of the dataset's own measurement columns gets exactly one assignment row in the new
revision, defaulting to ``UNRESOLVED`` for any column the caller's own input did not mention --
never a sparse diff that could leave a column's own status ambiguous between revisions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.dataset_model_alias_mapping import (
    DatasetModelAliasMappingAssignment,
    DatasetModelAliasMappingRevision,
)
from app.models.enums import (
    AliasMappingAssignmentStatus,
    AliasMappingUnitFinding,
    ModelSpeciesCatalogStatus,
)
from app.models.model_species_catalog import ModelSpeciesCatalog
from app.models.time_series_dataset import TimeSeriesDataset
from app.units import UnitComparisonStatus, compare_units


class MappingRevisionStaleError(ValueError):
    """Raised when ``expected_revision_number`` no longer matches the current revision --
    someone/something else saved a newer one first. Carries the real current revision (or
    ``None`` if no revision has ever been saved) so a caller can report exactly what changed."""

    def __init__(self, current_revision: DatasetModelAliasMappingRevision | None) -> None:
        self.current_revision = current_revision
        current_number = 0 if current_revision is None else current_revision.revision_number
        super().__init__(
            f"expected revision {current_number} is no longer current -- a newer revision "
            "already exists"
        )


class MappingSpeciesCatalogUnavailableError(ValueError):
    """Raised when the target model has no ``AVAILABLE`` species catalog -- there is nothing
    real to validate a target id against, so no revision is ever created (task instructions:
    never build a misleading target picker; the identical discipline applies to saving)."""


class InvalidMappingColumnError(ValueError):
    """Raised when an assignment names a column that is not one of the dataset's own real
    measurement columns -- never silently ignored or coerced."""

    def __init__(self, unknown_column_names: list[str]) -> None:
        self.unknown_column_names = unknown_column_names
        super().__init__(f"not a real measurement column of this dataset: {unknown_column_names!r}")


class InvalidMappingTargetError(ValueError):
    """Raised when an ``ASSIGNED`` assignment names a species id that is not a real member of
    the pinned, verified species catalog -- server-side validation, never trusted from the
    client alone (task instructions: "validate assigned identifiers server-side")."""

    def __init__(self, invalid_target_ids: list[str]) -> None:
        self.invalid_target_ids = invalid_target_ids
        super().__init__(
            f"not a real species in this model's own verified catalog: {invalid_target_ids!r}"
        )


class DuplicateMappingTargetError(ValueError):
    """Raised when two or more columns are assigned to the identical target species id in the
    same revision -- never silently combined (task instructions: "define and document
    duplicate-target handling; never silently combine columns"). Carries
    ``{target_antimony_species_id: [column_name, ...]}`` for every conflict found."""

    def __init__(self, conflicts: dict[str, list[str]]) -> None:
        self.conflicts = conflicts
        super().__init__(f"more than one column assigned to the identical target: {conflicts!r}")


@dataclass(frozen=True, slots=True)
class AssignmentInput:
    column_name: str
    status: AliasMappingAssignmentStatus
    target_antimony_species_id: str | None = None


def get_current_mapping_revision(
    session: Session, *, time_series_dataset_id: UUID, model_id: UUID
) -> DatasetModelAliasMappingRevision | None:
    """The highest-``revision_number`` row for this (dataset, model) pair, with its own
    assignments eagerly loaded, or ``None`` if never saved. Read-only."""
    return session.execute(
        select(DatasetModelAliasMappingRevision)
        .where(
            DatasetModelAliasMappingRevision.time_series_dataset_id == time_series_dataset_id,
            DatasetModelAliasMappingRevision.model_id == model_id,
        )
        .options(selectinload(DatasetModelAliasMappingRevision.assignments))
        .order_by(DatasetModelAliasMappingRevision.revision_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def list_mapping_revisions(
    session: Session, *, time_series_dataset_id: UUID, model_id: UUID
) -> list[DatasetModelAliasMappingRevision]:
    """Every revision ever saved for this (dataset, model) pair, newest first. Read-only."""
    return list(
        session.scalars(
            select(DatasetModelAliasMappingRevision)
            .where(
                DatasetModelAliasMappingRevision.time_series_dataset_id
                == time_series_dataset_id,
                DatasetModelAliasMappingRevision.model_id == model_id,
            )
            .options(selectinload(DatasetModelAliasMappingRevision.assignments))
            .order_by(DatasetModelAliasMappingRevision.revision_number.desc())
        )
    )


def get_mapping_revision(
    session: Session, *, time_series_dataset_id: UUID, model_id: UUID, revision_number: int
) -> DatasetModelAliasMappingRevision | None:
    """One specific, historical revision -- read-only reopening, exactly as saved."""
    return session.execute(
        select(DatasetModelAliasMappingRevision)
        .where(
            DatasetModelAliasMappingRevision.time_series_dataset_id == time_series_dataset_id,
            DatasetModelAliasMappingRevision.model_id == model_id,
            DatasetModelAliasMappingRevision.revision_number == revision_number,
        )
        .options(selectinload(DatasetModelAliasMappingRevision.assignments))
    ).scalar_one_or_none()


def _unit_finding(column_unit: str | None, species_unit: str | None) -> tuple[str, str]:
    """``(AliasMappingUnitFinding value, full compare_units() result as JSON)``."""
    comparison = compare_units(column_unit, species_unit)
    if comparison["status"] == UnitComparisonStatus.COMPATIBLE.value:
        finding = AliasMappingUnitFinding.COMPATIBLE
    elif comparison["status"] == UnitComparisonStatus.INCOMPATIBLE.value:
        finding = AliasMappingUnitFinding.INCOMPATIBLE
    else:  # MISSING or MALFORMED on either side -- cannot tell either way
        finding = AliasMappingUnitFinding.UNKNOWN
    return finding.value, json.dumps(comparison)


def save_mapping_revision(
    *,
    session: Session,
    dataset: TimeSeriesDataset,
    model_species_catalog: ModelSpeciesCatalog,
    assignments: list[AssignmentInput],
    expected_revision_number: int,
    saved_by: str | None = None,
) -> DatasetModelAliasMappingRevision:
    """Validate and save one complete alias-mapping revision.

    Raises ``MappingSpeciesCatalogUnavailableError`` if ``model_species_catalog.status`` is not
    ``AVAILABLE``; ``MappingRevisionStaleError`` if ``expected_revision_number`` no longer
    matches the current revision; ``InvalidMappingColumnError``/``InvalidMappingTargetError``/
    ``DuplicateMappingTargetError`` for the respective validation failures. Nothing is ever
    partially saved -- every check runs before any row is written.
    """
    if model_species_catalog.status is not ModelSpeciesCatalogStatus.AVAILABLE:
        raise MappingSpeciesCatalogUnavailableError(
            f"model species catalog is {model_species_catalog.status.value}, not AVAILABLE -- "
            f"reason: {model_species_catalog.unavailable_reason}"
        )

    current = get_current_mapping_revision(
        session, time_series_dataset_id=dataset.id, model_id=model_species_catalog.model_id
    )
    current_number = 0 if current is None else current.revision_number
    if current_number != expected_revision_number:
        raise MappingRevisionStaleError(current)

    real_column_names = {c.column_name for c in dataset.measurement_columns}
    unknown_columns = sorted({a.column_name for a in assignments} - real_column_names)
    if unknown_columns:
        raise InvalidMappingColumnError(unknown_columns)

    real_species_by_id = {s.antimony_species_id: s for s in model_species_catalog.species}
    assigned = [a for a in assignments if a.status is AliasMappingAssignmentStatus.ASSIGNED]
    invalid_targets = sorted(
        {
            a.target_antimony_species_id
            for a in assigned
            if a.target_antimony_species_id not in real_species_by_id
        }
    )
    if invalid_targets:
        raise InvalidMappingTargetError(invalid_targets)

    targets_to_columns: dict[str, list[str]] = {}
    for a in assigned:
        targets_to_columns.setdefault(a.target_antimony_species_id, []).append(a.column_name)
    conflicts = {target: cols for target, cols in targets_to_columns.items() if len(cols) > 1}
    if conflicts:
        raise DuplicateMappingTargetError(conflicts)

    assignments_by_column = {a.column_name: a for a in assignments}
    column_units = {c.column_name: c.unit for c in dataset.measurement_columns}

    with session.begin_nested():
        revision = DatasetModelAliasMappingRevision(
            time_series_dataset_id=dataset.id,
            model_id=model_species_catalog.model_id,
            model_species_catalog_id=model_species_catalog.id,
            revision_number=current_number + 1,
            saved_by=saved_by,
        )
        session.add(revision)
        session.flush()

        for column_name in sorted(real_column_names):
            input_assignment = assignments_by_column.get(column_name)
            if input_assignment is None:
                status = AliasMappingAssignmentStatus.UNRESOLVED
                target_id = None
            else:
                status = input_assignment.status
                target_id = input_assignment.target_antimony_species_id

            unit_finding = None
            unit_detail = None
            if status is AliasMappingAssignmentStatus.ASSIGNED:
                species_unit = real_species_by_id[target_id].unit
                unit_finding, unit_detail = _unit_finding(column_units[column_name], species_unit)

            session.add(
                DatasetModelAliasMappingAssignment(
                    revision_id=revision.id,
                    column_name=column_name,
                    status=status,
                    target_antimony_species_id=target_id,
                    unit_finding=unit_finding,
                    unit_comparison_detail=unit_detail,
                )
            )
        session.flush()

    return revision


__all__ = [
    "AssignmentInput",
    "DuplicateMappingTargetError",
    "InvalidMappingColumnError",
    "InvalidMappingTargetError",
    "MappingRevisionStaleError",
    "MappingSpeciesCatalogUnavailableError",
    "get_current_mapping_revision",
    "get_mapping_revision",
    "list_mapping_revisions",
    "save_mapping_revision",
]
