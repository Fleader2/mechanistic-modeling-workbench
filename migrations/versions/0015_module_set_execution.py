"""Module-Set Edited-Module Materialization increment, Phase B: boundary review and execution
for one module-set member's own current, possibly-edited reaction selection.

See ``docs/24_module_set_execution_increment.md``. Adds:

* ``module_set_member_review`` -- one mutable row per ``module_set_member`` (unique), carrying
  ``review_version`` (optimistic-concurrency token for boundary-decision submissions) and
  ``derived_at``. Never the member row itself -- ``ModuleSetMember``/``ModuleSetVersion`` stay
  exactly as immutable as the Manual Editing increment already made them.
* ``module_set_member_boundary_port`` -- one row per ``(review, species_id, direction)``,
  structurally identical to ``module_boundary_port`` (reuses its own three enums), but scoped
  to a module-set member's own review rather than a real ``model_module_id`` -- a module-set
  member's boundary review is its own, independently-versioned record, never a rewrite of the
  real module's own global ``ModuleBoundaryPort`` rows.
* ``run_record.module_set_member_id`` (nullable FK, ``RESTRICT``) -- distinguishes a module-
  set-scoped simulation run from an ordinary unedited-module one (which sets
  ``model_module_id`` alone, unchanged). A partial unique index enforces at most one active
  (``PENDING``/``RUNNING``) run per member at a time -- true duplicate-submission protection
  at the database level, the identical mechanism ``uq_module_set_draft_open_per_set`` already
  uses for "at most one OPEN draft per set."

**No existing column is altered or dropped, and no existing row's data changes.** Every
pre-existing ``run_record`` row gets ``module_set_member_id=NULL`` -- exactly its own honest
"not a module-set-scoped run" state, both before and after this migration.

Revision ID: 0015_module_set_execution
Revises: 0014_module_set_editing
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_module_set_execution"
down_revision: str | None = "0014_module_set_editing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_set_member_review",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_set_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("derived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_module_set_member_review"),
        sa.ForeignKeyConstraint(
            ["module_set_member_id"],
            ["module_set_member.id"],
            name="fk_module_set_member_review_module_set_member_id_msm",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "module_set_member_id", name="uq_module_set_member_review_module_set_member_id"
        ),
    )
    op.create_index(
        "ix_module_set_member_review_module_set_member_id",
        "module_set_member_review",
        ["module_set_member_id"],
    )

    op.create_table(
        "module_set_member_boundary_port",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("species_id", sa.Text(), nullable=False),
        sa.Column(
            "direction",
            postgresql.ENUM(name="module_port_direction", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "treatment_type",
            postgresql.ENUM(name="module_boundary_treatment_type", create_type=False),
            nullable=False,
            server_default="UNRESOLVED",
        ),
        sa.Column(
            "resolution_status",
            postgresql.ENUM(name="module_boundary_resolution_status", create_type=False),
            nullable=False,
            server_default="PENDING_REVIEW",
        ),
        sa.Column("initial_value", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_module_set_member_boundary_port"),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["module_set_member_review.id"],
            name="fk_module_set_member_boundary_port_review_id_msmr",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "review_id",
            "species_id",
            "direction",
            name="uq_module_set_member_boundary_port_review_species_direction",
        ),
    )
    op.create_index(
        "ix_module_set_member_boundary_port_review_id",
        "module_set_member_boundary_port",
        ["review_id"],
    )

    op.add_column(
        "run_record",
        sa.Column("module_set_member_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_run_record_module_set_member_id_msm",
        "run_record",
        "module_set_member",
        ["module_set_member_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_run_record_module_set_member_id", "run_record", ["module_set_member_id"])
    op.create_index(
        "uq_run_record_one_active_run_per_module_set_member",
        "run_record",
        ["module_set_member_id"],
        unique=True,
        postgresql_where=sa.text(
            "module_set_member_id IS NOT NULL AND status IN ('PENDING', 'RUNNING')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_run_record_one_active_run_per_module_set_member", table_name="run_record")
    op.drop_index("ix_run_record_module_set_member_id", table_name="run_record")
    op.drop_constraint("fk_run_record_module_set_member_id_msm", "run_record", type_="foreignkey")
    op.drop_column("run_record", "module_set_member_id")

    op.drop_index(
        "ix_module_set_member_boundary_port_review_id",
        table_name="module_set_member_boundary_port",
    )
    op.drop_table("module_set_member_boundary_port")

    op.drop_index(
        "ix_module_set_member_review_module_set_member_id",
        table_name="module_set_member_review",
    )
    op.drop_table("module_set_member_review")
