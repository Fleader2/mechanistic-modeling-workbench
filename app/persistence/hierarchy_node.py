"""HierarchyNode persistence: bulk-create the full node set of one hierarchical-recursion run,
and read it back for a UI to render as a tree.

No scientific logic lives here: this module never interprets, re-derives, or repairs any
node's own acceptance decision -- it only copies already-decided fields onto rows and reads
them back, ordered for deterministic tree reconstruction.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.hierarchy_node import HierarchyNode


def create_hierarchy_nodes(
    *,
    run_record_id: UUID,
    nodes: list[dict],
    session: Session,
) -> list[HierarchyNode]:
    """Insert every node of ``nodes`` not already persisted for ``run_record_id``.

    A fresh (non-resumed) run's own first call always inserts every node, exactly as before.
    Hierarchical Review/Resume increment: a *resumed* run's own harness result carries forward
    every already-completed node unchanged (same ``node_id``) ahead of any genuinely new ones
    -- calling this function again after a resume must insert only the new ones, never
    re-insert (let alone duplicate) a completed node. This is enforced by filtering against
    already-persisted ``node_id``s before inserting (the primary mechanism); the
    ``uq_hierarchy_node_run_record_id_node_id`` database constraint is only a backstop against
    a caller that fails to filter, never relied on here to silently absorb a duplicate.

    Each ``nodes[i]`` is one plain dict shaped like
    ``app.contracts.hierarchical_recursion.HierarchyNodeSummary`` (already parsed from the
    harness's own JSON response) -- never a raw harness dict passed through unvalidated.
    """
    existing_node_ids = {
        row.node_id
        for row in session.execute(
            select(HierarchyNode.node_id).where(HierarchyNode.run_record_id == run_record_id)
        )
    }
    new_nodes = [node for node in nodes if node["node_id"] not in existing_node_ids]

    rows = [
        HierarchyNode(
            run_record_id=run_record_id,
            node_id=node["node_id"],
            depth=node["depth"],
            parent_modularization_id=node.get("parent_modularization_id"),
            parent_module_id=node.get("parent_module_id"),
            child_submodel_id=node.get("child_submodel_id"),
            child_modularization_id=node.get("child_modularization_id"),
            child_module_ids=(
                None
                if not node.get("child_module_ids")
                else json.dumps(list(node["child_module_ids"]))
            ),
            accepted=bool(node["accepted"]),
            reason=node["reason"],
            baseline_score=(
                Decimal(node["baseline_score"]) if node.get("baseline_score") is not None else None
            ),
            child_score=(
                Decimal(node["child_score"]) if node.get("child_score") is not None else None
            ),
            branch_stopping_reason=node.get("branch_stopping_reason"),
            recursive_search_stopping_reason=node["recursive_search_stopping_reason"],
            recursive_search_rounds=node["recursive_search_rounds"],
            recursive_search_policy_version=node["recursive_search_policy_version"],
            attach_payload=(
                None if not node.get("attach_payload") else json.dumps(node["attach_payload"])
            ),
        )
        for node in new_nodes
    ]
    session.add_all(rows)
    session.flush()
    return rows


def list_hierarchy_nodes_for_run(session: Session, run_record_id: UUID) -> list[HierarchyNode]:
    """Every ``HierarchyNode`` row for one run, ordered depth-first (``depth`` ascending, then
    ``node_id``) -- the one, deterministic order a UI needs to reconstruct the tree by walking
    each row's own ``parent_modularization_id``/``parent_module_id`` against an ancestor's own
    ``child_modularization_id``. Read-only."""
    stmt = (
        select(HierarchyNode)
        .where(HierarchyNode.run_record_id == run_record_id)
        .order_by(HierarchyNode.depth.asc(), HierarchyNode.node_id.asc())
    )
    return list(session.scalars(stmt))


__all__ = ["create_hierarchy_nodes", "list_hierarchy_nodes_for_run"]
