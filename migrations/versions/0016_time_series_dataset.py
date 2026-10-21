"""Downloadable Two-Tab Excel Template increment: time-series experimental dataset import.

See ``docs/25_time_series_dataset_import_increment.md``. Adds:

* One new enum -- ``measurement_value_status`` (``MEASURED``/``MISSING``/``NOT_APPLICABLE``/
  ``UNKNOWN``/``UNRECOGNIZED`` -- ``app.models.enums.MeasurementValueStatus``), the mapped
  column type for ``time_series_dataset_row.time_status``. The identical vocabulary is also
  used, as a plain string inside the JSON ``measurements`` column below, for each individual
  measurement value -- not itself a DB enum, since it lives inside a dynamic, per-dataset JSON
  blob rather than a fixed column.
* ``time_series_dataset`` -- one row per saved import, 1:1 with a ``dataset_reference`` row
  (reused as this dataset's own catalog entry, so it is automatically counted by the existing
  "Datasets" column on the Modeling Studies table -- no change needed there). Every structured
  metadata field is nullable: a blank field is an honest, disclosed gap (a non-blocking
  validation finding), never fabricated, never a reason this row cannot exist.
  ``validation_findings`` is the exact findings list computed at save time, persisted verbatim
  so a later reopen shows what was actually found then, never silently re-derived against a
  possibly-changed parser. ``ON DELETE RESTRICT`` from ``dataset_reference`` -- a durable,
  independently-meaningful scientific record, the same precedent ``module_execution_snapshot``
  already set for "has its own lineage," never the "no independent existence apart from its
  parent" ``CASCADE`` precedent.
* ``time_series_measurement_column`` -- one row per Data-tab measurement column (the exact,
  original header text, never renamed/aliased), ``CASCADE`` from ``time_series_dataset`` (pure
  decomposition of one import, no independent existence of its own).
* ``time_series_dataset_row`` -- one row per Data-tab data row. ``measurements`` is a JSON
  string (matching this repository's own established ``Text``-holding-JSON convention, e.g.
  ``module_execution_snapshot.snapshot_payload`` -- never a native JSONB column) mapping each
  measurement column's own exact name to ``{"status", "value", "raw"}`` -- "missing," "not
  applicable," "unknown," and "a real, reported zero" are four different recorded facts, never
  collapsed into one. ``CASCADE`` from ``time_series_dataset`` for the same reason as above.

No existing column is altered or dropped, and no existing row's data changes.

Revision ID: 0016_time_series_dataset
Revises: 0015_module_set_execution
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import MeasurementValueStatus

revision: str = "0016_time_series_dataset"
down_revision: str | None = "0015_module_set_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_measurement_value_status_enum = postgresql.ENUM(
    *[m.value for m in MeasurementValueStatus], name="measurement_value_status"
)


def upgrade() -> None:
    bind = op.get_bind()
    _measurement_value_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "time_series_dataset",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version", sa.String(), nullable=False),
        sa.Column("dataset_name", sa.String(), nullable=True),
        sa.Column("experimental_date", sa.String(), nullable=True),
        sa.Column("organism", sa.String(), nullable=True),
        sa.Column("cell_type", sa.String(), nullable=True),
        sa.Column("strain", sa.String(), nullable=True),
        sa.Column("experiment_type", sa.String(), nullable=True),
        sa.Column("measurement_type", sa.String(), nullable=True),
        sa.Column("scientific_objective", sa.Text(), nullable=True),
        sa.Column("conditions_treatments", sa.Text(), nullable=True),
        sa.Column("assay", sa.Text(), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("processing_normalization", sa.Text(), nullable=True),
        sa.Column("time_unit", sa.String(), nullable=True),
        sa.Column("condition_legend", sa.Text(), nullable=True),
        sa.Column("validation_findings", sa.Text(), nullable=False),
        sa.Column("saved_by", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_time_series_dataset"),
        sa.ForeignKeyConstraint(
            ["dataset_reference_id"],
            ["dataset_reference.id"],
            name="fk_time_series_dataset_dataset_reference_id_dr",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "dataset_reference_id", name="uq_time_series_dataset_dataset_reference_id"
        ),
    )

    op.create_table(
        "time_series_measurement_column",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("time_series_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("declared_in_metadata", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id", name="pk_time_series_measurement_column"),
        sa.ForeignKeyConstraint(
            ["time_series_dataset_id"],
            ["time_series_dataset.id"],
            name="fk_time_series_measurement_column_time_series_dataset_id_tsd",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "time_series_dataset_id",
            "column_name",
            name="uq_time_series_measurement_column_dataset_id_column_name",
        ),
    )
    op.create_index(
        "ix_time_series_measurement_column_time_series_dataset_id",
        "time_series_measurement_column",
        ["time_series_dataset_id"],
    )

    op.create_table(
        "time_series_dataset_row",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("time_series_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("sample_id", sa.String(), nullable=True),
        sa.Column("condition_id", sa.String(), nullable=True),
        sa.Column("biological_replicate", sa.String(), nullable=True),
        sa.Column("technical_replicate", sa.String(), nullable=True),
        sa.Column(
            "time_status",
            postgresql.ENUM(
                *[m.value for m in MeasurementValueStatus],
                name="measurement_value_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("time_value", sa.Numeric(), nullable=True),
        sa.Column("time_raw", sa.String(), nullable=True),
        sa.Column("measurements", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_time_series_dataset_row"),
        sa.ForeignKeyConstraint(
            ["time_series_dataset_id"],
            ["time_series_dataset.id"],
            name="fk_time_series_dataset_row_time_series_dataset_id_tsd",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "time_series_dataset_id",
            "row_index",
            name="uq_time_series_dataset_row_dataset_id_row_index",
        ),
    )
    op.create_index(
        "ix_time_series_dataset_row_time_series_dataset_id",
        "time_series_dataset_row",
        ["time_series_dataset_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_time_series_dataset_row_time_series_dataset_id",
        table_name="time_series_dataset_row",
    )
    op.drop_table("time_series_dataset_row")

    op.drop_index(
        "ix_time_series_measurement_column_time_series_dataset_id",
        table_name="time_series_measurement_column",
    )
    op.drop_table("time_series_measurement_column")

    op.drop_table("time_series_dataset")

    bind = op.get_bind()
    _measurement_value_status_enum.drop(bind, checkfirst=True)
