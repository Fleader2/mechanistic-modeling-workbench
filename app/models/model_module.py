"""ModelModule: durable, first-class executable-module identity for one accepted hierarchy
module (Executable-Module Materialization increment).

See ``docs/07_executable_module_materialization.md``. One row per depth>=1 ``HierarchyNode``
that was genuinely materialized (``attach_payload IS NOT NULL`` -- see
``app.persistence.model_module.materialize_accepted_modules``'s own docstring for exactly which
nodes qualify and why), ``RESTRICT``-deleted from both ``run_record`` and ``hierarchy_node``:
unlike ``hierarchy_checkpoint``/``hierarchy_pending_review_item`` (ephemeral workflow
bookkeeping, ``CASCADE``), a ``ModelModule`` is a durable, independently-referenceable
execution target -- the identical "has its own lineage/meaning beyond the run that produced
it" precedent ``Model`` itself already uses, never the "no independent existence apart from
its parent" precedent.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.hierarchy_node import HierarchyNode
from app.models.model import Model
from app.models.run_record import RunRecord


class ModelModule(Base):
    """One accepted, materializable hierarchy module -- a stable, durable execution target
    distinct from (and never represented as) an ordinary top-level ``Model`` row."""

    __tablename__ = "model_module"
    __table_args__ = (
        UniqueConstraint("hierarchy_node_id", name="uq_model_module_hierarchy_node_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    run_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("run_record.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: The one ``HierarchyNode`` this module was materialized from -- unique (1:1).
    hierarchy_node_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("hierarchy_node.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: ``None`` only when this module's own parent is the root model itself (depth 1) -- the
    #: root is never represented as its own ``ModelModule`` row (preserves the existing root
    #: ``Model``, per this increment's own explicit requirement).
    parent_model_module_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_module.id", ondelete="RESTRICT"),
    )
    #: The root ``Model`` this module ultimately belongs to -- ``NULL`` when the hierarchy run
    #: that produced it was never associated with an existing Workbench ``Model`` row (e.g. a
    #: run submitted directly from a synthetic fixture), mirroring ``run_record.model_id``'s
    #: own identical nullability.
    root_model_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("model.id", ondelete="RESTRICT")
    )

    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The content-addressed module id (= the producing ``HierarchyNode.parent_module_id``).
    module_id: Mapped[str] = mapped_column(Text, nullable=False)
    #: The accepted candidate id this module was a member of (= the producing
    #: ``HierarchyNode.parent_modularization_id``).
    source_modularization_id: Mapped[str] = mapped_column(Text, nullable=False)
    #: The materialized submodel's own content-addressed id (denormalized from the producing
    #: ``HierarchyNode.child_submodel_id``) -- ``NULL`` when the node's own further search was
    #: never actually run (e.g. a global-budget-exhausted node, still genuinely materializable
    #: via its own ``attach_payload``).
    child_submodel_id: Mapped[str | None] = mapped_column(Text)
    #: The exact, opaque, JSON-encoded payload needed to re-materialize this module's own
    #: standalone executable artifact later -- copied verbatim from the producing
    #: ``HierarchyNode.attach_payload`` (never ``NULL``: a node with no attach_payload never
    #: becomes a ``ModelModule`` at all).
    attach_payload: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run_record: Mapped[RunRecord] = relationship(foreign_keys="ModelModule.run_record_id")
    hierarchy_node: Mapped[HierarchyNode] = relationship()
    parent_model_module: Mapped[ModelModule | None] = relationship(remote_side="ModelModule.id")
    root_model: Mapped[Model | None] = relationship()


__all__ = ["ModelModule"]
