"""Response/request schemas for the Initial-Conditions Dataset Import increment's own alias
mapping (``docs/36_initial_conditions_dataset_import_increment.md``). Mirrors
``app.schemas.dataset_model_alias_mapping`` exactly in spirit, adapted for row-value (not
column-header) mapping against either a species or a parameter catalog -- see
``app.models.initial_conditions_alias_mapping`` module docstring for why.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import (
    AliasMappingAssignmentStatus,
    AliasMappingUnitFinding,
    InitialConditionsAliasMappingTargetKind,
    ModelParameterCatalogStatus,
    ModelParameterKind,
    ModelSpeciesCatalogStatus,
)
from app.models.initial_conditions_alias_mapping import InitialConditionsAliasMappingRevision
from app.models.initial_conditions_dataset import InitialConditionsDataset
from app.models.model_parameter_catalog import ModelParameterCatalog
from app.models.model_species_catalog import ModelSpeciesCatalog

#: How many of a target's own real values to show alongside it in the picker.
_SAMPLE_VALUE_COUNT = 3


class InitialConditionsAliasMappingSpeciesOption(BaseModel):
    antimony_species_id: str
    display_name: str | None
    compartment_id: str
    compartment_name: str | None

    @classmethod
    def from_species_list(
        cls, catalog: ModelSpeciesCatalog
    ) -> list[InitialConditionsAliasMappingSpeciesOption]:
        return [
            cls(
                antimony_species_id=s.antimony_species_id,
                display_name=s.display_name,
                compartment_id=s.compartment_id,
                compartment_name=s.compartment_name,
            )
            for s in catalog.species
        ]


class InitialConditionsAliasMappingParameterOption(BaseModel):
    antimony_parameter_id: str
    display_name: str | None
    unit: str | None

    @classmethod
    def from_parameter_list(
        cls, catalog: ModelParameterCatalog
    ) -> list[InitialConditionsAliasMappingParameterOption]:
        return [
            cls(
                antimony_parameter_id=p.antimony_parameter_id,
                display_name=p.display_name,
                unit=p.unit,
            )
            for p in catalog.parameters
            if p.kind is ModelParameterKind.INDEPENDENT
        ]


class InitialConditionsAliasMappingTargetInfo(BaseModel):
    """One distinct ``target_name``'s own source identity -- name verbatim, plus a few real
    values for recognition."""

    target_name: str
    unit: str | None
    sample_values: list[str]

    @classmethod
    def from_dataset(
        cls, dataset: InitialConditionsDataset
    ) -> list[InitialConditionsAliasMappingTargetInfo]:
        column_unit = dataset.measurement_columns[0].unit if dataset.measurement_columns else None
        by_target: dict[str, list[str]] = {}
        for row in dataset.rows:
            if row.target_name is None:
                continue
            samples = by_target.setdefault(row.target_name, [])
            if len(samples) >= _SAMPLE_VALUE_COUNT:
                continue
            measurements = json.loads(row.measurements)
            for measurement in measurements.values():
                if measurement["status"] == "MEASURED":
                    samples.append(str(measurement["value"]))
                elif measurement["raw"] is not None:
                    samples.append(measurement["raw"])
                break
        return [
            cls(target_name=name, unit=column_unit, sample_values=samples)
            for name, samples in sorted(by_target.items())
        ]


class InitialConditionsAliasMappingAssignmentItem(BaseModel):
    target_name: str
    status: AliasMappingAssignmentStatus
    target_kind: InitialConditionsAliasMappingTargetKind | None
    target_id: str | None
    unit_finding: AliasMappingUnitFinding | None
    unit_comparison_detail: dict | None

    @classmethod
    def from_revision(
        cls, revision: InitialConditionsAliasMappingRevision
    ) -> list[InitialConditionsAliasMappingAssignmentItem]:
        return [
            cls(
                target_name=a.target_name,
                status=a.status,
                target_kind=a.target_kind,
                target_id=a.target_id,
                unit_finding=a.unit_finding,
                unit_comparison_detail=(
                    json.loads(a.unit_comparison_detail)
                    if a.unit_comparison_detail is not None
                    else None
                ),
            )
            for a in revision.assignments
        ]


class InitialConditionsAliasMappingRevisionSummary(BaseModel):
    revision_number: int
    saved_by: str | None
    created_at: datetime
    assigned_count: int
    skipped_count: int
    unresolved_count: int

    @classmethod
    def from_revision(
        cls, revision: InitialConditionsAliasMappingRevision
    ) -> InitialConditionsAliasMappingRevisionSummary:
        return cls(
            revision_number=revision.revision_number,
            saved_by=revision.saved_by,
            created_at=revision.created_at,
            assigned_count=sum(
                1 for a in revision.assignments if a.status == AliasMappingAssignmentStatus.ASSIGNED
            ),
            skipped_count=sum(
                1 for a in revision.assignments if a.status == AliasMappingAssignmentStatus.SKIPPED
            ),
            unresolved_count=sum(
                1
                for a in revision.assignments
                if a.status == AliasMappingAssignmentStatus.UNRESOLVED
            ),
        )


class InitialConditionsAliasMappingDetail(BaseModel):
    """The full state needed to render the initial-conditions alias-mapping screen."""

    initial_conditions_dataset_id: UUID
    model_id: UUID
    model_species_catalog_status: ModelSpeciesCatalogStatus | None
    model_species_catalog_unavailable_reason: str | None
    model_parameter_catalog_status: ModelParameterCatalogStatus | None
    model_parameter_catalog_unavailable_reason: str | None
    available_species: list[InitialConditionsAliasMappingSpeciesOption]
    available_parameters: list[InitialConditionsAliasMappingParameterOption]
    targets: list[InitialConditionsAliasMappingTargetInfo]
    revision_number: int
    saved_by: str | None
    created_at: datetime | None
    assignments: list[InitialConditionsAliasMappingAssignmentItem]

    @classmethod
    def build(
        cls,
        *,
        dataset: InitialConditionsDataset,
        model_id: UUID,
        species_catalog: ModelSpeciesCatalog | None,
        parameter_catalog: ModelParameterCatalog | None,
        revision: InitialConditionsAliasMappingRevision | None,
    ) -> InitialConditionsAliasMappingDetail:
        return cls(
            initial_conditions_dataset_id=dataset.id,
            model_id=model_id,
            model_species_catalog_status=(
                species_catalog.status if species_catalog is not None else None
            ),
            model_species_catalog_unavailable_reason=(
                species_catalog.unavailable_reason if species_catalog is not None else None
            ),
            model_parameter_catalog_status=(
                parameter_catalog.status if parameter_catalog is not None else None
            ),
            model_parameter_catalog_unavailable_reason=(
                parameter_catalog.unavailable_reason if parameter_catalog is not None else None
            ),
            available_species=(
                InitialConditionsAliasMappingSpeciesOption.from_species_list(species_catalog)
                if species_catalog is not None
                and species_catalog.status is ModelSpeciesCatalogStatus.AVAILABLE
                else []
            ),
            available_parameters=(
                InitialConditionsAliasMappingParameterOption.from_parameter_list(parameter_catalog)
                if parameter_catalog is not None
                and parameter_catalog.status is ModelParameterCatalogStatus.AVAILABLE
                else []
            ),
            targets=InitialConditionsAliasMappingTargetInfo.from_dataset(dataset),
            revision_number=0 if revision is None else revision.revision_number,
            saved_by=None if revision is None else revision.saved_by,
            created_at=None if revision is None else revision.created_at,
            assignments=(
                []
                if revision is None
                else InitialConditionsAliasMappingAssignmentItem.from_revision(revision)
            ),
        )


class SaveInitialConditionsAliasMappingAssignmentRequest(BaseModel):
    target_name: str
    status: AliasMappingAssignmentStatus
    target_kind: InitialConditionsAliasMappingTargetKind | None = None
    target_id: str | None = None


class SaveInitialConditionsAliasMappingRequest(BaseModel):
    expected_revision_number: int
    assignments: list[SaveInitialConditionsAliasMappingAssignmentRequest]
    saved_by: str | None = None


__all__ = [
    "InitialConditionsAliasMappingAssignmentItem",
    "InitialConditionsAliasMappingDetail",
    "InitialConditionsAliasMappingParameterOption",
    "InitialConditionsAliasMappingRevisionSummary",
    "InitialConditionsAliasMappingSpeciesOption",
    "InitialConditionsAliasMappingTargetInfo",
    "SaveInitialConditionsAliasMappingAssignmentRequest",
    "SaveInitialConditionsAliasMappingRequest",
]
