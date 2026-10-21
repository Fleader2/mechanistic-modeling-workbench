"""Model persistence.

A later calibration or modification never overwrites a prior ``Model`` row
-- this module only ever creates new rows (linked via ``parent_model_id``
when the caller supplies one), never updates an existing one, so model
lineage stays reproducible by construction. ``stable_identifier`` is always
caller-supplied here (unlike Agent 1's own retired equivalent, the
Workbench has no need for a sequence-based allocator: a ``Model`` row is
always created in response to an explicit user/harness action that already
knows what to call it).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import ModelSourceType, ModelStatus
from app.models.model import Model
from app.persistence.types import PersistenceAction, PersistenceResult


def _existing_by_stable_identifier(session: Session, stable_identifier: str) -> Model | None:
    return session.execute(
        select(Model).where(Model.stable_identifier == stable_identifier)
    ).scalar_one_or_none()


def persist_model(
    *,
    subproject_id: UUID,
    stable_identifier: str,
    name: str,
    source_type: ModelSourceType,
    session: Session,
    status: ModelStatus = ModelStatus.DRAFT,
    artifact_reference: str | None = None,
    parent_model_id: UUID | None = None,
    version_label: str | None = None,
    notes: str | None = None,
) -> PersistenceResult:
    """Persist one ``Model``, keyed by the globally-unique ``stable_identifier``."""
    if not isinstance(stable_identifier, str) or not stable_identifier.strip():
        raise ValueError("persist_model requires a non-empty stable_identifier")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("persist_model requires a non-empty name")

    existing = _existing_by_stable_identifier(session, stable_identifier)
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=stable_identifier,
            reason=f"reused existing model {existing.id} with the identical stable_identifier",
        )

    try:
        with session.begin_nested():
            row = Model(
                subproject_id=subproject_id,
                stable_identifier=stable_identifier,
                name=name,
                source_type=source_type,
                status=status,
                artifact_reference=artifact_reference,
                parent_model_id=parent_model_id,
                version_label=version_label,
                notes=notes,
            )
            session.add(row)
            session.flush()
    except IntegrityError:
        raced = _existing_by_stable_identifier(session, stable_identifier)
        if raced is not None:
            return PersistenceResult(
                action=PersistenceAction.REUSED_EXISTING,
                entity_id=raced.id,
                created=False,
                reused_existing=True,
                identity=stable_identifier,
                reason=f"reused existing model {raced.id} after a concurrent insert won",
            )
        return PersistenceResult(
            action=PersistenceAction.FAILED,
            entity_id=None,
            created=False,
            reused_existing=False,
            identity=stable_identifier,
            reason=(
                "model creation rolled back due to a database integrity violation, "
                "and no matching row was found on recheck"
            ),
        )

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=stable_identifier,
        reason="created new model",
    )


def get_model(session: Session, model_id: UUID) -> Model | None:
    """One ``Model`` row by id, or ``None``. Read-only."""
    return session.get(Model, model_id)


def count_models_by_subproject(session: Session) -> dict[UUID, int]:
    """Model count per subproject, in one aggregate query -- never one query
    per subproject (the "Modeling Studies" table's "Models" column).

    A subproject with zero models is simply absent from the returned
    mapping; callers that need a default of ``0`` use ``dict.get(..., 0)``.
    """
    rows = session.execute(
        select(Model.subproject_id, func.count(Model.id)).group_by(Model.subproject_id)
    ).all()
    return dict(rows)


__all__ = ["count_models_by_subproject", "get_model", "persist_model"]
