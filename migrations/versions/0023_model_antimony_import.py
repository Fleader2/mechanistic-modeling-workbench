"""Whole-Model Antimony Import increment: let a user upload an already-written Antimony text
file directly, bypassing the Agent1->Agent2 build pipeline, verified and cataloged through the
same downstream pipeline an Agent2-built model already uses.

See ``docs/34_whole_model_antimony_import_increment.md``. Adds:

* ``model_import_provenance`` -- one immutable row per imported ``Model`` (``model_id``
  unique, 1:1; never created for a ``GENERATED``/``DERIVED`` model), recording the uploaded
  file's own original filename, its byte-for-byte-preserved artifact reference and checksum,
  user-supplied source/reference and verification notes, and Agent 2's own import
  fidelity-audit findings (rule/event counts, any rejected construct). ``ON DELETE RESTRICT``
  from both ``model`` and ``run_record``, mirroring ``module_execution_snapshot``'s own
  identical "durable provenance, never ephemeral" precedent.

No existing column is altered or dropped, and no existing row's data changes.
``Model.source_type=IMPORTED`` already existed, schema-ready, with zero production callers
before this increment (``app.models.enums.ModelSourceType``) -- this migration adds no new
enum value.

Revision ID: 0023_model_antimony_import
Revises: 0022_calibration_scenario_eval
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_model_antimony_import"
down_revision: str | None = "0022_calibration_scenario_eval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_import_provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("original_artifact_reference", sa.Text(), nullable=False),
        sa.Column("original_checksum", sa.String(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("verification_notes", sa.Text(), nullable=True),
        sa.Column("import_succeeded", sa.Boolean(), nullable=False),
        sa.Column("import_error_kind", sa.String(), nullable=True),
        sa.Column("import_message", sa.Text(), nullable=True),
        sa.Column("assignment_rule_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rate_rule_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("algebraic_rule_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("antimony_import_parser_version", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_model_import_provenance"),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["model.id"],
            name="fk_model_import_provenance_model_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_record_id"],
            ["run_record.id"],
            name="fk_model_import_provenance_run_record_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("model_id", name="uq_model_import_provenance_model_id"),
    )
    op.create_index(
        "ix_model_import_provenance_model_id", "model_import_provenance", ["model_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_model_import_provenance_model_id", table_name="model_import_provenance")
    op.drop_table("model_import_provenance")
