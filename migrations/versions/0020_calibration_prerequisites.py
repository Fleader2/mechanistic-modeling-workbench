"""Joint Calibration Workflow, configuration-prerequisites increment.

See ``docs/31_joint_calibration_configuration_prerequisites_increment.md``. Adds:

* Two new enums: ``model_parameter_catalog_status``, ``model_parameter_kind``.
* ``model_parameter_catalog``/``model_parameter`` -- a durable, whole-model parameter catalog,
  the sibling of the already-existing ``model_species_catalog``/``model_species`` (0017).
* ``time_series_independent_variable_column`` -- the sibling of the already-existing
  ``time_series_measurement_column`` (0016), for Data-tab columns declared as model inputs.
* ``time_series_dataset_row.independent_variables`` -- a new, additive column mirroring the
  already-existing ``measurements`` column exactly, defaulted to ``'{}'`` so every row saved
  before this increment reads back byte-identical to before.

No existing column is altered or dropped, and no existing row's data changes.

Revision ID: 0020_calibration_prerequisites
Revises: 0019_calibration_configuration
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import ModelParameterCatalogStatus, ModelParameterKind

revision: str = "0020_calibration_prerequisites"
down_revision: str | None = "0019_calibration_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_model_parameter_catalog_status_enum = postgresql.ENUM(
    *[m.value for m in ModelParameterCatalogStatus], name="model_parameter_catalog_status"
)
_model_parameter_kind_enum = postgresql.ENUM(
    *[m.value for m in ModelParameterKind], name="model_parameter_kind"
)


def upgrade() -> None:
    bind = op.get_bind()
    _model_parameter_catalog_status_enum.create(bind, checkfirst=True)
    _model_parameter_kind_enum.create(bind, checkfirst=True)

    op.create_table(
        "model_parameter_catalog",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                *[m.value for m in ModelParameterCatalogStatus],
                name="model_parameter_catalog_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        sa.Column("source_run_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_antimony_artifact_reference", sa.Text(), nullable=True),
        sa.Column("source_antimony_checksum", sa.String(), nullable=True),
        sa.Column("unresolved_canonical_parameter_ids", sa.Text(), nullable=False),
        sa.Column("unmapped_canonical_parameter_ids", sa.Text(), nullable=False),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_parameter_catalog"),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["model.id"],
            name="fk_model_parameter_catalog_model_id_model",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_record_id"],
            ["run_record.id"],
            name="fk_model_parameter_catalog_source_run_record_id_rr",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("model_id", name="uq_model_parameter_catalog_model_id"),
    )
    op.create_index(
        "ix_model_parameter_catalog_model_id", "model_parameter_catalog", ["model_id"]
    )
    op.create_index(
        "ix_model_parameter_catalog_source_run_record_id",
        "model_parameter_catalog",
        ["source_run_record_id"],
    )

    op.create_table(
        "model_parameter",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_parameter_catalog_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("antimony_parameter_id", sa.Text(), nullable=False),
        sa.Column("canonical_parameter_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column(
            "kind",
            postgresql.ENUM(
                *[m.value for m in ModelParameterKind],
                name="model_parameter_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("lower_bound", sa.Numeric(), nullable=True),
        sa.Column("upper_bound", sa.Numeric(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_model_parameter"),
        sa.ForeignKeyConstraint(
            ["model_parameter_catalog_id"],
            ["model_parameter_catalog.id"],
            name="fk_model_parameter_catalog_id_mpc",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "model_parameter_catalog_id",
            "antimony_parameter_id",
            name="uq_model_parameter_catalog_id_antimony_parameter_id",
        ),
    )
    op.create_index(
        "ix_model_parameter_catalog_id", "model_parameter", ["model_parameter_catalog_id"]
    )

    op.create_table(
        "time_series_independent_variable_column",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("time_series_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_time_series_independent_variable_column"),
        sa.ForeignKeyConstraint(
            ["time_series_dataset_id"],
            ["time_series_dataset.id"],
            name="fk_time_series_independent_variable_column_dataset_id_tsd",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "time_series_dataset_id",
            "column_name",
            name="uq_ts_independent_variable_column_dataset_id_column_name",
        ),
    )
    op.create_index(
        "ix_time_series_independent_variable_column_dataset_id",
        "time_series_independent_variable_column",
        ["time_series_dataset_id"],
    )

    op.add_column(
        "time_series_dataset_row",
        sa.Column(
            "independent_variables", sa.Text(), nullable=False, server_default="{}"
        ),
    )


def downgrade() -> None:
    op.drop_column("time_series_dataset_row", "independent_variables")

    op.drop_index(
        "ix_time_series_independent_variable_column_dataset_id",
        table_name="time_series_independent_variable_column",
    )
    op.drop_table("time_series_independent_variable_column")

    op.drop_index("ix_model_parameter_catalog_id", table_name="model_parameter")
    op.drop_table("model_parameter")

    op.drop_index(
        "ix_model_parameter_catalog_source_run_record_id", table_name="model_parameter_catalog"
    )
    op.drop_index("ix_model_parameter_catalog_model_id", table_name="model_parameter_catalog")
    op.drop_table("model_parameter_catalog")

    bind = op.get_bind()
    _model_parameter_kind_enum.drop(bind, checkfirst=True)
    _model_parameter_catalog_status_enum.drop(bind, checkfirst=True)
