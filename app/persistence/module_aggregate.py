"""ModuleAggregate persistence: create (once per fingerprint, immutably) and read back the
rolled-up, per-execution-kind summary for one target (a module or the hierarchy root).

No scientific logic lives here, and -- deliberately -- no update function exists at all: once
created, an aggregate is never modified by any code in this repository (see
``app.models.module_aggregate``'s own module docstring for why).
"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ModuleAggregateCompleteness, ModuleExecutionKind
from app.models.module_aggregate import ModuleAggregate


def compute_aggregate_fingerprint(payload: dict) -> str:
    """A deterministic ``sha256`` hex digest of ``payload``'s own canonical (sorted-key) JSON
    encoding -- this table's own idempotency key. Mirrors ``app.persistence
    .module_execution_snapshot.compute_module_artifact_hash``'s own identical technique,
    applied to "what did this aggregate roll up" instead of "what did this execution
    materialize"."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_latest_aggregate(
    session: Session,
    *,
    execution_kind: ModuleExecutionKind,
    target_model_module_id: UUID | None = None,
    hierarchy_run_record_id: UUID | None = None,
) -> ModuleAggregate | None:
    """The highest-``version`` ``ModuleAggregate`` on file for one target, or ``None`` if none
    exists yet. Read-only.

    Exactly one of ``target_model_module_id`` (a specific module) or
    ``hierarchy_run_record_id`` (the hierarchy root -- pass this alone, with
    ``target_model_module_id`` left ``None``) identifies the target being queried.
    """
    stmt = select(ModuleAggregate).where(ModuleAggregate.execution_kind == execution_kind)
    if target_model_module_id is not None:
        stmt = stmt.where(ModuleAggregate.target_model_module_id == target_model_module_id)
    else:
        if hierarchy_run_record_id is None:
            raise ValueError(
                "get_latest_aggregate requires hierarchy_run_record_id when "
                "target_model_module_id is None (querying a root aggregate)"
            )
        stmt = stmt.where(
            ModuleAggregate.target_model_module_id.is_(None),
            ModuleAggregate.hierarchy_run_record_id == hierarchy_run_record_id,
        )
    stmt = stmt.order_by(ModuleAggregate.version.desc()).limit(1)
    return session.scalars(stmt).one_or_none()


def list_aggregate_versions(
    session: Session,
    *,
    execution_kind: ModuleExecutionKind,
    target_model_module_id: UUID | None = None,
    hierarchy_run_record_id: UUID | None = None,
) -> list[ModuleAggregate]:
    """Every version on file for one target, oldest first. Read-only."""
    stmt = select(ModuleAggregate).where(ModuleAggregate.execution_kind == execution_kind)
    if target_model_module_id is not None:
        stmt = stmt.where(ModuleAggregate.target_model_module_id == target_model_module_id)
    else:
        if hierarchy_run_record_id is None:
            raise ValueError(
                "list_aggregate_versions requires hierarchy_run_record_id when "
                "target_model_module_id is None (querying a root aggregate)"
            )
        stmt = stmt.where(
            ModuleAggregate.target_model_module_id.is_(None),
            ModuleAggregate.hierarchy_run_record_id == hierarchy_run_record_id,
        )
    stmt = stmt.order_by(ModuleAggregate.version.asc())
    return list(session.scalars(stmt))


def create_aggregate(
    *,
    hierarchy_run_record_id: UUID,
    execution_kind: ModuleExecutionKind,
    completeness_status: ModuleAggregateCompleteness,
    input_fingerprint: str,
    summary_payload: dict,
    session: Session,
    target_model_module_id: UUID | None = None,
) -> ModuleAggregate:
    """Create a new ``ModuleAggregate`` version for one target, idempotently.

    Idempotent by ``input_fingerprint`` against the *latest* existing version for this exact
    target+execution_kind: if it matches, the existing row is returned unchanged -- never
    duplicated, and never updated with ``summary_payload``'s own new contents. Only a genuinely
    different fingerprint (new/changed contributing results) creates a new, incrementally
    numbered version; the old version is never touched.
    """
    latest = get_latest_aggregate(
        session,
        execution_kind=execution_kind,
        target_model_module_id=target_model_module_id,
        hierarchy_run_record_id=hierarchy_run_record_id,
    )
    if latest is not None and latest.input_fingerprint == input_fingerprint:
        return latest

    row = ModuleAggregate(
        hierarchy_run_record_id=hierarchy_run_record_id,
        target_model_module_id=target_model_module_id,
        execution_kind=execution_kind,
        version=(latest.version + 1) if latest is not None else 1,
        completeness_status=completeness_status,
        input_fingerprint=input_fingerprint,
        summary_payload=json.dumps(summary_payload),
    )
    session.add(row)
    session.flush()
    return row


def read_aggregate_payload(aggregate: ModuleAggregate) -> dict:
    """Decode one ``ModuleAggregate.summary_payload`` back into a plain dict -- the one,
    documented place this opaque column is ever parsed."""
    return json.loads(aggregate.summary_payload)


__all__ = [
    "compute_aggregate_fingerprint",
    "create_aggregate",
    "get_latest_aggregate",
    "list_aggregate_versions",
    "read_aggregate_payload",
]
