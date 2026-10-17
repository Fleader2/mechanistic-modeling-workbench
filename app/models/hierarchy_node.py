"""HierarchyNode: durable, first-class, queryable record of one node of one Automatic
Hierarchical Recursive Modularization run.

See ``docs/04_hierarchical_recursion.md``. One ``RunRecord`` (``stage=RunStage.HARNESS``) that
produced a hierarchical-recursion result owns any number of these -- the Workbench never stores
the harness's own full ``HierarchicalRecursionResult`` JSON as the *only* record of a run's own
tree/scores/reasons (that would force a UI to parse raw JSON to render anything); every field a
UI needs to show the accepted module tree, stopped branches, scores, and reasons is its own
typed, queryable column. This table never re-derives or re-scores anything -- it only records,
verbatim, what ``app.harness.workbench_contracts.WorkbenchHierarchyNodeSummary`` already
reported.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.run_record import RunRecord


class HierarchyNode(Base):
    """One ``HierarchyNodeRecord`` (``agent-integration-harness/app/harness
    .hierarchical_recursion.types``), persisted verbatim under the ``RunRecord`` that produced
    it.

    ``(run_record_id, node_id)`` is unique (Hierarchical Review/Resume increment): a resumed
    run's own harness result always carries forward every already-completed node unchanged, so
    ``app.persistence.hierarchy_node.create_hierarchy_nodes`` must insert only genuinely new
    nodes on each resume -- this constraint is the database-level backstop for that
    idempotency, never relied on as the primary mechanism (see that function's own docstring).
    """

    __tablename__ = "hierarchy_node"
    __table_args__ = (
        UniqueConstraint(
            "run_record_id", "node_id", name="uq_hierarchy_node_run_record_id_node_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    run_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("run_record.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: The harness's own ``node_id`` string -- unique within one run, never globally.
    node_id: Mapped[str] = mapped_column(String, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)

    #: ``None`` only for the root node (depth 0), which has no parent module being subdivided.
    #: ``Text``, not ``String``: a module id is content-addressed (one token per member
    #: reaction/species/parameter) and can be arbitrarily long.
    parent_modularization_id: Mapped[str | None] = mapped_column(Text)
    parent_module_id: Mapped[str | None] = mapped_column(Text)

    #: The materialized submodel's own content-addressed ``model_id`` this node searched --
    #: ``None`` for the root node, which searches the whole canonical model directly.
    child_submodel_id: Mapped[str | None] = mapped_column(Text)
    #: The accepted candidate's own modularization id at this node -- ``None`` when no child
    #: decomposition was accepted.
    child_modularization_id: Mapped[str | None] = mapped_column(Text)
    #: JSON-encoded list of the accepted candidate's own module ids -- opaque, matching
    #: ``RunRecord.warnings``'s own identical "store the encoded list, never interpret it here"
    #: convention; a UI that needs these renders them from this run's own sibling
    #: ``HierarchyNode`` rows (each child node already names its own ``parent_module_id``),
    #: never by parsing this column.
    child_module_ids: Mapped[str | None] = mapped_column(Text)

    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    #: The degenerate ("leave the parent module intact") baseline's own ``overall_score`` under
    #: the weights in effect -- ``None`` when no baseline was available (the root node has no
    #: such baseline at all).
    baseline_score: Mapped[float | None] = mapped_column(Numeric)
    #: The accepted (or best-attempted) child candidate's own ``overall_score`` -- ``None``
    #: when no candidate was ever scored.
    child_score: Mapped[float | None] = mapped_column(Numeric)

    #: One of ``HierarchyBranchStoppingReason``'s own values, or ``None`` for an accepted node
    #: whose own branch continues descending.
    branch_stopping_reason: Mapped[str | None] = mapped_column(String)

    #: This node's own *flat* recursive search's own outcome -- distinct from
    #: ``branch_stopping_reason`` (the hierarchy's own decision about this node), see that
    #: harness-side type's own docstring.
    recursive_search_stopping_reason: Mapped[str] = mapped_column(String, nullable=False)
    recursive_search_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    recursive_search_policy_version: Mapped[str] = mapped_column(String, nullable=False)

    #: Executable-Module Materialization increment: the exact, opaque, JSON-encoded
    #: ``{"modularization_id", "module_ids", "memberships"}`` payload the harness used to
    #: materialize *this* node's own submodel -- ``None`` for the root node and for a node
    #: never actually materialized (``MODULE_TOO_SMALL``/``HUMAN_REVIEW_REJECTED``). Never
    #: parsed or interpreted here except to pass it back, unchanged, to the harness's own
    #: module-simulation entrypoint (see ``app.models.model_module.ModelModule
    #: .attach_payload``, which copies this verbatim).
    attach_payload: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run_record: Mapped[RunRecord] = relationship()


__all__ = ["HierarchyNode"]
