"""Hierarchical Review/Resume: persist the harness's own checkpoint/resume state, and make
``hierarchy_node`` insertion idempotent across resume.

Adds:

* ``RunStatus.REQUIRES_USER_REVIEW`` -- a new ``run_status`` enum value (one-way in PostgreSQL,
  exactly as migration ``0016_gotenzymes_source`` in the sibling ``agent1-biochemical-curator``
  repository already documents for ``SourceType.GOTENZYMES``: ``downgrade()`` leaves the value
  present but unused, since there is nothing else this migration adds to reverse).
* ``hierarchy_review_decision_value`` -- a new, small, standalone enum type (``APPROVE``/
  ``REJECT``).
* ``hierarchy_checkpoint`` -- one row per pause of one hierarchical-recursion ``run_record``,
  storing the harness's own ``serialize_checkpoint(...)`` payload verbatim. ``CASCADE``-deleted
  from ``run_record`` (no independent meaning apart from the run that produced it, identical
  precedent to ``hierarchy_node``'s own migration ``0003``).
* ``hierarchy_pending_review_item`` -- one row per pending module of one ``hierarchy_checkpoint``,
  ``CASCADE``-deleted from it.
* ``hierarchy_review_decision`` -- one row per decision, with a unique FK to
  ``hierarchy_pending_review_item`` (exactly one decision per pending item), ``CASCADE``-deleted
  from it.
* A new unique constraint on ``hierarchy_node(run_record_id, node_id)`` -- the database-level
  idempotency backstop for inserting only genuinely new nodes on each resume (see
  ``app.persistence.hierarchy_node.create_hierarchy_nodes``).

See ``docs/05_hierarchical_review_resume.md``.

Revision ID: 0004_checkpoint_review
Revises: 0003_hierarchy_node
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import HierarchyReviewDecisionValue

revision: str = "0004_checkpoint_review"
down_revision: str | None = "0003_hierarchy_node"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Transcribed verbatim from app.models.enums.RunStatus's one new member at the time this
# migration was written.
_NEW_RUN_STATUS_VALUES = ("REQUIRES_USER_REVIEW",)

_hierarchy_review_decision_value_enum = postgresql.ENUM(
    *[m.value for m in HierarchyReviewDecisionValue], name="hierarchy_review_decision_value"
)


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction that later uses the new
    # value (PostgreSQL restriction) -- this migration only adds the value and never uses it
    # itself, so no autocommit workaround is needed (identical precedent to
    # agent1-biochemical-curator's 0016_gotenzymes_source).
    for value in _NEW_RUN_STATUS_VALUES:
        op.execute(f"ALTER TYPE run_status ADD VALUE IF NOT EXISTS '{value}'")

    bind = op.get_bind()
    _hierarchy_review_decision_value_enum.create(bind, checkfirst=True)

    op.create_table(
        "hierarchy_checkpoint",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("checkpoint_version", sa.String(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("hierarchy_id", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_hierarchy_checkpoint"),
        sa.ForeignKeyConstraint(
            ["run_record_id"],
            ["run_record.id"],
            name="fk_hierarchy_checkpoint_run_record_id_run_record",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "run_record_id", "sequence", name="uq_hierarchy_checkpoint_run_record_id_sequence"
        ),
    )
    op.create_index("ix_hierarchy_checkpoint_run_record_id", "hierarchy_checkpoint", ["run_record_id"])

    op.create_table(
        "hierarchy_pending_review_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hierarchy_checkpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pending_id", sa.Text(), nullable=False),
        sa.Column("parent_node_id", sa.Text(), nullable=False),
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("reaction_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_hierarchy_pending_review_item"),
        sa.ForeignKeyConstraint(
            ["hierarchy_checkpoint_id"],
            ["hierarchy_checkpoint.id"],
            name="fk_hierarchy_pending_review_item_checkpoint_id_checkpoint",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "hierarchy_checkpoint_id",
            "pending_id",
            name="uq_hierarchy_pending_review_item_checkpoint_id_pending_id",
        ),
    )
    op.create_index(
        "ix_hierarchy_pending_review_item_hierarchy_checkpoint_id",
        "hierarchy_pending_review_item",
        ["hierarchy_checkpoint_id"],
    )

    op.create_table(
        "hierarchy_review_decision",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pending_review_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "decision",
            postgresql.ENUM(
                *[m.value for m in HierarchyReviewDecisionValue],
                name="hierarchy_review_decision_value",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_hierarchy_review_decision"),
        sa.ForeignKeyConstraint(
            ["pending_review_item_id"],
            ["hierarchy_pending_review_item.id"],
            name="fk_hierarchy_review_decision_pending_review_item_id_item",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "pending_review_item_id", name="uq_hierarchy_review_decision_pending_review_item_id"
        ),
    )

    op.create_unique_constraint(
        "uq_hierarchy_node_run_record_id_node_id", "hierarchy_node", ["run_record_id", "node_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_hierarchy_node_run_record_id_node_id", "hierarchy_node", type_="unique")

    op.drop_table("hierarchy_review_decision")

    op.drop_index(
        "ix_hierarchy_pending_review_item_hierarchy_checkpoint_id",
        table_name="hierarchy_pending_review_item",
    )
    op.drop_table("hierarchy_pending_review_item")

    op.drop_index("ix_hierarchy_checkpoint_run_record_id", table_name="hierarchy_checkpoint")
    op.drop_table("hierarchy_checkpoint")

    bind = op.get_bind()
    _hierarchy_review_decision_value_enum.drop(bind, checkfirst=True)

    # See module docstring: PostgreSQL cannot remove a single enum value without recreating the
    # whole type, and nothing else was added here to reverse.
