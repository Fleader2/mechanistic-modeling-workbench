"""ModelSpeciesCatalog persistence: capture a durable, whole-model species/compartment catalog
exactly once per ``Model`` row, atomically and repeat-safe. See
``docs/26_model_species_catalog_prerequisite_increment.md``.

``persist_model_species_catalog`` is the single, atomic write path for both outcomes
(``AVAILABLE`` with every species/compartment row, or an explicit, disclosed ``UNAVAILABLE``) --
there is no separate "mark unavailable" function, so a capture failure can never be reported
through a different, less-careful path than success. Repeat-safe: a second call for the same
``model_id`` (e.g. a caller retrying after an ambiguous failure) reuses the existing row rather
than creating a duplicate or silently overwriting it -- this table is immutable once created.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.enums import ModelSpeciesCatalogStatus
from app.models.model_species_catalog import ModelCompartment, ModelSpecies, ModelSpeciesCatalog
from app.persistence.types import PersistenceAction, PersistenceResult


@dataclass(frozen=True, slots=True)
class CapturedSpecies:
    antimony_species_id: str
    canonical_species_id: str
    display_name: str | None
    compartment_id: str
    compartment_name: str | None
    kind: str
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class CapturedCompartment:
    compartment_id: str
    name: str | None
    volume_unit: str | None
    species_count: int


def _existing(session: Session, model_id: UUID) -> ModelSpeciesCatalog | None:
    return session.execute(
        select(ModelSpeciesCatalog).where(ModelSpeciesCatalog.model_id == model_id)
    ).scalar_one_or_none()


def persist_model_species_catalog(
    *,
    session: Session,
    model_id: UUID,
    source_run_record_id: UUID,
    status: ModelSpeciesCatalogStatus,
    unavailable_reason: str | None = None,
    source_antimony_artifact_reference: str | None = None,
    source_antimony_checksum: str | None = None,
    unresolved_canonical_species_ids: list[str] | None = None,
    unmapped_canonical_species_ids: list[str] | None = None,
    species: list[CapturedSpecies] | None = None,
    compartments: list[CapturedCompartment] | None = None,
) -> PersistenceResult:
    """Persist one ``ModelSpeciesCatalog`` (and, if ``status`` is ``AVAILABLE``, every
    ``ModelSpecies``/``ModelCompartment`` row), keyed 1:1 by ``model_id``.

    Raises ``ValueError`` if ``status`` is ``UNAVAILABLE`` and ``unavailable_reason`` is not
    supplied (a failure is always disclosed, never silent), or if ``status`` is ``AVAILABLE``
    and ``species`` is ``None`` (an empty list is a genuine, valid empty catalog; ``None`` is
    not -- this distinguishes "verified, genuinely zero species" from "never populated").
    """
    if status is ModelSpeciesCatalogStatus.UNAVAILABLE and not unavailable_reason:
        raise ValueError(
            "persist_model_species_catalog requires unavailable_reason when status=UNAVAILABLE"
        )
    if status is ModelSpeciesCatalogStatus.AVAILABLE and species is None:
        raise ValueError(
            "persist_model_species_catalog requires species (possibly []) when status=AVAILABLE"
        )

    existing = _existing(session, model_id)
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=str(model_id),
            reason=f"reused existing model species catalog {existing.id} for this model",
        )

    try:
        with session.begin_nested():
            row = ModelSpeciesCatalog(
                model_id=model_id,
                status=status,
                unavailable_reason=unavailable_reason,
                source_run_record_id=source_run_record_id,
                source_antimony_artifact_reference=source_antimony_artifact_reference,
                source_antimony_checksum=source_antimony_checksum,
                unresolved_canonical_species_ids=json.dumps(
                    unresolved_canonical_species_ids or []
                ),
                unmapped_canonical_species_ids=json.dumps(unmapped_canonical_species_ids or []),
            )
            session.add(row)
            session.flush()

            for sp in species or ():
                session.add(
                    ModelSpecies(
                        model_species_catalog_id=row.id,
                        antimony_species_id=sp.antimony_species_id,
                        canonical_species_id=sp.canonical_species_id,
                        display_name=sp.display_name,
                        compartment_id=sp.compartment_id,
                        compartment_name=sp.compartment_name,
                        kind=sp.kind,
                        unit=sp.unit,
                    )
                )
            for comp in compartments or ():
                session.add(
                    ModelCompartment(
                        model_species_catalog_id=row.id,
                        compartment_id=comp.compartment_id,
                        name=comp.name,
                        volume_unit=comp.volume_unit,
                        species_count=comp.species_count,
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
                    f"reused existing model species catalog {raced.id} after a concurrent "
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
                "model species catalog creation rolled back due to a database integrity "
                "violation, and no matching row was found on recheck"
            ),
        )

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=str(model_id),
        reason=f"created new model species catalog with status={status.value}",
    )


def get_model_species_catalog(session: Session, model_id: UUID) -> ModelSpeciesCatalog | None:
    """One ``Model``'s own species catalog, with every species/compartment eagerly loaded, or
    ``None`` if capture was never attempted -- read identically to an explicit ``UNAVAILABLE``
    row by every caller. Read-only."""
    return session.execute(
        select(ModelSpeciesCatalog)
        .where(ModelSpeciesCatalog.model_id == model_id)
        .options(
            selectinload(ModelSpeciesCatalog.species),
            selectinload(ModelSpeciesCatalog.compartments),
        )
    ).scalar_one_or_none()


__all__ = [
    "CapturedCompartment",
    "CapturedSpecies",
    "get_model_species_catalog",
    "persist_model_species_catalog",
]
