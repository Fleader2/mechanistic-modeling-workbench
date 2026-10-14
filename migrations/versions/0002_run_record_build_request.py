"""Scoped-Build Support increment: associate a ``RunRecord`` with the ``ModelBuildRequest``
that scoped it, and persist structured scoping warnings.

Adds two nullable columns to ``run_record``:

* ``model_build_request_id`` -- a ``RESTRICT`` foreign key to
  ``model_build_request.id``, mirroring ``run_record.model_id``'s own
  nullable/``RESTRICT`` shape exactly. ``RunRecord`` already records which
  request parameters produced one run (``model_id``); this is the
  identical kind of fact, added alongside it rather than onto ``Model``
  (a ``Model``'s own durable lineage is independent of which specific run
  attempt built it -- see ``docs/01_workbench_architecture.md``).
* ``warnings`` -- a nullable ``Text`` column holding a JSON-encoded list
  of warning strings (e.g. an unresolved ``ModelBuildRequest`` reference,
  an unsupported pathway constraint) returned by a scoped build. Plain
  ``Text``, not a native array/JSON column, matching every other
  "opaque, Workbench-never-interprets-this" field already on
  ``run_record`` (``artifact_reference``).

Both columns are nullable and additive; every pre-existing ``RunRecord``
row is unaffected, and no existing query or persistence function is
broken by their mere presence.

Revision ID: 0002_run_record_build_request
Revises: 0001_initial_workbench_schema
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_run_record_build_request"
down_revision: str | None = "0001_initial_workbench_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run_record",
        sa.Column("model_build_request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("run_record", sa.Column("warnings", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_run_record_model_build_request_id_mbr",
        "run_record",
        "model_build_request",
        ["model_build_request_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_run_record_model_build_request_id", "run_record", ["model_build_request_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_run_record_model_build_request_id", table_name="run_record")
    op.drop_constraint("fk_run_record_model_build_request_id_mbr", "run_record", type_="foreignkey")
    op.drop_column("run_record", "warnings")
    op.drop_column("run_record", "model_build_request_id")
