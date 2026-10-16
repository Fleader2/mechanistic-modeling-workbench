"""HierarchyPendingReviewItem persistence: bulk-create the pending-review modules of one
``HierarchyCheckpoint`` as first-class rows, and read them back for a UI/service to show
without parsing the checkpoint's own opaque payload.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.hierarchy_pending_review_item import HierarchyPendingReviewItem


def create_pending_review_items(
    *,
    hierarchy_checkpoint_id: UUID,
    pending_review_modules: list[dict],
    session: Session,
) -> list[HierarchyPendingReviewItem]:
    """Bulk-insert every entry of one checkpoint's own ``pending_review_modules`` -- always a
    fresh insert for a freshly-created checkpoint (never called twice for the identical
    ``hierarchy_checkpoint_id``, since each checkpoint row is itself append-only/immutable --
    see ``app.persistence.hierarchy_checkpoint.create_hierarchy_checkpoint``).

    Each ``pending_review_modules[i]`` is one plain dict shaped like the harness's own
    ``HierarchyCheckpoint.pending_review_modules`` entry (already parsed from the harness's own
    JSON response) -- never a raw harness dict passed through unvalidated.
    """
    rows = [
        HierarchyPendingReviewItem(
            hierarchy_checkpoint_id=hierarchy_checkpoint_id,
            pending_id=item["pending_id"],
            parent_node_id=item["parent_node_id"],
            module_id=item["module_id"],
            depth=item["depth"],
            reaction_count=item.get("reaction_count"),
        )
        for item in pending_review_modules
    ]
    session.add_all(rows)
    session.flush()
    return rows


def list_pending_review_items_for_checkpoint(
    session: Session, hierarchy_checkpoint_id: UUID
) -> list[HierarchyPendingReviewItem]:
    """Every ``HierarchyPendingReviewItem`` row of one checkpoint, ordered by ``pending_id`` for
    deterministic display. Read-only."""
    stmt = (
        select(HierarchyPendingReviewItem)
        .where(HierarchyPendingReviewItem.hierarchy_checkpoint_id == hierarchy_checkpoint_id)
        .order_by(HierarchyPendingReviewItem.pending_id.asc())
    )
    return list(session.scalars(stmt))


def get_pending_review_item(
    session: Session, pending_review_item_id: UUID
) -> HierarchyPendingReviewItem | None:
    """One ``HierarchyPendingReviewItem`` row by id, or ``None``. Read-only."""
    return session.get(HierarchyPendingReviewItem, pending_review_item_id)


__all__ = [
    "create_pending_review_items",
    "get_pending_review_item",
    "list_pending_review_items_for_checkpoint",
]
