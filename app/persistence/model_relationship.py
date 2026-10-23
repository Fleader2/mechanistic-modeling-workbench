"""ModelRelationship persistence: declare and read explicit, curator-declared relationships
between ``Model`` rows. See ``app.models.model_relationship`` and
``docs/29_joint_calibration_workflow_design.md`` §3.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.enums import ModelRelationshipKind
from app.models.model_relationship import ModelRelationship


def declare_model_relationship(
    session: Session,
    *,
    model_id_a: UUID,
    model_id_b: UUID,
    relationship_kind: ModelRelationshipKind,
    role_label_a: str | None = None,
    role_label_b: str | None = None,
    declared_by: str | None = None,
) -> ModelRelationship:
    """Declare one new relationship fact. Insert-only -- never edits or supersedes an earlier
    declaration; if a curator's own understanding changes, a later row is simply added.

    Raises ``ValueError`` if ``model_id_a == model_id_b`` -- a model is never declared related
    to itself.
    """
    if model_id_a == model_id_b:
        raise ValueError("a model cannot be declared related to itself")
    relationship = ModelRelationship(
        model_id_a=model_id_a,
        model_id_b=model_id_b,
        relationship_kind=relationship_kind,
        role_label_a=role_label_a,
        role_label_b=role_label_b,
        declared_by=declared_by,
    )
    session.add(relationship)
    session.flush()
    return relationship


def list_model_relationships_for_models(
    session: Session, model_ids: set[UUID]
) -> list[ModelRelationship]:
    """Every declared relationship touching at least one of ``model_ids`` -- used to decide
    whether Screen 1's model-relationship section has anything to show (docs/29 §7). Read-only.
    """
    if not model_ids:
        return []
    stmt = select(ModelRelationship).where(
        or_(
            ModelRelationship.model_id_a.in_(model_ids),
            ModelRelationship.model_id_b.in_(model_ids),
        )
    )
    return list(session.scalars(stmt))


__all__ = ["declare_model_relationship", "list_model_relationships_for_models"]
