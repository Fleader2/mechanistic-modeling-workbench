"""DatasetReference persistence. Idempotent on ``(project_id, name, artifact_reference)``."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.dataset_reference import DatasetReference
from app.persistence.types import PersistenceAction, PersistenceResult


def _existing(
    session: Session, *, project_id: UUID, name: str, artifact_reference: str
) -> DatasetReference | None:
    return session.execute(
        select(DatasetReference).where(
            DatasetReference.project_id == project_id,
            DatasetReference.name == name,
            DatasetReference.artifact_reference == artifact_reference,
        )
    ).scalar_one_or_none()


def persist_dataset_reference(
    *,
    project_id: UUID,
    name: str,
    dataset_type: str,
    artifact_reference: str,
    session: Session,
    subproject_id: UUID | None = None,
    description: str | None = None,
    agent1_entity_type: str | None = None,
    agent1_entity_id: UUID | None = None,
    biological_context_notes: str | None = None,
    checksum: str | None = None,
    version_label: str | None = None,
    notes: str | None = None,
) -> PersistenceResult:
    """Persist one ``DatasetReference``, keyed by ``(project_id, name, artifact_reference)``."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("persist_dataset_reference requires a non-empty name")
    if not isinstance(dataset_type, str) or not dataset_type.strip():
        raise ValueError("persist_dataset_reference requires a non-empty dataset_type")
    if not isinstance(artifact_reference, str) or not artifact_reference.strip():
        raise ValueError("persist_dataset_reference requires a non-empty artifact_reference")

    existing = _existing(
        session, project_id=project_id, name=name, artifact_reference=artifact_reference
    )
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=name,
            reason=(
                f"reused existing dataset reference {existing.id} with the identical natural key"
            ),
        )

    try:
        with session.begin_nested():
            row = DatasetReference(
                project_id=project_id,
                subproject_id=subproject_id,
                dataset_type=dataset_type,
                name=name,
                description=description,
                agent1_entity_type=agent1_entity_type,
                agent1_entity_id=agent1_entity_id,
                biological_context_notes=biological_context_notes,
                artifact_reference=artifact_reference,
                checksum=checksum,
                version_label=version_label,
                notes=notes,
            )
            session.add(row)
            session.flush()
    except IntegrityError:
        raced = _existing(
            session, project_id=project_id, name=name, artifact_reference=artifact_reference
        )
        if raced is not None:
            return PersistenceResult(
                action=PersistenceAction.REUSED_EXISTING,
                entity_id=raced.id,
                created=False,
                reused_existing=True,
                identity=name,
                reason=(
                    f"reused existing dataset reference {raced.id} after a concurrent insert won"
                ),
            )
        return PersistenceResult(
            action=PersistenceAction.FAILED,
            entity_id=None,
            created=False,
            reused_existing=False,
            identity=name,
            reason=(
                "dataset reference creation rolled back due to a database integrity "
                "violation, and no matching row was found on recheck"
            ),
        )

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=name,
        reason="created new dataset reference",
    )


def get_dataset_reference(session: Session, dataset_reference_id: UUID) -> DatasetReference | None:
    """One ``DatasetReference`` row by id, or ``None``. Read-only."""
    return session.get(DatasetReference, dataset_reference_id)


__all__ = ["get_dataset_reference", "persist_dataset_reference"]
