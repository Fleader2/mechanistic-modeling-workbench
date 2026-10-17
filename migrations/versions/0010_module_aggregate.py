"""Hierarchical Aggregation of Module-Level Agent3/4/5 Results: persist an immutable,
versioned roll-up of module-level simulation/calibration/validation results, one per
(target, execution kind) -- never a blended score across unlike result types or children.

Adds:

* One new enum -- ``module_aggregate_completeness`` (``COMPLETE``/``PARTIAL``/``EMPTY``).
* ``module_aggregate`` -- one immutable row per (``target_model_module_id`` or hierarchy root,
  ``execution_kind``, ``version``). ``ON DELETE RESTRICT`` from both ``run_record`` and
  ``model_module`` (a durable provenance record, never ephemeral workflow bookkeeping, the
  identical precedent ``model_module``/``module_execution_snapshot`` already use). No
  ``updated_at`` column: this table is never updated after creation -- a new version is always
  a new row.

See ``docs/12_hierarchical_aggregation.md``.

Revision ID: 0010_module_aggregate
Revises: 0009_validation_execution_kind
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import ModuleAggregateCompleteness

revision: str = "0010_module_aggregate"
down_revision: str | None = "0009_validation_execution_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_module_aggregate_completeness_enum = postgresql.ENUM(
    *[m.value for m in ModuleAggregateCompleteness], name="module_aggregate_completeness"
)


def upgrade() -> None:
    bind = op.get_bind()
    _module_aggregate_completeness_enum.create(bind, checkfirst=True)

    op.create_table(
        "module_aggregate",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hierarchy_run_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_model_module_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "execution_kind",
            postgresql.ENUM(
                "SIMULATION",
                "CALIBRATION",
                "VALIDATION",
                name="module_execution_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "completeness_status",
            postgresql.ENUM(
                *[m.value for m in ModuleAggregateCompleteness],
                name="module_aggregate_completeness",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("input_fingerprint", sa.String(), nullable=False),
        sa.Column("summary_payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_module_aggregate"),
        sa.ForeignKeyConstraint(
            ["hierarchy_run_record_id"],
            ["run_record.id"],
            name="fk_module_aggregate_hierarchy_run_record_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_model_module_id"],
            ["model_module.id"],
            name="fk_module_aggregate_target_model_module_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_module_aggregate_target_model_module_id",
        "module_aggregate",
        ["target_model_module_id"],
    )
    op.create_index(
        "ix_module_aggregate_hierarchy_run_record_id",
        "module_aggregate",
        ["hierarchy_run_record_id", "execution_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_module_aggregate_hierarchy_run_record_id", table_name="module_aggregate")
    op.drop_index("ix_module_aggregate_target_model_module_id", table_name="module_aggregate")
    op.drop_table("module_aggregate")

    bind = op.get_bind()
    _module_aggregate_completeness_enum.drop(bind, checkfirst=True)
