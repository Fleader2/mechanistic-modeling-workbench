"""ModuleAggregate: an immutable, versioned roll-up of module-level Agent3/Agent4/Agent5
results, one per (target, execution kind) -- never a blended score across unlike result types
or children (Hierarchical Aggregation of Module-Level Agent3/4/5 Results increment).

See ``docs/12_hierarchical_aggregation.md``. A "target" is either a specific, durable
``ModelModule`` (rolling up that module's own direct result, if any, plus its own direct
children's own latest aggregates -- never the root model, which is never itself a
``ModelModule`` row) or the hierarchy root itself (``target_model_module_id IS NULL``, rolling
up every depth-1 ``ModelModule`` of one hierarchy run). Recursive by construction: a parent's
own aggregate links to each child's own *aggregate* (by id/version), never re-deriving or
re-walking that child's own subtree -- the persisted hierarchy relationship
(``ModelModule.parent_model_module_id``) is the only topology this increment ever reads.

Immutable once created, exactly like ``ModuleExecutionSnapshot``: no ``updated_at`` column, and
no persistence function in this repository ever issues an ``UPDATE`` against it. When
contributing runs change or a previously-missing child result appears, a *new*, separately
numbered ``version`` row is created for the same ``(target_model_module_id, execution_kind)``
pair -- the old version is never mutated or deleted, only superseded as "latest."

``ON DELETE RESTRICT`` from ``run_record``/``model_module``, the identical "has its own
lineage, never ephemeral workflow bookkeeping" precedent ``model_module``/
``module_execution_snapshot`` already use.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ModuleAggregateCompleteness, ModuleExecutionKind
from app.models.model_module import ModelModule
from app.models.run_record import RunRecord

_MODULE_EXECUTION_KIND = Enum(ModuleExecutionKind, name="module_execution_kind", create_type=False)
_MODULE_AGGREGATE_COMPLETENESS = Enum(
    ModuleAggregateCompleteness, name="module_aggregate_completeness", create_type=False
)


class ModuleAggregate(Base):
    """One immutable, versioned roll-up of one target's own module-level results for one
    execution kind."""

    __tablename__ = "module_aggregate"
    __table_args__ = (
        Index("ix_module_aggregate_target_model_module_id", "target_model_module_id"),
        Index(
            "ix_module_aggregate_hierarchy_run_record_id",
            "hierarchy_run_record_id",
            "execution_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    #: The hierarchy run (``RunStage.HARNESS``) this aggregate's own target ultimately belongs
    #: to -- always set, including for a non-root target, so every root-level aggregate for one
    #: hierarchy run can be found without first resolving any particular module.
    hierarchy_run_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "run_record.id",
            ondelete="RESTRICT",
            name="fk_module_aggregate_hierarchy_run_record_id",
        ),
        nullable=False,
    )
    #: ``NULL`` means this aggregate's own target is the hierarchy root itself (rolling up
    #: every depth-1 ``ModelModule`` of ``hierarchy_run_record_id``) -- the root is never
    #: itself a ``ModelModule`` row, the identical precedent ``ModelModule
    #: .parent_model_module_id`` already uses for "this module's own parent is the root."
    target_model_module_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_module.id",
            ondelete="RESTRICT",
            name="fk_module_aggregate_target_model_module_id",
        ),
    )

    execution_kind: Mapped[ModuleExecutionKind] = mapped_column(
        _MODULE_EXECUTION_KIND, nullable=False
    )
    #: 1-based, increasing per ``(target_model_module_id, execution_kind)`` (or per
    #: ``(hierarchy_run_record_id, execution_kind)`` when ``target_model_module_id IS NULL``) --
    #: never reused, never decremented; "latest" is always the maximum version on file.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    completeness_status: Mapped[ModuleAggregateCompleteness] = mapped_column(
        _MODULE_AGGREGATE_COMPLETENESS, nullable=False
    )
    #: ``sha256`` hex digest of the canonical encoding of exactly what this aggregate rolled up
    #: (its own direct result's ``RunRecord`` id, if any, plus each direct child's own latest
    #: aggregate id+version) -- this increment's own idempotency key: a rebuild whose own
    #: freshly-computed fingerprint matches the latest existing row's own is never re-created
    #: as a new version (``app.persistence.module_aggregate.create_aggregate``).
    input_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    #: Opaque, pre-serialized JSON object -- decoded nowhere except
    #: ``app.persistence.module_aggregate.read_aggregate_payload``, the one documented site,
    #: matching ``ModuleExecutionSnapshot.snapshot_payload``'s own established discipline. See
    #: ``docs/12_hierarchical_aggregation.md`` for its full documented shape.
    summary_payload: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    hierarchy_run_record: Mapped[RunRecord] = relationship(
        foreign_keys="ModuleAggregate.hierarchy_run_record_id"
    )
    target_model_module: Mapped[ModelModule | None] = relationship(
        foreign_keys="ModuleAggregate.target_model_module_id"
    )


__all__ = ["ModuleAggregate"]
