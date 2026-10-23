"""ModelParameterCatalog persistence: capture a durable, whole-model parameter catalog exactly
once per ``Model`` row, atomically and repeat-safe. Mirrors
``app.persistence.model_species_catalog`` exactly -- see that module's own docstring for the
shared rationale, and ``app.models.model_parameter_catalog`` for why this is a genuinely
distinct catalog, not a repurposing of the species one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.enums import ModelParameterCatalogStatus
from app.models.model_parameter_catalog import ModelParameter, ModelParameterCatalog
from app.persistence.types import PersistenceAction, PersistenceResult


@dataclass(frozen=True, slots=True)
class CapturedParameter:
    antimony_parameter_id: str
    canonical_parameter_id: str
    display_name: str | None
    kind: str
    unit: str | None = None
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None


def _existing(session: Session, model_id: UUID) -> ModelParameterCatalog | None:
    return session.execute(
        select(ModelParameterCatalog).where(ModelParameterCatalog.model_id == model_id)
    ).scalar_one_or_none()


def persist_model_parameter_catalog(
    *,
    session: Session,
    model_id: UUID,
    source_run_record_id: UUID,
    status: ModelParameterCatalogStatus,
    unavailable_reason: str | None = None,
    source_antimony_artifact_reference: str | None = None,
    source_antimony_checksum: str | None = None,
    unresolved_canonical_parameter_ids: list[str] | None = None,
    unmapped_canonical_parameter_ids: list[str] | None = None,
    parameters: list[CapturedParameter] | None = None,
) -> PersistenceResult:
    """Persist one ``ModelParameterCatalog`` (and, if ``status`` is ``AVAILABLE``, every
    ``ModelParameter`` row), keyed 1:1 by ``model_id``. Identical contract and raised-error
    conditions to ``persist_model_species_catalog`` -- see that function's own docstring.
    """
    if status is ModelParameterCatalogStatus.UNAVAILABLE and not unavailable_reason:
        raise ValueError(
            "persist_model_parameter_catalog requires unavailable_reason when status=UNAVAILABLE"
        )
    if status is ModelParameterCatalogStatus.AVAILABLE and parameters is None:
        raise ValueError(
            "persist_model_parameter_catalog requires parameters (possibly []) when "
            "status=AVAILABLE"
        )

    existing = _existing(session, model_id)
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=str(model_id),
            reason=f"reused existing model parameter catalog {existing.id} for this model",
        )

    try:
        with session.begin_nested():
            row = ModelParameterCatalog(
                model_id=model_id,
                status=status,
                unavailable_reason=unavailable_reason,
                source_run_record_id=source_run_record_id,
                source_antimony_artifact_reference=source_antimony_artifact_reference,
                source_antimony_checksum=source_antimony_checksum,
                unresolved_canonical_parameter_ids=json.dumps(
                    unresolved_canonical_parameter_ids or []
                ),
                unmapped_canonical_parameter_ids=json.dumps(
                    unmapped_canonical_parameter_ids or []
                ),
            )
            session.add(row)
            session.flush()

            for p in parameters or ():
                session.add(
                    ModelParameter(
                        model_parameter_catalog_id=row.id,
                        antimony_parameter_id=p.antimony_parameter_id,
                        canonical_parameter_id=p.canonical_parameter_id,
                        display_name=p.display_name,
                        kind=p.kind,
                        unit=p.unit,
                        lower_bound=p.lower_bound,
                        upper_bound=p.upper_bound,
                    )
                )
            session.flush()
    except IntegrityError:
        raced = _existing(session, model_id)
        if raced is not None:
            return PersistenceResult(
                action=PersistenceAction.REUSED_EXISTING,
                entity_id=raced.id,
                created=False,
                reused_existing=True,
                identity=str(model_id),
                reason=(
                    f"reused existing model parameter catalog {raced.id} after a concurrent "
                    "capture won"
                ),
            )
        return PersistenceResult(
            action=PersistenceAction.FAILED,
            entity_id=None,
            created=False,
            reused_existing=False,
            identity=str(model_id),
            reason=(
                "model parameter catalog creation rolled back due to a database integrity "
                "violation, and no matching row was found on recheck"
            ),
        )

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=str(model_id),
        reason=f"created new model parameter catalog with status={status.value}",
    )


def get_model_parameter_catalog(
    session: Session, model_id: UUID
) -> ModelParameterCatalog | None:
    """One ``Model``'s own parameter catalog, with every parameter eagerly loaded, or ``None``
    if capture was never attempted -- read identically to an explicit ``UNAVAILABLE`` row by
    every caller. Read-only."""
    return session.execute(
        select(ModelParameterCatalog)
        .where(ModelParameterCatalog.model_id == model_id)
        .options(selectinload(ModelParameterCatalog.parameters))
    ).scalar_one_or_none()


__all__ = [
    "CapturedParameter",
    "get_model_parameter_catalog",
    "persist_model_parameter_catalog",
]
