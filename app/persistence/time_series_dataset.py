"""TimeSeriesDataset persistence: save a parsed workbook durably, list/reopen read-only
afterward. See ``app.time_series.parser`` for parsing (never duplicated here) and
``docs/25_time_series_dataset_import_increment.md`` for the full contract.

``persist_time_series_dataset`` always re-parses the raw workbook bytes itself -- it never
trusts a caller-supplied, already-parsed structure as the source of truth for what gets saved
(the same discipline ``submit_module_set_simulation`` already applies to a pinned snapshot: an
authoritative artifact is always rebuilt from its own real source, never from an echo of a
possibly-stale client-side copy).
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.dataset_reference import DatasetReference
from app.models.time_series_dataset import (
    TimeSeriesDataset,
    TimeSeriesDatasetRow,
    TimeSeriesMeasurementColumn,
)
from app.persistence.dataset_reference import persist_dataset_reference
from app.persistence.types import PersistenceAction, PersistenceResult
from app.storage import save_dataset_workbook
from app.time_series.contract import TEMPLATE_VERSION
from app.time_series.parser import Finding, ParsedWorkbook, parse_workbook

DATASET_TYPE = "time_series_experimental_observation"


def _finding_to_dict(finding: Finding) -> dict:
    return {
        "code": finding.code,
        "severity": finding.severity,
        "message": finding.message,
        "field": finding.field,
        "column_name": finding.column_name,
        "row_index": finding.row_index,
    }


def _effective_dataset_name(
    parsed: ParsedWorkbook, original_filename: str
) -> tuple[str, list[Finding]]:
    name = parsed.metadata.get("dataset_name")
    if name:
        return name, []
    fallback = original_filename.rsplit(".", 1)[0] or original_filename
    return fallback, [
        Finding(
            "DATASET_NAME_MISSING_USING_FILENAME",
            "INFO",
            f"Dataset name was left blank; using the uploaded filename {fallback!r} instead.",
            field="dataset_name",
        )
    ]


def _existing_time_series_dataset(
    session: Session, dataset_reference_id: UUID
) -> TimeSeriesDataset | None:
    return session.execute(
        select(TimeSeriesDataset).where(
            TimeSeriesDataset.dataset_reference_id == dataset_reference_id
        )
    ).scalar_one_or_none()


def persist_time_series_dataset(
    *,
    session: Session,
    project_id: UUID,
    subproject_id: UUID,
    original_filename: str,
    workbook_bytes: bytes,
    saved_by: str | None = None,
) -> PersistenceResult:
    """Parse (``app.time_series.parser.parse_workbook`` -- raises ``WorkbookMalformedError``
    for a malformed workbook; the caller is responsible for mapping that to a 422, never
    partially saving) and durably persist one time-series dataset import.

    Idempotent on re-saving byte-identical content for the same project: the artifact is
    content-addressed (``app.storage.save_dataset_workbook``) and
    ``persist_dataset_reference``'s own existing ``(project_id, name, artifact_reference)``
    dedup key reuses the existing catalog row -- the ``TimeSeriesDataset`` row this returns is
    then the *original* save's own row (its own ``dataset_reference_id`` unique constraint
    forbids a second one), never a duplicate.
    """
    parsed = parse_workbook(workbook_bytes)
    dataset_name, name_findings = _effective_dataset_name(parsed, original_filename)
    all_findings = [*name_findings, *parsed.findings]

    artifact_reference, checksum = save_dataset_workbook(workbook_bytes)

    dataset_reference_result = persist_dataset_reference(
        project_id=project_id,
        subproject_id=subproject_id,
        name=dataset_name,
        dataset_type=DATASET_TYPE,
        artifact_reference=artifact_reference,
        checksum=checksum,
        version_label=parsed.metadata.get("template_version") or TEMPLATE_VERSION,
        session=session,
    )
    assert dataset_reference_result.entity_id is not None  # CREATED or REUSED_EXISTING only
    dataset_reference_id = dataset_reference_result.entity_id

    existing = _existing_time_series_dataset(session, dataset_reference_id)
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=dataset_name,
            reason=(
                f"reused existing time-series dataset {existing.id} -- an identical workbook "
                "was already saved for this project under this name"
            ),
        )

    condition_legend_json = (
        json.dumps(
            [{"condition_id": cid, "description": desc} for cid, desc in parsed.condition_legend]
        )
        if parsed.condition_legend
        else None
    )

    try:
        with session.begin_nested():
            row = TimeSeriesDataset(
                dataset_reference_id=dataset_reference_id,
                template_version=parsed.metadata.get("template_version") or TEMPLATE_VERSION,
                dataset_name=parsed.metadata.get("dataset_name"),
                experimental_date=parsed.metadata.get("experimental_date"),
                organism=parsed.metadata.get("organism"),
                cell_type=parsed.metadata.get("cell_type"),
                strain=parsed.metadata.get("strain"),
                experiment_type=parsed.metadata.get("experiment_type"),
                measurement_type=parsed.metadata.get("measurement_type"),
                scientific_objective=parsed.metadata.get("scientific_objective"),
                conditions_treatments=parsed.metadata.get("conditions_treatments"),
                assay=parsed.metadata.get("assay"),
                provenance=parsed.metadata.get("provenance"),
                processing_normalization=parsed.metadata.get("processing_normalization"),
                time_unit=parsed.metadata.get("time_unit"),
                condition_legend=condition_legend_json,
                validation_findings=json.dumps([_finding_to_dict(f) for f in all_findings]),
                saved_by=saved_by,
            )
            session.add(row)
            session.flush()

            for column in parsed.measurement_columns:
                session.add(
                    TimeSeriesMeasurementColumn(
                        time_series_dataset_id=row.id,
                        column_name=column.column_name,
                        display_order=column.display_order,
                        unit=column.unit,
                        description=column.description,
                        declared_in_metadata=column.declared_in_metadata,
                    )
                )

            for data_row in parsed.rows:
                measurements_json = json.dumps(
                    {
                        name: {"status": mv.status.value, "value": mv.value, "raw": mv.raw}
                        for name, mv in data_row.measurements.items()
                    }
                )
                session.add(
                    TimeSeriesDatasetRow(
                        time_series_dataset_id=row.id,
                        row_index=data_row.row_index,
                        sample_id=data_row.sample_id,
                        condition_id=data_row.condition_id,
                        biological_replicate=data_row.biological_replicate,
                        technical_replicate=data_row.technical_replicate,
                        time_status=data_row.time_status,
                        time_value=data_row.time_value,
                        time_raw=data_row.time_raw,
                        measurements=measurements_json,
                    )
                )
            session.flush()
    except IntegrityError:
        raced = _existing_time_series_dataset(session, dataset_reference_id)
        if raced is not None:
            return PersistenceResult(
                action=PersistenceAction.REUSED_EXISTING,
                entity_id=raced.id,
                created=False,
                reused_existing=True,
                identity=dataset_name,
                reason=(
                    f"reused existing time-series dataset {raced.id} after a concurrent save won"
                ),
            )
        return PersistenceResult(
            action=PersistenceAction.FAILED,
            entity_id=None,
            created=False,
            reused_existing=False,
            identity=dataset_name,
            reason="time-series dataset creation rolled back due to a database integrity violation",
        )

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=dataset_name,
        reason="created new time-series dataset",
    )


def get_time_series_dataset(session: Session, dataset_id: UUID) -> TimeSeriesDataset | None:
    """One ``TimeSeriesDataset`` by id, with its measurement columns and rows eagerly loaded
    (the reopen screen always needs both in full). Read-only."""
    return session.execute(
        select(TimeSeriesDataset)
        .where(TimeSeriesDataset.id == dataset_id)
        .options(
            selectinload(TimeSeriesDataset.measurement_columns),
            selectinload(TimeSeriesDataset.rows),
            selectinload(TimeSeriesDataset.dataset_reference),
        )
    ).scalar_one_or_none()


def list_time_series_datasets_for_subproject(
    session: Session, subproject_id: UUID
) -> list[TimeSeriesDataset]:
    """Every saved time-series dataset scoped to one Modeling Study, newest first. Read-only."""
    stmt = (
        select(TimeSeriesDataset)
        .join(DatasetReference, TimeSeriesDataset.dataset_reference_id == DatasetReference.id)
        .where(DatasetReference.subproject_id == subproject_id)
        .options(
            selectinload(TimeSeriesDataset.dataset_reference),
            selectinload(TimeSeriesDataset.measurement_columns),
            selectinload(TimeSeriesDataset.rows),
        )
        .order_by(TimeSeriesDataset.created_at.desc())
    )
    return list(session.scalars(stmt))


__all__ = [
    "DATASET_TYPE",
    "get_time_series_dataset",
    "list_time_series_datasets_for_subproject",
    "persist_time_series_dataset",
]
