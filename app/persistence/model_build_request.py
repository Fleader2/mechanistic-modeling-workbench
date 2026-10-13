"""ModelBuildRequest persistence: the header row and its eight child tables.

**Header.** Idempotent on ``ModelBuildRequest.subproject_id`` (one build
request per subproject).

**Child rows.** No database uniqueness constraint backs them (a request may
legitimately need the identical reaction under two different roles), so
idempotency is enforced at the application level: each ``add_*`` function
queries for an existing row with the identical full field set before
inserting. ``raw_identifier`` is always preserved when supplied, regardless
of whether a resolved ``agent1_entity_id`` was also supplied -- never
discarded.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import (
    ModelBuildRequestGeneProteinRole,
    ModelBuildRequestPathwayRole,
    ModelBuildRequestReactionRole,
    ModelBuildRequestSpeciesRole,
)
from app.models.model_build_request import (
    ModelBuildRequest,
    ModelBuildRequestAssumption,
    ModelBuildRequestCompartment,
    ModelBuildRequestEnzymeState,
    ModelBuildRequestGeneProtein,
    ModelBuildRequestPathway,
    ModelBuildRequestReaction,
    ModelBuildRequestRegulatoryInteraction,
    ModelBuildRequestSpecies,
)
from app.persistence.types import PersistenceAction, PersistenceResult


def _existing_by_subproject(session: Session, subproject_id: UUID) -> ModelBuildRequest | None:
    return session.execute(
        select(ModelBuildRequest).where(ModelBuildRequest.subproject_id == subproject_id)
    ).scalar_one_or_none()


def persist_model_build_request(
    *, subproject_id: UUID, session: Session, notes: str | None = None
) -> PersistenceResult:
    """Persist one ``ModelBuildRequest`` header row. See module docstring."""
    existing = _existing_by_subproject(session, subproject_id)
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=str(subproject_id),
            reason=f"reused existing model build request {existing.id} for this subproject",
        )

    try:
        with session.begin_nested():
            row = ModelBuildRequest(subproject_id=subproject_id, notes=notes)
            session.add(row)
            session.flush()
    except IntegrityError:
        raced = _existing_by_subproject(session, subproject_id)
        if raced is not None:
            return PersistenceResult(
                action=PersistenceAction.REUSED_EXISTING,
                entity_id=raced.id,
                created=False,
                reused_existing=True,
                identity=str(subproject_id),
                reason="reused existing model build request after a concurrent insert won",
            )
        return PersistenceResult(
            action=PersistenceAction.FAILED,
            entity_id=None,
            created=False,
            reused_existing=False,
            identity=str(subproject_id),
            reason=(
                "model build request creation rolled back due to a database integrity "
                "violation, and no matching row was found on recheck"
            ),
        )

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=str(subproject_id),
        reason="created new model build request",
    )


def get_model_build_request(
    session: Session, model_build_request_id: UUID
) -> ModelBuildRequest | None:
    """One ``ModelBuildRequest`` row by id, or ``None``. Read-only."""
    return session.get(ModelBuildRequest, model_build_request_id)


def _add_child_row(
    *,
    session: Session,
    model_cls: type,
    identity_fields: dict[str, object],
    extra_fields: dict[str, object],
) -> PersistenceResult:
    where_clauses = [getattr(model_cls, name) == value for name, value in identity_fields.items()]
    existing = session.execute(select(model_cls).where(*where_clauses)).scalars().first()
    table_name = model_cls.__tablename__
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=table_name,
            reason=f"reused existing {table_name} row with the identical field set",
        )

    try:
        with session.begin_nested():
            row = model_cls(**identity_fields, **extra_fields)
            session.add(row)
            session.flush()
    except IntegrityError:
        raced = session.execute(select(model_cls).where(*where_clauses)).scalars().first()
        if raced is not None:
            return PersistenceResult(
                action=PersistenceAction.REUSED_EXISTING,
                entity_id=raced.id,
                created=False,
                reused_existing=True,
                identity=table_name,
                reason=f"reused existing {table_name} row after a concurrent insert won",
            )
        return PersistenceResult(
            action=PersistenceAction.FAILED,
            entity_id=None,
            created=False,
            reused_existing=False,
            identity=table_name,
            reason=(
                f"{table_name} row creation rolled back due to a database integrity "
                "violation, and no matching row was found on recheck"
            ),
        )

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=table_name,
        reason=f"created new {table_name} row",
    )


def add_species(
    *,
    model_build_request_id: UUID,
    role: ModelBuildRequestSpeciesRole,
    session: Session,
    agent1_entity_type: str | None = None,
    agent1_entity_id: UUID | None = None,
    raw_identifier: str | None = None,
    notes: str | None = None,
) -> PersistenceResult:
    """Add one input/output/boundary/seed species reference."""
    return _add_child_row(
        session=session,
        model_cls=ModelBuildRequestSpecies,
        identity_fields={
            "model_build_request_id": model_build_request_id,
            "role": role,
            "agent1_entity_type": agent1_entity_type,
            "agent1_entity_id": agent1_entity_id,
        },
        extra_fields={"raw_identifier": raw_identifier, "notes": notes},
    )


def add_reaction(
    *,
    model_build_request_id: UUID,
    role: ModelBuildRequestReactionRole,
    session: Session,
    agent1_entity_type: str | None = None,
    agent1_entity_id: UUID | None = None,
    raw_identifier: str | None = None,
    notes: str | None = None,
) -> PersistenceResult:
    """Add one seed/required/excluded reaction reference."""
    return _add_child_row(
        session=session,
        model_cls=ModelBuildRequestReaction,
        identity_fields={
            "model_build_request_id": model_build_request_id,
            "role": role,
            "agent1_entity_type": agent1_entity_type,
            "agent1_entity_id": agent1_entity_id,
        },
        extra_fields={"raw_identifier": raw_identifier, "notes": notes},
    )


def add_gene_protein(
    *,
    model_build_request_id: UUID,
    role: ModelBuildRequestGeneProteinRole,
    session: Session,
    agent1_entity_type: str | None = None,
    agent1_entity_id: UUID | None = None,
    raw_identifier: str | None = None,
    localization_entity_type: str | None = None,
    localization_entity_id: UUID | None = None,
    localization_raw_identifier: str | None = None,
    notes: str | None = None,
) -> PersistenceResult:
    """Add one seed/important gene or protein reference."""
    return _add_child_row(
        session=session,
        model_cls=ModelBuildRequestGeneProtein,
        identity_fields={
            "model_build_request_id": model_build_request_id,
            "role": role,
            "agent1_entity_type": agent1_entity_type,
            "agent1_entity_id": agent1_entity_id,
            "localization_entity_type": localization_entity_type,
            "localization_entity_id": localization_entity_id,
        },
        extra_fields={
            "raw_identifier": raw_identifier,
            "localization_raw_identifier": localization_raw_identifier,
            "notes": notes,
        },
    )


def add_compartment(
    *,
    model_build_request_id: UUID,
    session: Session,
    agent1_entity_type: str | None = None,
    agent1_entity_id: UUID | None = None,
    raw_identifier: str | None = None,
    notes: str | None = None,
) -> PersistenceResult:
    """Add one compartment-to-include reference."""
    return _add_child_row(
        session=session,
        model_cls=ModelBuildRequestCompartment,
        identity_fields={
            "model_build_request_id": model_build_request_id,
            "agent1_entity_type": agent1_entity_type,
            "agent1_entity_id": agent1_entity_id,
        },
        extra_fields={"raw_identifier": raw_identifier, "notes": notes},
    )


def add_regulatory_interaction(
    *,
    model_build_request_id: UUID,
    session: Session,
    agent1_entity_type: str | None = None,
    agent1_entity_id: UUID | None = None,
    raw_identifier: str | None = None,
    notes: str | None = None,
) -> PersistenceResult:
    """Add one regulatory-interaction-to-include reference."""
    return _add_child_row(
        session=session,
        model_cls=ModelBuildRequestRegulatoryInteraction,
        identity_fields={
            "model_build_request_id": model_build_request_id,
            "agent1_entity_type": agent1_entity_type,
            "agent1_entity_id": agent1_entity_id,
        },
        extra_fields={"raw_identifier": raw_identifier, "notes": notes},
    )


def add_enzyme_state(
    *,
    model_build_request_id: UUID,
    session: Session,
    agent1_entity_type: str | None = None,
    agent1_entity_id: UUID | None = None,
    raw_identifier: str | None = None,
    notes: str | None = None,
) -> PersistenceResult:
    """Add one PTM/protein-state-to-include reference."""
    return _add_child_row(
        session=session,
        model_cls=ModelBuildRequestEnzymeState,
        identity_fields={
            "model_build_request_id": model_build_request_id,
            "agent1_entity_type": agent1_entity_type,
            "agent1_entity_id": agent1_entity_id,
        },
        extra_fields={"raw_identifier": raw_identifier, "notes": notes},
    )


def add_pathway(
    *,
    model_build_request_id: UUID,
    role: ModelBuildRequestPathwayRole,
    session: Session,
    external_pathway_id: str | None = None,
    name: str | None = None,
    notes: str | None = None,
) -> PersistenceResult:
    """Add one include/exclude pathway-scope reference."""
    return _add_child_row(
        session=session,
        model_cls=ModelBuildRequestPathway,
        identity_fields={
            "model_build_request_id": model_build_request_id,
            "role": role,
            "external_pathway_id": external_pathway_id,
            "name": name,
        },
        extra_fields={"notes": notes},
    )


def add_assumption(
    *,
    model_build_request_id: UUID,
    assumption: str,
    session: Session,
    rationale: str | None = None,
    required: bool = False,
) -> PersistenceResult:
    """Add one user constraint/assumption. Idempotent on the assumption text."""
    if not isinstance(assumption, str) or not assumption.strip():
        raise ValueError("add_assumption requires non-empty assumption text")
    return _add_child_row(
        session=session,
        model_cls=ModelBuildRequestAssumption,
        identity_fields={
            "model_build_request_id": model_build_request_id,
            "assumption": assumption,
        },
        extra_fields={"rationale": rationale, "required": required},
    )


__all__ = [
    "add_assumption",
    "add_compartment",
    "add_enzyme_state",
    "add_gene_protein",
    "add_pathway",
    "add_reaction",
    "add_regulatory_interaction",
    "add_species",
    "get_model_build_request",
    "persist_model_build_request",
]
