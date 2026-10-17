"""Executable-Module Materialization: persist accepted hierarchy modules as durable,
first-class execution targets, and link an Agent 3 module-simulation run back to one.

Adds:

* ``hierarchy_node.attach_payload`` -- a new, nullable, opaque ``TEXT`` column: the exact
  payload the harness used to materialize that node's own submodel (``NULL`` for the root node
  and for a node never actually materialized), threaded through from the harness's own new
  ``HierarchyNodeRecord.attach_payload`` field.
* ``model_module`` -- one row per depth>=1 ``HierarchyNode`` that was genuinely materialized
  (``attach_payload IS NOT NULL``). ``ON DELETE RESTRICT`` from ``run_record``/
  ``hierarchy_node``/``model`` -- unlike every CASCADE-deleted table the Hierarchical Review/
  Resume increment added, a ``ModelModule`` is a durable execution target with its own
  independent lineage, the identical precedent ``model`` itself already uses, never the
  "no independent existence apart from its parent" precedent.
* ``run_record.model_module_id`` -- a new, nullable, ``RESTRICT`` foreign key: which
  ``ModelModule`` (if any) an Agent 3 module-simulation run simulated.

See ``docs/07_executable_module_materialization.md``.

Revision ID: 0006_model_module
Revises: 0005_resume_attempt
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_model_module"
down_revision: str | None = "0005_resume_attempt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hierarchy_node", sa.Column("attach_payload", sa.Text(), nullable=True))

    op.create_table(
        "model_module",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hierarchy_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_model_module_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("root_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("source_modularization_id", sa.Text(), nullable=False),
        sa.Column("child_submodel_id", sa.Text(), nullable=True),
        sa.Column("attach_payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_module"),
        sa.ForeignKeyConstraint(
            ["run_record_id"],
            ["run_record.id"],
            name="fk_model_module_run_record_id_run_record",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["hierarchy_node_id"],
            ["hierarchy_node.id"],
            name="fk_model_module_hierarchy_node_id_hierarchy_node",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_model_module_id"],
            ["model_module.id"],
            name="fk_model_module_parent_model_module_id_mm",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["root_model_id"],
            ["model.id"],
            name="fk_model_module_root_model_id_model",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("hierarchy_node_id", name="uq_model_module_hierarchy_node_id"),
    )
    op.create_index("ix_model_module_run_record_id", "model_module", ["run_record_id"])

    op.add_column("run_record", sa.Column("model_module_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_run_record_model_module_id_mm",
        "run_record",
        "model_module",
        ["model_module_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_run_record_model_module_id", "run_record", ["model_module_id"])


def downgrade() -> None:
    op.drop_index("ix_run_record_model_module_id", table_name="run_record")
    op.drop_constraint("fk_run_record_model_module_id_mm", "run_record", type_="foreignkey")
    op.drop_column("run_record", "model_module_id")

    op.drop_index("ix_model_module_run_record_id", table_name="model_module")
    op.drop_table("model_module")

    op.drop_column("hierarchy_node", "attach_payload")
