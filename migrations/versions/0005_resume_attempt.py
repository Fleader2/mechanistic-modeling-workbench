"""Crash-Safe Resume: a durable ``hierarchy_resume_attempt`` record so a hierarchy checkpoint
is never marked consumed until the Harness resume call has actually, durably succeeded.

Adds:

* ``hierarchy_resume_attempt_status`` -- a new, standalone enum type (``PENDING``/
  ``IN_PROGRESS``/``SUCCEEDED``/``FAILED``).
* ``hierarchy_resume_attempt`` -- one row per ``hierarchy_checkpoint`` (unique
  ``hierarchy_checkpoint_id``, so a repeated resume request for the identical checkpoint always
  finds and reuses this same row), ``CASCADE``-deleted from it (no independent meaning apart
  from the checkpoint it attempts to resume, identical precedent to every other table this
  increment's own predecessor added).

See ``docs/06_crash_safe_resume.md``.

Revision ID: 0005_resume_attempt
Revises: 0004_checkpoint_review
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import HierarchyResumeAttemptStatus

revision: str = "0005_resume_attempt"
down_revision: str | None = "0004_checkpoint_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_hierarchy_resume_attempt_status_enum = postgresql.ENUM(
    *[m.value for m in HierarchyResumeAttemptStatus], name="hierarchy_resume_attempt_status"
)


def upgrade() -> None:
    bind = op.get_bind()
    _hierarchy_resume_attempt_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "hierarchy_resume_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hierarchy_checkpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                *[m.value for m in HierarchyResumeAttemptStatus],
                name="hierarchy_resume_attempt_status",
                create_type=False,
            ),
            nullable=False,
            server_default=HierarchyResumeAttemptStatus.PENDING.value,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_hierarchy_resume_attempt"),
        sa.ForeignKeyConstraint(
            ["hierarchy_checkpoint_id"],
            ["hierarchy_checkpoint.id"],
            name="fk_hierarchy_resume_attempt_checkpoint_id_checkpoint",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "hierarchy_checkpoint_id", name="uq_hierarchy_resume_attempt_checkpoint_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("hierarchy_resume_attempt")

    bind = op.get_bind()
    _hierarchy_resume_attempt_status_enum.drop(bind, checkfirst=True)
