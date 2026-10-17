"""ModelModule persistence: idempotently materialize accepted hierarchy modules as durable,
first-class rows, and read them back.

No scientific logic lives here: this module never interprets, re-derives, or repairs any
node's own acceptance decision -- it only copies already-decided fields onto rows.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.hierarchy_node import HierarchyNode
from app.models.model_module import ModelModule
from app.models.run_record import RunRecord
from app.persistence.hierarchy_node import list_hierarchy_nodes_for_run


def materialize_accepted_modules(*, run_record_id: UUID, session: Session) -> list[ModelModule]:
    """Create (and return only) the newly-created ``ModelModule`` rows for every depth>=1
    ``HierarchyNode`` of this run that was genuinely materialized (``attach_payload IS NOT
    NULL``) and does not already have one -- an already-materialized node is silently skipped,
    never re-returned.

    **Which nodes qualify.** A node's own ``accepted`` field describes whether *its own
    further* decomposition was found acceptable -- not whether the node's own module is a
    legitimate, executable-candidate member of its parent's modularization (it always is,
    for any depth>=1 node that was ever actually reached). Gating on ``attach_payload is not
    None`` instead -- a broader, deliberate interpretation -- is what makes this feature
    usable at all for real models: a leaf module whose own further split was correctly
    rejected (``accepted=False``, ``NO_VALID_CHILD_DECOMPOSITION``) is still every bit as
    materializable/simulatable as one that did split further, and in practice is the *common*
    case. Excluded (``attach_payload is None``): the root node (depth 0 -- preserves the
    existing root ``Model``, never represented as a ``ModelModule``), a
    ``MODULE_TOO_SMALL`` node (never even attempted), and a ``HUMAN_REVIEW_REJECTED`` node
    (rejected outright, never searched).

    **Idempotency.** Always queries already-materialized ``hierarchy_node_id``s first and
    creates only the new ones -- safe to call after every resume/replay, exactly mirroring
    ``app.persistence.hierarchy_node.create_hierarchy_nodes``'s own established pattern. A
    node's own parent ``ModelModule`` (``parent_model_module_id``) is resolved by matching this
    node's ``parent_modularization_id`` against an already-known ancestor's own
    ``child_modularization_id`` -- ``None`` when that ancestor is the root itself (which has no
    ``ModelModule`` row to point at).
    """
    run_record = session.get(RunRecord, run_record_id)
    assert run_record is not None  # the caller's own contract guarantee

    nodes = list_hierarchy_nodes_for_run(session, run_record_id)  # depth-ascending order

    existing_by_node_id = {
        row.hierarchy_node_id: row
        for row in session.execute(
            select(ModelModule).where(ModelModule.run_record_id == run_record_id)
        ).scalars()
    }

    # Maps a modularization id a node's own acceptance produced -> the ModelModule row
    # representing *that node's own module* (None for the root, which produces modularizations
    # but is never itself a ModelModule).
    modularization_to_module: dict[str, ModelModule | None] = {}
    newly_created: list[ModelModule] = []
    for node in nodes:
        if node.depth == 0:
            if node.child_modularization_id:
                modularization_to_module[node.child_modularization_id] = None
            continue
        existing = existing_by_node_id.get(node.id)
        if existing is not None:
            if node.child_modularization_id:
                modularization_to_module[node.child_modularization_id] = existing
            continue
        if not node.attach_payload:
            continue

        parent_module = modularization_to_module.get(node.parent_modularization_id)
        row = ModelModule(
            run_record_id=run_record_id,
            hierarchy_node_id=node.id,
            parent_model_module_id=parent_module.id if parent_module is not None else None,
            root_model_id=run_record.model_id,
            depth=node.depth,
            module_id=node.parent_module_id,
            source_modularization_id=node.parent_modularization_id,
            child_submodel_id=node.child_submodel_id,
            attach_payload=node.attach_payload,
        )
        session.add(row)
        session.flush()
        existing_by_node_id[node.id] = row
        newly_created.append(row)
        if node.child_modularization_id:
            modularization_to_module[node.child_modularization_id] = row

    return newly_created


def get_model_module(session: Session, model_module_id: UUID) -> ModelModule | None:
    """One ``ModelModule`` row by id, or ``None``. Read-only."""
    return session.get(ModelModule, model_module_id)


def list_model_modules_for_run(session: Session, run_record_id: UUID) -> list[ModelModule]:
    """Every ``ModelModule`` row for one run, ordered depth-first. Read-only."""
    stmt = (
        select(ModelModule)
        .where(ModelModule.run_record_id == run_record_id)
        .join(HierarchyNode, HierarchyNode.id == ModelModule.hierarchy_node_id)
        .order_by(ModelModule.depth.asc(), HierarchyNode.node_id.asc())
    )
    return list(session.scalars(stmt))


def build_attach_payload(model_module: ModelModule) -> dict:
    """Decode one ``ModelModule.attach_payload`` back into a plain dict -- the one, documented
    place this opaque column is ever parsed, and only to pass it straight back to the harness's
    own module-simulation entrypoint, never to inspect or act on its own contents here."""
    return json.loads(model_module.attach_payload)


__all__ = [
    "build_attach_payload",
    "get_model_module",
    "list_model_modules_for_run",
    "materialize_accepted_modules",
]
