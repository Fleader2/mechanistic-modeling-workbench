"""Automatic Hierarchical Recursive Modularization: persist the full node set of one
hierarchical-recursion harness run as first-class, queryable rows.

Creates one new table, ``hierarchy_node``, a ``CASCADE``-deleted child of ``run_record`` (a
``RunRecord`` whose own run is deleted should never leave orphaned node rows behind -- unlike
``run_record.model_id``'s own ``RESTRICT`` FK, which protects a ``Model`` row's own durable
lineage, a ``HierarchyNode`` has no independent existence apart from the run that produced it).

No enum change: this increment deliberately does not add a new ``RunStage`` value -- a
hierarchical-recursion run is recorded as ``RunStage.HARNESS`` (the identical stage the
five-agent ``FULL_PIPELINE`` already uses), distinguished from it only by whether any
``HierarchyNode`` rows exist for a given run. See ``docs/04_hierarchical_recursion.md``.

Revision ID: 0003_hierarchy_node
Revises: 0002_run_record_build_request
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_hierarchy_node"
down_revision: str | None = "0002_run_record_build_request"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hierarchy_node",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("parent_modularization_id", sa.Text(), nullable=True),
        sa.Column("parent_module_id", sa.Text(), nullable=True),
        sa.Column("child_submodel_id", sa.Text(), nullable=True),
        sa.Column("child_modularization_id", sa.Text(), nullable=True),
        sa.Column("child_module_ids", sa.Text(), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("baseline_score", sa.Numeric(), nullable=True),
        sa.Column("child_score", sa.Numeric(), nullable=True),
        sa.Column("branch_stopping_reason", sa.String(), nullable=True),
        sa.Column("recursive_search_stopping_reason", sa.String(), nullable=False),
        sa.Column("recursive_search_rounds", sa.Integer(), nullable=False),
        sa.Column("recursive_search_policy_version", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_hierarchy_node"),
        sa.ForeignKeyConstraint(
            ["run_record_id"],
            ["run_record.id"],
            name="fk_hierarchy_node_run_record_id_run_record",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_hierarchy_node_run_record_id", "hierarchy_node", ["run_record_id"])


def downgrade() -> None:
    op.drop_index("ix_hierarchy_node_run_record_id", table_name="hierarchy_node")
    op.drop_table("hierarchy_node")
