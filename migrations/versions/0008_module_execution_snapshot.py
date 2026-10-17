"""Module-Level Agent4 Calibration with Immutable Execution-Condition Provenance: persist an
immutable, versioned record of exactly what was used to execute one module-scoped Agent 3/
Agent 4 run.

Adds:

* One new enum -- ``module_execution_kind`` (``SIMULATION``/``CALIBRATION``).
* ``module_execution_snapshot`` -- one row per module-scoped execution (``run_record_id``
  unique, 1:1), ``ON DELETE RESTRICT`` from both ``model_module`` and ``run_record`` (a
  durable provenance record, never ephemeral workflow bookkeeping, the identical precedent
  ``model_module`` itself already uses). No ``updated_at`` column: this table is never
  updated after creation.

See ``docs/09_module_level_agent4_calibration.md``.

Revision ID: 0008_module_execution_snapshot
Revises: 0007_module_boundary_port
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import ModuleExecutionKind

revision: str = "0008_module_execution_snapshot"
down_revision: str | None = "0007_module_boundary_port"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_module_execution_kind_enum = postgresql.ENUM(
    *[m.value for m in ModuleExecutionKind], name="module_execution_kind"
)


def upgrade() -> None:
    bind = op.get_bind()
    _module_execution_kind_enum.create(bind, checkfirst=True)

    op.create_table(
        "module_execution_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "execution_kind",
            postgresql.ENUM(
                *[m.value for m in ModuleExecutionKind],
                name="module_execution_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("module_artifact_hash", sa.String(), nullable=False),
        sa.Column("snapshot_payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_module_execution_snapshot"),
        sa.ForeignKeyConstraint(
            ["model_module_id"],
            ["model_module.id"],
            name="fk_module_execution_snapshot_model_module_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_record_id"],
            ["run_record.id"],
            name="fk_module_execution_snapshot_run_record_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("run_record_id", name="uq_module_execution_snapshot_run_record_id"),
    )
    op.create_index(
        "ix_module_execution_snapshot_model_module_id",
        "module_execution_snapshot",
        ["model_module_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_module_execution_snapshot_model_module_id", table_name="module_execution_snapshot"
    )
    op.drop_table("module_execution_snapshot")

    bind = op.get_bind()
    _module_execution_kind_enum.drop(bind, checkfirst=True)
