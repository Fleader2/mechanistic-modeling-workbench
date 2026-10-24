"""InitialConditionsDataset persistence: save a parsed workbook durably, list/reopen read-only
afterward. Mirrors ``app.persistence.time_series_dataset`` exactly -- see its own module
docstring for the "always re-parse the raw bytes, never trust a client-side echo" discipline,
identically applied here. See ``docs/36_initial_conditions_dataset_import_increment.md``.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.initial_conditions.contract import TEMPLATE_VERSION
from app.initial_conditions.parser import (
    Finding,
    ParsedInitialConditionsWorkbook,
    parse_initial_conditions_workbook,
)
from app.models.dataset_reference import DatasetReference
from app.models.initial_conditions_dataset import (
    InitialConditionsDataset,
    InitialConditionsDatasetRow,
    InitialConditionsMeasurementColumn,
    InitialConditionsMeasurementUncertaintyColumn,
)
from app.persistence.dataset_reference import persist_dataset_reference
from app.persistence.types import PersistenceAction, PersistenceResult
from app.storage import save_dataset_workbook

DATASET_TYPE = "initial_conditions"


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
    parsed: ParsedInitialConditionsWorkbook, original_filename: str
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


def _existing_initial_conditions_dataset(
    session: Session, dataset_reference_id: UUID
) -> InitialConditionsDataset | None:
    return session.execute(
        select(InitialConditionsDataset).where(
            InitialConditionsDataset.dataset_reference_id == dataset_reference_id
        )
    ).scalar_one_or_none()


def persist_initial_conditions_dataset(
    *,
    session: Session,
    project_id: UUID,
    subproject_id: UUID,
    original_filename: str,
    workbook_bytes: bytes,
    saved_by: str | None = None,
) -> PersistenceResult:
    """Parse (``app.initial_conditions.parser.parse_initial_conditions_workbook`` -- raises
    ``InitialConditionsWorkbookMalformedError`` for a malformed workbook; the caller maps that
    to a 422, never partially saving) and durably persist one initial-conditions dataset
    import. Idempotent on re-saving byte-identical content, identically to
    ``persist_time_series_dataset``."""
    parsed = parse_initial_conditions_workbook(workbook_bytes)
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
    assert dataset_reference_result.entity_id is not None
    dataset_reference_id = dataset_reference_result.entity_id

    existing = _existing_initial_conditions_dataset(session, dataset_reference_id)
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=dataset_name,
            reason=(
                f"reused existing initial-conditions dataset {existing.id} -- an identical "
                "workbook was already saved for this project under this name"
            ),
        )

    try:
        with session.begin_nested():
            row = InitialConditionsDataset(
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
                validation_findings=json.dumps([_finding_to_dict(f) for f in all_findings]),
                saved_by=saved_by,
            )
            session.add(row)
            session.flush()

            for column in parsed.measurement_columns:
                session.add(
                    InitialConditionsMeasurementColumn(
                        initial_conditions_dataset_id=row.id,
                        column_name=column.column_name,
                        display_order=column.display_order,
                        unit=column.unit,
                        description=column.description,
                        declared_in_metadata=column.declared_in_metadata,
                    )
                )

            for uncertainty_column in parsed.measurement_uncertainty_columns:
                session.add(
                    InitialConditionsMeasurementUncertaintyColumn(
                        initial_conditions_dataset_id=row.id,
                        column_name=uncertainty_column.column_name,
                        measurement_column_name=uncertainty_column.measurement_column_name,
                        statistic_kind=uncertainty_column.statistic_kind,
                        display_order=uncertainty_column.display_order,
                        unit=uncertainty_column.unit,
                        description=uncertainty_column.description,
                    )
                )

            for data_row in parsed.rows:
                measurements_json = json.dumps(
                    {
                        name: {"status": mv.status.value, "value": mv.value, "raw": mv.raw}
                        for name, mv in data_row.measurements.items()
                    }
                )
                measurement_uncertainty_json = json.dumps(
                    {
                        name: {"status": mv.status.value, "value": mv.value, "raw": mv.raw}
                        for name, mv in data_row.measurement_uncertainty.items()
                    }
                )
                session.add(
                    InitialConditionsDatasetRow(
                        initial_conditions_dataset_id=row.id,
                        row_index=data_row.row_index,
                        target_name=data_row.target_name,
                        measurements=measurements_json,
                        measurement_uncertainty=measurement_uncertainty_json,
                    )
                )
            session.flush()
    except IntegrityError:
        raced = _existing_initial_conditions_dataset(session, dataset_reference_id)
        if raced is not None:
            return PersistenceResult(
                action=PersistenceAction.REUSED_EXISTING,
                entity_id=raced.id,
                created=False,
                reused_existing=True,
                identity=dataset_name,
                reason=(
                    f"reused existing initial-conditions dataset {raced.id} after a concurrent "
                    "save won"
                ),
            )
        return PersistenceResult(
            action=PersistenceAction.FAILED,
            entity_id=None,
            created=False,
            reused_existing=False,
            identity=dataset_name,
            reason=(
                "initial-conditions dataset creation rolled back due to a database integrity "
                "violation"
            ),
        )

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=dataset_name,
        reason="created new initial-conditions dataset",
    )


def get_initial_conditions_dataset(
    session: Session, dataset_id: UUID
) -> InitialConditionsDataset | None:
    """One ``InitialConditionsDataset`` by id, with its columns and rows eagerly loaded.
    Read-only."""
    return session.execute(
        select(InitialConditionsDataset)
        .where(InitialConditionsDataset.id == dataset_id)
        .options(
            selectinload(InitialConditionsDataset.measurement_columns),
            selectinload(InitialConditionsDataset.measurement_uncertainty_columns),
            selectinload(InitialConditionsDataset.rows),
            selectinload(InitialConditionsDataset.dataset_reference),
        )
    ).scalar_one_or_none()


def list_initial_conditions_datasets_for_subproject(
    session: Session, subproject_id: UUID
) -> list[InitialConditionsDataset]:
    """Every saved initial-conditions dataset scoped to one Modeling Study, newest first.
    Read-only."""
    stmt = (
        select(InitialConditionsDataset)
        .join(
            DatasetReference,
            InitialConditionsDataset.dataset_reference_id == DatasetReference.id,
        )
        .where(DatasetReference.subproject_id == subproject_id)
        .options(
            selectinload(InitialConditionsDataset.dataset_reference),
            selectinload(InitialConditionsDataset.measurement_columns),
            selectinload(InitialConditionsDataset.measurement_uncertainty_columns),
            selectinload(InitialConditionsDataset.rows),
        )
        .order_by(InitialConditionsDataset.created_at.desc())
    )
    return list(session.scalars(stmt))


__all__ = [
    "DATASET_TYPE",
    "get_initial_conditions_dataset",
    "list_initial_conditions_datasets_for_subproject",
    "persist_initial_conditions_dataset",
]
