"""InitialConditionsAliasMappingRevision persistence: validate and save one complete alias-
mapping revision for one (initial-conditions dataset, model) pair, atomically. Initial-
Conditions Dataset Import increment -- see
``docs/36_initial_conditions_dataset_import_increment.md``.

Mirrors ``app.persistence.dataset_model_alias_mapping`` exactly in spirit (always a complete
snapshot; never a sparse diff; every real target gets exactly one assignment row, defaulting to
``UNRESOLVED``), with the two differences the model module docstring already documents: the
thing being mapped is each distinct ``target_name`` value actually present in the dataset's own
rows (never a column header), and a target may resolve to either a real species or a real
independent parameter -- ``target_kind`` records which, and a save is rejected outright
(``AmbiguousMappingTargetError``) if a curator's own ``target_id`` happens to be a real member
of *both* catalogs at once, since silently preferring one would be exactly the kind of silent
resolution this project's own alias-mapping discipline never allows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import (
    AliasMappingAssignmentStatus,
    AliasMappingUnitFinding,
    InitialConditionsAliasMappingTargetKind,
    ModelParameterCatalogStatus,
    ModelParameterKind,
    ModelSpeciesCatalogStatus,
)
from app.models.initial_conditions_alias_mapping import (
    InitialConditionsAliasMappingAssignment,
    InitialConditionsAliasMappingRevision,
)
from app.models.initial_conditions_dataset import InitialConditionsDataset
from app.models.model_parameter_catalog import ModelParameterCatalog
from app.models.model_species_catalog import ModelSpeciesCatalog
from app.units import UnitComparisonStatus, compare_units


class MappingRevisionStaleError(ValueError):
    """Raised when ``expected_revision_number`` no longer matches the current revision."""

    def __init__(
        self, current_revision: InitialConditionsAliasMappingRevision | None
    ) -> None:
        self.current_revision = current_revision
        current_number = 0 if current_revision is None else current_revision.revision_number
        super().__init__(
            f"expected revision {current_number} is no longer current -- a newer revision "
            "already exists"
        )


class MappingCatalogsUnavailableError(ValueError):
    """Raised when neither the model's species catalog nor its parameter catalog is
    ``AVAILABLE`` -- there is nothing real to validate any target against, so no revision is
    ever created."""


class InvalidMappingTargetNameError(ValueError):
    """Raised when an assignment names a ``target_name`` that is not one of the dataset's own
    real, non-blank ``target_name`` values."""

    def __init__(self, unknown_target_names: list[str]) -> None:
        self.unknown_target_names = unknown_target_names
        super().__init__(
            f"not a real target_name of this dataset: {unknown_target_names!r}"
        )


class InvalidMappingTargetIdError(ValueError):
    """Raised when an ``ASSIGNED`` assignment names a species/parameter id that is not a real
    member of the relevant, verified catalog -- or names a real parameter whose own ``kind`` is
    ``DERIVED`` (never an independent target, identical discipline to
    ``app.persistence.calibration._validate_target_against_catalogs``)."""

    def __init__(self, invalid: list[str]) -> None:
        self.invalid = invalid
        super().__init__(f"not a real, independent target in the verified catalog(s): {invalid!r}")


class AmbiguousMappingTargetError(ValueError):
    """Raised when an ``ASSIGNED`` assignment's own ``target_id`` is a real member of *both*
    the species and the parameter catalog at once -- never silently resolved one way."""

    def __init__(self, ambiguous: list[str]) -> None:
        self.ambiguous = ambiguous
        super().__init__(
            f"matches both a real species and a real independent parameter -- must be "
            f"disambiguated, never guessed: {ambiguous!r}"
        )


class DuplicateMappingTargetIdError(ValueError):
    """Raised when two or more ``target_name`` values are assigned to the identical
    (``target_kind``, ``target_id``) pair in the same revision -- never silently combined."""

    def __init__(self, conflicts: dict[str, list[str]]) -> None:
        self.conflicts = conflicts
        super().__init__(
            f"more than one target_name assigned to the identical target: {conflicts!r}"
        )


@dataclass(frozen=True, slots=True)
class AssignmentInput:
    target_name: str
    status: AliasMappingAssignmentStatus
    target_kind: InitialConditionsAliasMappingTargetKind | None = None
    target_id: str | None = None


def get_current_mapping_revision(
    session: Session, *, initial_conditions_dataset_id: UUID, model_id: UUID
) -> InitialConditionsAliasMappingRevision | None:
    return session.execute(
        select(InitialConditionsAliasMappingRevision)
        .where(
            InitialConditionsAliasMappingRevision.initial_conditions_dataset_id
            == initial_conditions_dataset_id,
            InitialConditionsAliasMappingRevision.model_id == model_id,
        )
        .options(selectinload(InitialConditionsAliasMappingRevision.assignments))
        .order_by(InitialConditionsAliasMappingRevision.revision_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def list_mapping_revisions(
    session: Session, *, initial_conditions_dataset_id: UUID, model_id: UUID
) -> list[InitialConditionsAliasMappingRevision]:
    return list(
        session.scalars(
            select(InitialConditionsAliasMappingRevision)
            .where(
                InitialConditionsAliasMappingRevision.initial_conditions_dataset_id
                == initial_conditions_dataset_id,
                InitialConditionsAliasMappingRevision.model_id == model_id,
            )
            .options(selectinload(InitialConditionsAliasMappingRevision.assignments))
            .order_by(InitialConditionsAliasMappingRevision.revision_number.desc())
        )
    )


def get_mapping_revision(
    session: Session,
    *,
    initial_conditions_dataset_id: UUID,
    model_id: UUID,
    revision_number: int,
) -> InitialConditionsAliasMappingRevision | None:
    return session.execute(
        select(InitialConditionsAliasMappingRevision)
        .where(
            InitialConditionsAliasMappingRevision.initial_conditions_dataset_id
            == initial_conditions_dataset_id,
            InitialConditionsAliasMappingRevision.model_id == model_id,
            InitialConditionsAliasMappingRevision.revision_number == revision_number,
        )
        .options(selectinload(InitialConditionsAliasMappingRevision.assignments))
    ).scalar_one_or_none()


def _real_target_names(dataset: InitialConditionsDataset) -> set[str]:
    return {r.target_name for r in dataset.rows if r.target_name is not None}


def _unit_finding(column_unit: str | None, target_unit: str | None) -> tuple[str, str]:
    comparison = compare_units(column_unit, target_unit)
    if comparison["status"] == UnitComparisonStatus.COMPATIBLE.value:
        finding = AliasMappingUnitFinding.COMPATIBLE
    elif comparison["status"] == UnitComparisonStatus.INCOMPATIBLE.value:
        finding = AliasMappingUnitFinding.INCOMPATIBLE
    else:
        finding = AliasMappingUnitFinding.UNKNOWN
    return finding.value, json.dumps(comparison)


def save_mapping_revision(
    *,
    session: Session,
    dataset: InitialConditionsDataset,
    model_id: UUID,
    model_species_catalog: ModelSpeciesCatalog | None,
    model_parameter_catalog: ModelParameterCatalog | None,
    assignments: list[AssignmentInput],
    expected_revision_number: int,
    saved_by: str | None = None,
) -> InitialConditionsAliasMappingRevision:
    """Validate and save one complete alias-mapping revision. Nothing is ever partially saved
    -- every check runs before any row is written. See module docstring for the full error
    taxonomy."""
    species_available = (
        model_species_catalog is not None
        and model_species_catalog.status is ModelSpeciesCatalogStatus.AVAILABLE
    )
    parameters_available = (
        model_parameter_catalog is not None
        and model_parameter_catalog.status is ModelParameterCatalogStatus.AVAILABLE
    )
    if not species_available and not parameters_available:
        raise MappingCatalogsUnavailableError(
            "neither this model's species catalog nor its parameter catalog is AVAILABLE -- "
            "there is nothing real to validate a target against"
        )

    current = get_current_mapping_revision(
        session, initial_conditions_dataset_id=dataset.id, model_id=model_id
    )
    current_number = 0 if current is None else current.revision_number
    if current_number != expected_revision_number:
        raise MappingRevisionStaleError(current)

    real_target_names = _real_target_names(dataset)
    unknown_names = sorted({a.target_name for a in assignments} - real_target_names)
    if unknown_names:
        raise InvalidMappingTargetNameError(unknown_names)

    species_by_id = (
        {s.antimony_species_id: s for s in model_species_catalog.species}
        if species_available
        else {}
    )
    parameters_by_id = (
        {p.antimony_parameter_id: p for p in model_parameter_catalog.parameters}
        if parameters_available
        else {}
    )

    assigned = [a for a in assignments if a.status is AliasMappingAssignmentStatus.ASSIGNED]

    invalid: list[str] = []
    ambiguous: list[str] = []
    for a in assigned:
        in_species = a.target_id in species_by_id
        in_parameter = (
            a.target_id in parameters_by_id
            and parameters_by_id[a.target_id].kind is ModelParameterKind.INDEPENDENT
        )
        wrong_species = (
            a.target_kind is InitialConditionsAliasMappingTargetKind.SPECIES and not in_species
        )
        wrong_parameter = (
            a.target_kind is InitialConditionsAliasMappingTargetKind.PARAMETER
            and not in_parameter
        )
        if in_species and in_parameter:
            ambiguous.append(f"{a.target_name}={a.target_id!r}")
        elif wrong_species or wrong_parameter or a.target_kind is None:
            invalid.append(f"{a.target_name}={a.target_id!r}")
    if ambiguous:
        raise AmbiguousMappingTargetError(sorted(ambiguous))
    if invalid:
        raise InvalidMappingTargetIdError(sorted(invalid))

    targets_to_names: dict[tuple[str, str], list[str]] = {}
    for a in assigned:
        key = (a.target_kind.value, a.target_id)  # type: ignore[union-attr]
        targets_to_names.setdefault(key, []).append(a.target_name)
    conflicts = {
        f"{kind}:{target_id}": names
        for (kind, target_id), names in targets_to_names.items()
        if len(names) > 1
    }
    if conflicts:
        raise DuplicateMappingTargetIdError(conflicts)

    assignments_by_name = {a.target_name: a for a in assignments}
    #: The unit to compare an ``ASSIGNED`` target against -- this dataset's own first declared
    #: measurement column (in practice there is exactly one, e.g. "Abundance"); see module
    #: docstring of ``app.models.initial_conditions_dataset`` for why a target_name is never
    #: tied to a specific column the way a time-series measurement column is.
    column_unit = dataset.measurement_columns[0].unit if dataset.measurement_columns else None

    with session.begin_nested():
        revision = InitialConditionsAliasMappingRevision(
            initial_conditions_dataset_id=dataset.id,
            model_id=model_id,
            model_species_catalog_id=(
                model_species_catalog.id if species_available else None
            ),
            model_parameter_catalog_id=(
                model_parameter_catalog.id if parameters_available else None
            ),
            revision_number=current_number + 1,
            saved_by=saved_by,
        )
        session.add(revision)
        session.flush()

        for target_name in sorted(real_target_names):
            input_assignment = assignments_by_name.get(target_name)
            if input_assignment is None:
                status = AliasMappingAssignmentStatus.UNRESOLVED
                target_kind = None
                target_id = None
            else:
                status = input_assignment.status
                target_kind = input_assignment.target_kind
                target_id = input_assignment.target_id

            unit_finding = None
            unit_detail = None
            if status is AliasMappingAssignmentStatus.ASSIGNED:
                target_unit = (
                    species_by_id[target_id].unit
                    if target_kind is InitialConditionsAliasMappingTargetKind.SPECIES
                    else parameters_by_id[target_id].unit
                )
                unit_finding, unit_detail = _unit_finding(column_unit, target_unit)

            session.add(
                InitialConditionsAliasMappingAssignment(
                    revision_id=revision.id,
                    target_name=target_name,
                    status=status,
                    target_kind=target_kind,
                    target_id=target_id,
                    unit_finding=unit_finding,
                    unit_comparison_detail=unit_detail,
                )
            )
        session.flush()

    return revision


__all__ = [
    "AmbiguousMappingTargetError",
    "AssignmentInput",
    "DuplicateMappingTargetIdError",
    "InvalidMappingTargetIdError",
    "InvalidMappingTargetNameError",
    "MappingCatalogsUnavailableError",
    "MappingRevisionStaleError",
    "get_current_mapping_revision",
    "get_mapping_revision",
    "list_mapping_revisions",
    "save_mapping_revision",
]
