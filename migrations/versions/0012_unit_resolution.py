"""Structured Units and Dimensional-Consistency Validation: persist a durable, content-
addressed cache of every raw unit string this Workbench has ever resolved against its own
``pint`` registry.

Adds:

* One new enum -- ``unit_parse_status`` (``PARSED``/``MALFORMED``/``MISSING``).
* ``unit_resolution`` -- one row per distinct, non-empty raw unit string on file
  (``source_unit_string`` unique), carrying its own normalized form, dimensionality, and parse
  status. No foreign keys in or out: a standalone lookup table, never joined against by any
  other table's own schema (callers resolve a string and get back a dict). No ``updated_at``
  column: never updated after creation.

See ``docs/14_structured_units.md``.

Revision ID: 0012_unit_resolution
Revises: 0011_cross_module_diagnostics
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import UnitParseStatus

revision: str = "0012_unit_resolution"
down_revision: str | None = "0011_cross_module_diagnostics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_unit_parse_status_enum = postgresql.ENUM(
    *[m.value for m in UnitParseStatus], name="unit_parse_status"
)


def upgrade() -> None:
    bind = op.get_bind()
    _unit_parse_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "unit_resolution",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_unit_string", sa.String(), nullable=False),
        sa.Column("normalized_unit", sa.String(), nullable=True),
        sa.Column("dimensionality", sa.String(), nullable=True),
        sa.Column(
            "parse_status",
            postgresql.ENUM(
                *[m.value for m in UnitParseStatus],
                name="unit_parse_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_unit_resolution"),
        sa.UniqueConstraint("source_unit_string", name="uq_unit_resolution_source_unit_string"),
    )


def downgrade() -> None:
    op.drop_table("unit_resolution")

    bind = op.get_bind()
    _unit_parse_status_enum.drop(bind, checkfirst=True)
