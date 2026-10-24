"""Response schemas for the Initial-Conditions Dataset Import increment
(``docs/36_initial_conditions_dataset_import_increment.md``). Mirrors
``app.schemas.time_series_dataset`` exactly in spirit; no request body schema is needed here
either -- both the preview and save endpoints take the workbook itself as a multipart file
upload.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.initial_conditions.parser import Finding, ParsedInitialConditionsWorkbook
from app.models.enums import MeasurementValueStatus, UncertaintyStatisticKind
from app.models.initial_conditions_dataset import InitialConditionsDataset

_METADATA_KEYS = (
    "template_version",
    "dataset_name",
    "experimental_date",
    "organism",
    "cell_type",
    "strain",
    "experiment_type",
    "measurement_type",
    "scientific_objective",
    "conditions_treatments",
    "assay",
    "provenance",
    "processing_normalization",
)


class InitialConditionsFindingItem(BaseModel):
    code: str
    severity: str
    message: str
    field: str | None = None
    column_name: str | None = None
    row_index: int | None = None

    @classmethod
    def from_finding(cls, finding: Finding) -> InitialConditionsFindingItem:
        return cls(
            code=finding.code,
            severity=finding.severity,
            message=finding.message,
            field=finding.field,
            column_name=finding.column_name,
            row_index=finding.row_index,
        )

    @classmethod
    def from_json_list(cls, raw: str) -> list[InitialConditionsFindingItem]:
        return [cls.model_validate(item) for item in json.loads(raw)]


class InitialConditionsMeasurementColumnItem(BaseModel):
    column_name: str
    display_order: int
    unit: str | None
    description: str | None
    declared_in_metadata: bool


class InitialConditionsMeasurementUncertaintyColumnItem(BaseModel):
    column_name: str
    measurement_column_name: str
    statistic_kind: UncertaintyStatisticKind
    display_order: int
    unit: str | None
    description: str | None


class InitialConditionsMeasurementValueItem(BaseModel):
    status: MeasurementValueStatus
    value: float | None
    raw: str | None


class InitialConditionsDataRowItem(BaseModel):
    row_index: int
    target_name: str | None
    measurements: dict[str, InitialConditionsMeasurementValueItem]
    measurement_uncertainty: dict[str, InitialConditionsMeasurementValueItem] = {}


class InitialConditionsWorkbookPreview(BaseModel):
    """What a preview call returns, and what a saved dataset's own content looks like --
    never carrying a database id (a preview was never saved)."""

    original_filename: str
    effective_dataset_name: str
    metadata: dict[str, str | None]
    measurement_columns: list[InitialConditionsMeasurementColumnItem]
    measurement_uncertainty_columns: list[InitialConditionsMeasurementUncertaintyColumnItem] = []
    rows: list[InitialConditionsDataRowItem]
    findings: list[InitialConditionsFindingItem]

    @classmethod
    def from_parsed(
        cls,
        parsed: ParsedInitialConditionsWorkbook,
        *,
        original_filename: str,
        effective_dataset_name: str,
    ) -> InitialConditionsWorkbookPreview:
        return cls(
            original_filename=original_filename,
            effective_dataset_name=effective_dataset_name,
            metadata={key: parsed.metadata.get(key) for key in _METADATA_KEYS},
            measurement_columns=[
                InitialConditionsMeasurementColumnItem(
                    column_name=c.column_name,
                    display_order=c.display_order,
                    unit=c.unit,
                    description=c.description,
                    declared_in_metadata=c.declared_in_metadata,
                )
                for c in parsed.measurement_columns
            ],
            measurement_uncertainty_columns=[
                InitialConditionsMeasurementUncertaintyColumnItem(
                    column_name=c.column_name,
                    measurement_column_name=c.measurement_column_name,
                    statistic_kind=c.statistic_kind,
                    display_order=c.display_order,
                    unit=c.unit,
                    description=c.description,
                )
                for c in parsed.measurement_uncertainty_columns
            ],
            rows=[
                InitialConditionsDataRowItem(
                    row_index=r.row_index,
                    target_name=r.target_name,
                    measurements={
                        name: InitialConditionsMeasurementValueItem(
                            status=mv.status, value=mv.value, raw=mv.raw
                        )
                        for name, mv in r.measurements.items()
                    },
                    measurement_uncertainty={
                        name: InitialConditionsMeasurementValueItem(
                            status=mv.status, value=mv.value, raw=mv.raw
                        )
                        for name, mv in r.measurement_uncertainty.items()
                    },
                )
                for r in parsed.rows
            ],
            findings=[InitialConditionsFindingItem.from_finding(f) for f in parsed.findings],
        )


class InitialConditionsDatasetDetail(BaseModel):
    """A saved dataset, read back exactly as it was saved."""

    id: UUID
    dataset_reference_id: UUID
    saved_by: str | None
    created_at: datetime
    content: InitialConditionsWorkbookPreview

    @classmethod
    def from_model(cls, dataset: InitialConditionsDataset) -> InitialConditionsDatasetDetail:
        metadata = {
            "template_version": dataset.template_version,
            "dataset_name": dataset.dataset_name,
            "experimental_date": dataset.experimental_date,
            "organism": dataset.organism,
            "cell_type": dataset.cell_type,
            "strain": dataset.strain,
            "experiment_type": dataset.experiment_type,
            "measurement_type": dataset.measurement_type,
            "scientific_objective": dataset.scientific_objective,
            "conditions_treatments": dataset.conditions_treatments,
            "assay": dataset.assay,
            "provenance": dataset.provenance,
            "processing_normalization": dataset.processing_normalization,
        }
        measurement_columns = [
            InitialConditionsMeasurementColumnItem(
                column_name=c.column_name,
                display_order=c.display_order,
                unit=c.unit,
                description=c.description,
                declared_in_metadata=c.declared_in_metadata,
            )
            for c in dataset.measurement_columns
        ]
        measurement_uncertainty_columns = [
            InitialConditionsMeasurementUncertaintyColumnItem(
                column_name=c.column_name,
                measurement_column_name=c.measurement_column_name,
                statistic_kind=c.statistic_kind,
                display_order=c.display_order,
                unit=c.unit,
                description=c.description,
            )
            for c in dataset.measurement_uncertainty_columns
        ]
        rows = [
            InitialConditionsDataRowItem(
                row_index=r.row_index,
                target_name=r.target_name,
                measurements={
                    name: InitialConditionsMeasurementValueItem.model_validate(value)
                    for name, value in json.loads(r.measurements).items()
                },
                measurement_uncertainty={
                    name: InitialConditionsMeasurementValueItem.model_validate(value)
                    for name, value in json.loads(r.measurement_uncertainty or "{}").items()
                },
            )
            for r in dataset.rows
        ]
        content = InitialConditionsWorkbookPreview(
            original_filename=dataset.dataset_reference.name,
            effective_dataset_name=dataset.dataset_reference.name,
            metadata=metadata,
            measurement_columns=measurement_columns,
            measurement_uncertainty_columns=measurement_uncertainty_columns,
            rows=rows,
            findings=InitialConditionsFindingItem.from_json_list(dataset.validation_findings),
        )
        return cls(
            id=dataset.id,
            dataset_reference_id=dataset.dataset_reference_id,
            saved_by=dataset.saved_by,
            created_at=dataset.created_at,
            content=content,
        )


class InitialConditionsDatasetListItem(BaseModel):
    """One row of the initial-conditions datasets list screen."""

    id: UUID
    name: str
    cell_type: str | None
    organism: str | None
    row_count: int
    measurement_column_count: int
    unresolved_finding_count: int
    saved_by: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, dataset: InitialConditionsDataset) -> InitialConditionsDatasetListItem:
        findings = InitialConditionsFindingItem.from_json_list(dataset.validation_findings)
        return cls(
            id=dataset.id,
            name=dataset.dataset_reference.name,
            cell_type=dataset.cell_type,
            organism=dataset.organism,
            row_count=len(dataset.rows),
            measurement_column_count=len(dataset.measurement_columns),
            unresolved_finding_count=len(findings),
            saved_by=dataset.saved_by,
            created_at=dataset.created_at,
        )


__all__ = [
    "InitialConditionsDataRowItem",
    "InitialConditionsDatasetDetail",
    "InitialConditionsDatasetListItem",
    "InitialConditionsFindingItem",
    "InitialConditionsMeasurementColumnItem",
    "InitialConditionsMeasurementUncertaintyColumnItem",
    "InitialConditionsWorkbookPreview",
]
