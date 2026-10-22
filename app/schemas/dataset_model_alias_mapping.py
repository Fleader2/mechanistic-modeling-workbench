"""Response/request schemas for the Model-Specific Alias Mapping increment
(``docs/27_model_specific_alias_mapping_increment.md``)."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.dataset_model_alias_mapping import DatasetModelAliasMappingRevision
from app.models.enums import (
    AliasMappingAssignmentStatus,
    AliasMappingUnitFinding,
    ModelSpeciesCatalogStatus,
)
from app.models.model_species_catalog import ModelSpeciesCatalog
from app.models.time_series_dataset import TimeSeriesDataset

#: How many of a column's own real values to show alongside it in the picker -- enough for a
#: scientist to recognize the data, never the whole column (that's the dataset's own reopen
#: screen's job).
_SAMPLE_VALUE_COUNT = 3


class AliasMappingSpeciesOption(BaseModel):
    """One real, verified species a measurement column may be assigned to."""

    antimony_species_id: str
    display_name: str | None
    compartment_id: str
    compartment_name: str | None

    @classmethod
    def from_species_list(cls, catalog: ModelSpeciesCatalog) -> list[AliasMappingSpeciesOption]:
        return [
            cls(
                antimony_species_id=s.antimony_species_id,
                display_name=s.display_name,
                compartment_id=s.compartment_id,
                compartment_name=s.compartment_name,
            )
            for s in catalog.species
        ]


class AliasMappingColumnInfo(BaseModel):
    """One measurement column's own source identity -- name/unit verbatim, plus a few real
    values for recognition. Never a species-mapping target's own information."""

    column_name: str
    unit: str | None
    sample_values: list[str]

    @classmethod
    def from_dataset(cls, dataset: TimeSeriesDataset) -> list[AliasMappingColumnInfo]:
        columns = []
        for column in dataset.measurement_columns:
            samples: list[str] = []
            for row in dataset.rows:
                if len(samples) >= _SAMPLE_VALUE_COUNT:
                    break
                measurement = json.loads(row.measurements).get(column.column_name)
                if measurement is None:
                    continue
                if measurement["status"] == "MEASURED":
                    samples.append(str(measurement["value"]))
                elif measurement["raw"] is not None:
                    samples.append(measurement["raw"])
            columns.append(
                cls(column_name=column.column_name, unit=column.unit, sample_values=samples)
            )
        return columns


class AliasMappingAssignmentItem(BaseModel):
    column_name: str
    status: AliasMappingAssignmentStatus
    target_antimony_species_id: str | None
    unit_finding: AliasMappingUnitFinding | None
    unit_comparison_detail: dict | None

    @classmethod
    def from_revision(
        cls, revision: DatasetModelAliasMappingRevision
    ) -> list[AliasMappingAssignmentItem]:
        return [
            cls(
                column_name=a.column_name,
                status=a.status,
                target_antimony_species_id=a.target_antimony_species_id,
                unit_finding=a.unit_finding,
                unit_comparison_detail=(
                    json.loads(a.unit_comparison_detail)
                    if a.unit_comparison_detail is not None
                    else None
                ),
            )
            for a in revision.assignments
        ]


class AliasMappingRevisionSummary(BaseModel):
    """One row of the revision-history list."""

    revision_number: int
    saved_by: str | None
    created_at: datetime
    assigned_count: int
    skipped_count: int
    unresolved_count: int

    @classmethod
    def from_revision(
        cls, revision: DatasetModelAliasMappingRevision
    ) -> AliasMappingRevisionSummary:
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


class AliasMappingDetail(BaseModel):
    """The full state needed to render the alias-mapping screen: the current (or, when
    reopening history, one specific past) revision's own content, plus everything needed to
    build the picker -- never a model/species fact this screen invents itself."""

    time_series_dataset_id: UUID
    model_id: UUID
    model_species_catalog_status: ModelSpeciesCatalogStatus | None
    model_species_catalog_unavailable_reason: str | None
    available_species: list[AliasMappingSpeciesOption]
    columns: list[AliasMappingColumnInfo]
    revision_number: int
    saved_by: str | None
    created_at: datetime | None
    assignments: list[AliasMappingAssignmentItem]

    @classmethod
    def build(
        cls,
        *,
        dataset: TimeSeriesDataset,
        model_id: UUID,
        catalog: ModelSpeciesCatalog | None,
        revision: DatasetModelAliasMappingRevision | None,
    ) -> AliasMappingDetail:
        return cls(
            time_series_dataset_id=dataset.id,
            model_id=model_id,
            model_species_catalog_status=catalog.status if catalog is not None else None,
            model_species_catalog_unavailable_reason=(
                catalog.unavailable_reason if catalog is not None else None
            ),
            available_species=(
                AliasMappingSpeciesOption.from_species_list(catalog)
                if catalog is not None and catalog.status == ModelSpeciesCatalogStatus.AVAILABLE
                else []
            ),
            columns=AliasMappingColumnInfo.from_dataset(dataset),
            revision_number=0 if revision is None else revision.revision_number,
            saved_by=None if revision is None else revision.saved_by,
            created_at=None if revision is None else revision.created_at,
            assignments=(
                [] if revision is None else AliasMappingAssignmentItem.from_revision(revision)
            ),
        )


class SaveAliasMappingAssignmentRequest(BaseModel):
    column_name: str
    status: AliasMappingAssignmentStatus
    target_antimony_species_id: str | None = None


class SaveAliasMappingRequest(BaseModel):
    expected_revision_number: int
    assignments: list[SaveAliasMappingAssignmentRequest]
    saved_by: str | None = None


__all__ = [
    "AliasMappingAssignmentItem",
    "AliasMappingColumnInfo",
    "AliasMappingDetail",
    "AliasMappingRevisionSummary",
    "AliasMappingSpeciesOption",
    "SaveAliasMappingAssignmentRequest",
    "SaveAliasMappingRequest",
]
