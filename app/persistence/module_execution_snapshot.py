"""ModuleExecutionSnapshot persistence: create (once, immutably) and read back the exact
inputs one module-scoped execution used.

No scientific logic lives here, and -- deliberately -- no update function exists at all: once
created, a snapshot is never modified by any code in this repository (see
``app.models.module_execution_snapshot``'s own module docstring for why).
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ModuleExecutionKind
from app.models.module_execution_snapshot import ModuleExecutionSnapshot


def create_snapshot(
    *,
    model_module_id: UUID,
    run_record_id: UUID,
    execution_kind: ModuleExecutionKind,
    module_artifact_hash: str,
    snapshot_payload: dict,
    session: Session,
) -> ModuleExecutionSnapshot:
    """Create the one, immutable ``ModuleExecutionSnapshot`` row for ``run_record_id``.

    Idempotent by ``run_record_id`` (its own unique constraint, the natural identity key: one
    execution, one snapshot): if a row already exists, it is returned unchanged, never
    duplicated and never updated with ``snapshot_payload``'s own new contents -- a caller
    replaying an identical request must never retroactively rewrite an already-captured
    snapshot.
    """
    existing = get_snapshot_for_run(session, run_record_id)
    if existing is not None:
        return existing

    row = ModuleExecutionSnapshot(
        model_module_id=model_module_id,
        run_record_id=run_record_id,
        execution_kind=execution_kind,
        module_artifact_hash=module_artifact_hash,
        snapshot_payload=json.dumps(snapshot_payload),
    )
    session.add(row)
    session.flush()
    return row


def get_snapshot_for_run(session: Session, run_record_id: UUID) -> ModuleExecutionSnapshot | None:
    """The one ``ModuleExecutionSnapshot`` for a given run, or ``None``. Read-only."""
    stmt = select(ModuleExecutionSnapshot).where(
        ModuleExecutionSnapshot.run_record_id == run_record_id
    )
    return session.scalars(stmt).one_or_none()


def list_snapshots_for_module(
    session: Session, model_module_id: UUID
) -> list[ModuleExecutionSnapshot]:
    """Every ``ModuleExecutionSnapshot`` for one module, newest first. Read-only."""
    stmt = (
        select(ModuleExecutionSnapshot)
        .where(ModuleExecutionSnapshot.model_module_id == model_module_id)
        .order_by(ModuleExecutionSnapshot.created_at.desc())
    )
    return list(session.scalars(stmt))


def read_snapshot_payload(snapshot: ModuleExecutionSnapshot) -> dict:
    """Decode one ``ModuleExecutionSnapshot.snapshot_payload`` back into a plain dict -- the
    one, documented place this opaque column is ever parsed."""
    return json.loads(snapshot.snapshot_payload)


__all__ = [
    "create_snapshot",
    "get_snapshot_for_run",
    "list_snapshots_for_module",
    "read_snapshot_payload",
]
