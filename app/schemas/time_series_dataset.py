"""Response schemas for the Downloadable Two-Tab Excel Template increment
(``docs/25_time_series_dataset_import_increment.md``). No request body schema is needed here --
both the preview and save endpoints take the workbook itself as a multipart file upload
(``UploadFile``), not JSON.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import MeasurementValueStatus
from app.models.time_series_dataset import TimeSeriesDataset
from app.time_series.parser import Finding, ParsedWorkbook

#: The ``Metadata`` tab's own scalar field keys, in template order -- mirrors
#: ``app.time_series.contract.METADATA_FIELDS``'s own ``key``s, repeated here (rather than
#: imported as a type) only for the response model's own explicit field list.
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
    "time_unit",
)


class TimeSeriesFindingItem(BaseModel):
    code: str
    severity: str
    message: str
    field: str | None = None
    column_name: str | None = None
    row_index: int | None = None

    @classmethod
    def from_finding(cls, finding: Finding) -> TimeSeriesFindingItem:
        return cls(
            code=finding.code,
            severity=finding.severity,
            message=finding.message,
            field=finding.field,
            column_name=finding.column_name,
            row_index=finding.row_index,
        )

    @classmethod
    def from_json_list(cls, raw: str) -> list[TimeSeriesFindingItem]:
        return [cls.model_validate(item) for item in json.loads(raw)]


class TimeSeriesConditionLegendItem(BaseModel):
    condition_id: str
    description: str | None


class TimeSeriesMeasurementColumnItem(BaseModel):
    column_name: str
    display_order: int
    unit: str | None
    description: str | None
    declared_in_metadata: bool


class TimeSeriesMeasurementValueItem(BaseModel):
    status: MeasurementValueStatus
    value: float | None
    raw: str | None


class TimeSeriesDataRowItem(BaseModel):
    row_index: int
    sample_id: str | None
    condition_id: str | None
    biological_replicate: str | None
    technical_replicate: str | None
    time_status: MeasurementValueStatus
    time_value: float | None
    time_raw: str | None
    measurements: dict[str, TimeSeriesMeasurementValueItem]


class TimeSeriesWorkbookPreview(BaseModel):
    """What a preview call returns, and what a saved dataset's own content looks like --
    never carrying a database id (a preview was never saved; a saved dataset's own id sits
    alongside this, not inside it)."""

    original_filename: str
    effective_dataset_name: str
    metadata: dict[str, str | None]
    condition_legend: list[TimeSeriesConditionLegendItem]
    measurement_columns: list[TimeSeriesMeasurementColumnItem]
    rows: list[TimeSeriesDataRowItem]
    findings: list[TimeSeriesFindingItem]

    @classmethod
    def from_parsed(
        cls, parsed: ParsedWorkbook, *, original_filename: str, effective_dataset_name: str
    ) -> TimeSeriesWorkbookPreview:
        return cls(
            original_filename=original_filename,
            effective_dataset_name=effective_dataset_name,
            metadata={key: parsed.metadata.get(key) for key in _METADATA_KEYS},
            condition_legend=[
                TimeSeriesConditionLegendItem(condition_id=cid, description=desc)
                for cid, desc in parsed.condition_legend
            ],
            measurement_columns=[
                TimeSeriesMeasurementColumnItem(
                    column_name=c.column_name,
                    display_order=c.display_order,
                    unit=c.unit,
                    description=c.description,
                    declared_in_metadata=c.declared_in_metadata,
                )
                for c in parsed.measurement_columns
            ],
            rows=[
                TimeSeriesDataRowItem(
                    row_index=r.row_index,
                    sample_id=r.sample_id,
                    condition_id=r.condition_id,
                    biological_replicate=r.biological_replicate,
                    technical_replicate=r.technical_replicate,
                    time_status=r.time_status,
                    time_value=r.time_value,
                    time_raw=r.time_raw,
                    measurements={
                        name: TimeSeriesMeasurementValueItem(
                            status=mv.status, value=mv.value, raw=mv.raw
                        )
                        for name, mv in r.measurements.items()
                    },
                )
                for r in parsed.rows
            ],
            findings=[TimeSeriesFindingItem.from_finding(f) for f in parsed.findings],
        )


class TimeSeriesDatasetDetail(BaseModel):
    """A saved dataset, read back exactly as it was saved -- metadata, every row, and the
    original validation findings, never re-derived (task instructions: "read-only
    reopening")."""

    id: UUID
    dataset_reference_id: UUID
    saved_by: str | None
    created_at: datetime
    content: TimeSeriesWorkbookPreview

    @classmethod
    def from_model(cls, dataset: TimeSeriesDataset) -> TimeSeriesDatasetDetail:
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
            "time_unit": dataset.time_unit,
        }
        condition_legend = (
            [
                TimeSeriesConditionLegendItem.model_validate(item)
                for item in json.loads(dataset.condition_legend)
            ]
            if dataset.condition_legend
            else []
        )
        measurement_columns = [
            TimeSeriesMeasurementColumnItem(
                column_name=c.column_name,
                display_order=c.display_order,
                unit=c.unit,
                description=c.description,
                declared_in_metadata=c.declared_in_metadata,
            )
            for c in dataset.measurement_columns
        ]
        rows = [
            TimeSeriesDataRowItem(
                row_index=r.row_index,
                sample_id=r.sample_id,
                condition_id=r.condition_id,
                biological_replicate=r.biological_replicate,
                technical_replicate=r.technical_replicate,
                time_status=r.time_status,
                time_value=float(r.time_value) if r.time_value is not None else None,
                time_raw=r.time_raw,
                measurements={
                    name: TimeSeriesMeasurementValueItem.model_validate(value)
                    for name, value in json.loads(r.measurements).items()
                },
            )
            for r in dataset.rows
        ]
        content = TimeSeriesWorkbookPreview(
            original_filename=dataset.dataset_reference.name,
            effective_dataset_name=dataset.dataset_reference.name,
            metadata=metadata,
            condition_legend=condition_legend,
            measurement_columns=measurement_columns,
            rows=rows,
            findings=TimeSeriesFindingItem.from_json_list(dataset.validation_findings),
        )
        return cls(
            id=dataset.id,
            dataset_reference_id=dataset.dataset_reference_id,
            saved_by=dataset.saved_by,
            created_at=dataset.created_at,
            content=content,
        )


class TimeSeriesDatasetListItem(BaseModel):
    """One row of the time-series datasets list screen."""

    id: UUID
    name: str
    measurement_type: str | None
    organism: str | None
    row_count: int
    measurement_column_count: int
    unresolved_finding_count: int
    saved_by: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, dataset: TimeSeriesDataset) -> TimeSeriesDatasetListItem:
        findings = TimeSeriesFindingItem.from_json_list(dataset.validation_findings)
        return cls(
            id=dataset.id,
            name=dataset.dataset_reference.name,
            measurement_type=dataset.measurement_type,
            organism=dataset.organism,
            row_count=len(dataset.rows),
            measurement_column_count=len(dataset.measurement_columns),
            unresolved_finding_count=len(findings),
            saved_by=dataset.saved_by,
            created_at=dataset.created_at,
        )


__all__ = [
    "TimeSeriesConditionLegendItem",
    "TimeSeriesDataRowItem",
    "TimeSeriesDatasetDetail",
    "TimeSeriesDatasetListItem",
    "TimeSeriesFindingItem",
    "TimeSeriesMeasurementColumnItem",
    "TimeSeriesMeasurementValueItem",
    "TimeSeriesWorkbookPreview",
]
