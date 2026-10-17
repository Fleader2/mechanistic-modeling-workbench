"""Module-Level Agent5 Validation and Experimental Design: add ``VALIDATION`` as a new
``module_execution_kind`` enum value, so an Agent5 validation run can get its own immutable
``ModuleExecutionSnapshot`` row using the exact same table the Module-Level Agent4 Calibration
increment already added.

Adds:

* ``ModuleExecutionKind.VALIDATION`` -- a new ``module_execution_kind`` enum value (one-way in
  PostgreSQL, identical precedent to migration ``0004_checkpoint_review``'s own
  ``RunStatus.REQUIRES_USER_REVIEW`` addition: ``downgrade()`` leaves the value present but
  unused, since there is nothing else this migration adds to reverse).

No new table, no new column -- ``module_execution_snapshot`` itself (migration
``0008_module_execution_snapshot``) was already deliberately designed generic over every
``ModuleExecutionKind`` value from the start.

See ``docs/10_module_level_agent5_validation.md``.

Revision ID: 0009_validation_execution_kind
Revises: 0008_module_execution_snapshot
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009_validation_execution_kind"
down_revision: str | None = "0008_module_execution_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Transcribed verbatim from app.models.enums.ModuleExecutionKind's one new member at the time
# this migration was written.
_NEW_MODULE_EXECUTION_KIND_VALUES = ("VALIDATION",)


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction that later uses the new
    # value (PostgreSQL restriction) -- this migration only adds the value and never uses it
    # itself, so no autocommit workaround is needed (identical precedent to
    # 0004_checkpoint_review's own RunStatus.REQUIRES_USER_REVIEW addition).
    for value in _NEW_MODULE_EXECUTION_KIND_VALUES:
        op.execute(f"ALTER TYPE module_execution_kind ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL has no `DROP VALUE` for an enum type -- the added value is left in place,
    # simply unused again once no row references it, identical precedent to
    # 0004_checkpoint_review's own downgrade.
    pass
