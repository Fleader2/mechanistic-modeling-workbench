"""Cross-Module Consistency and Reconciliation Diagnostics: persist a versioned batch of
detected cross-module inconsistency findings for one hierarchy run, without automatically
forcing reconciliation.

Adds:

* Three new enums -- ``cross_module_diagnostic_category`` (the seven detection categories),
  ``diagnostic_severity`` (``INFO``/``WARNING``/``ERROR``/``UNRESOLVED``), and
  ``diagnostic_review_status`` (``UNREVIEWED``/``REVIEWED``).
* ``cross_module_diagnostic_run`` -- one immutable, versioned row per invocation of the
  consistency sweep over one hierarchy run. ``ON DELETE RESTRICT`` from ``run_record`` (a
  durable provenance record, the identical precedent ``model_module``/``module_execution
  _snapshot``/``module_aggregate`` already use).
* ``cross_module_diagnostic`` -- one row per detected finding, ``ON DELETE CASCADE`` from
  ``cross_module_diagnostic_run`` (no independent meaning apart from the run batch that
  produced it). Its own ``review_status``/``review_note``/``reviewed_by``/``reviewed_at``
  columns are the one deliberately mutable field group this increment adds anywhere -- see
  ``app.models.cross_module_diagnostic``'s own module docstring.

See ``docs/13_cross_module_diagnostics.md``.

Revision ID: 0011_cross_module_diagnostics
Revises: 0010_module_aggregate
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import (
    CrossModuleDiagnosticCategory,
    DiagnosticReviewStatus,
    DiagnosticSeverity,
)

revision: str = "0011_cross_module_diagnostics"
down_revision: str | None = "0010_module_aggregate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_cross_module_diagnostic_category_enum = postgresql.ENUM(
    *[m.value for m in CrossModuleDiagnosticCategory], name="cross_module_diagnostic_category"
)
_diagnostic_severity_enum = postgresql.ENUM(
    *[m.value for m in DiagnosticSeverity], name="diagnostic_severity"
)
_diagnostic_review_status_enum = postgresql.ENUM(
    *[m.value for m in DiagnosticReviewStatus], name="diagnostic_review_status"
)


def upgrade() -> None:
    bind = op.get_bind()
    _cross_module_diagnostic_category_enum.create(bind, checkfirst=True)
    _diagnostic_severity_enum.create(bind, checkfirst=True)
    _diagnostic_review_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "cross_module_diagnostic_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hierarchy_run_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("input_fingerprint", sa.String(), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cross_module_diagnostic_run"),
        sa.ForeignKeyConstraint(
            ["hierarchy_run_record_id"],
            ["run_record.id"],
            name="fk_cross_module_diagnostic_run_hierarchy_run_record_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_cross_module_diagnostic_run_hierarchy_run_record_id",
        "cross_module_diagnostic_run",
        ["hierarchy_run_record_id"],
    )

    op.create_table(
        "cross_module_diagnostic",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("diagnostic_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(
                *[m.value for m in CrossModuleDiagnosticCategory],
                name="cross_module_diagnostic_category",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            postgresql.ENUM(
                *[m.value for m in DiagnosticSeverity],
                name="diagnostic_severity",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("affected_model_module_ids", sa.Text(), nullable=False),
        sa.Column("evidence_payload", sa.Text(), nullable=False),
        sa.Column(
            "review_status",
            postgresql.ENUM(
                *[m.value for m in DiagnosticReviewStatus],
                name="diagnostic_review_status",
                create_type=False,
            ),
            nullable=False,
            server_default=DiagnosticReviewStatus.UNREVIEWED.value,
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cross_module_diagnostic"),
        sa.ForeignKeyConstraint(
            ["diagnostic_run_id"],
            ["cross_module_diagnostic_run.id"],
            name="fk_cross_module_diagnostic_diagnostic_run_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_cross_module_diagnostic_diagnostic_run_id",
        "cross_module_diagnostic",
        ["diagnostic_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cross_module_diagnostic_diagnostic_run_id", table_name="cross_module_diagnostic"
    )
    op.drop_table("cross_module_diagnostic")

    op.drop_index(
        "ix_cross_module_diagnostic_run_hierarchy_run_record_id",
        table_name="cross_module_diagnostic_run",
    )
    op.drop_table("cross_module_diagnostic_run")

    bind = op.get_bind()
    _diagnostic_review_status_enum.drop(bind, checkfirst=True)
    _diagnostic_severity_enum.drop(bind, checkfirst=True)
    _cross_module_diagnostic_category_enum.drop(bind, checkfirst=True)
