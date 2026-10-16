"""HierarchyReviewDecision persistence.

**Idempotent on ``pending_review_item_id``** (database-enforced uniqueness, backed here by
``session.begin_nested()`` race handling identical to ``app.persistence.model.persist_model``'s
own convention): resubmitting the identical decision for an already-decided item is a no-op
that returns the existing row; resubmitting a *different* decision for one is rejected with
``ValueError`` -- a genuine conflict, never silently overwritten.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import HierarchyReviewDecisionValue
from app.models.hierarchy_review_decision import HierarchyReviewDecision


def _existing_decision(
    session: Session, pending_review_item_id: UUID
) -> HierarchyReviewDecision | None:
    return session.execute(
        select(HierarchyReviewDecision).where(
            HierarchyReviewDecision.pending_review_item_id == pending_review_item_id
        )
    ).scalar_one_or_none()


def submit_review_decision(
    *,
    pending_review_item_id: UUID,
    decision: HierarchyReviewDecisionValue,
    session: Session,
    decided_by: str | None = None,
    notes: str | None = None,
) -> HierarchyReviewDecision:
    """Record one reviewer decision for one pending item.

    Raises ``ValueError`` if a decision already exists for this item with a *different* value
    -- resubmitting the identical value is an idempotent no-op that returns the existing row
    unchanged (``decided_by``/``notes`` on that first submission are never overwritten by a
    later, identical resubmission).
    """
    existing = _existing_decision(session, pending_review_item_id)
    if existing is not None:
        if existing.decision is not decision:
            raise ValueError(
                f"HierarchyPendingReviewItem {pending_review_item_id} was already decided as "
                f"{existing.decision}, cannot resubmit as {decision}"
            )
        return existing

    try:
        with session.begin_nested():
            row = HierarchyReviewDecision(
                pending_review_item_id=pending_review_item_id,
                decision=decision,
                decided_by=decided_by,
                notes=notes,
            )
            session.add(row)
            session.flush()
    except IntegrityError:
        raced = _existing_decision(session, pending_review_item_id)
        if raced is not None:
            if raced.decision is not decision:
                raise ValueError(
                    f"HierarchyPendingReviewItem {pending_review_item_id} was already decided "
                    f"as {raced.decision} by a concurrent submission, cannot resubmit as "
                    f"{decision}"
                ) from None
            return raced
        raise

    return row


def get_decision_for_item(
    session: Session, pending_review_item_id: UUID
) -> HierarchyReviewDecision | None:
    """The decision recorded for one pending item, or ``None`` if undecided. Read-only."""
    return _existing_decision(session, pending_review_item_id)


__all__ = ["get_decision_for_item", "submit_review_decision"]
