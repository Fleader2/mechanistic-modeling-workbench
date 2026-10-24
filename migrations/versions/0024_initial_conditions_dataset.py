"""Initial-Conditions Dataset Import increment: a new, long-format dataset type (one row per
target species/parameter, e.g. one protein or metabolite) for importing a cell type's own
initial protein/metabolite abundance profile, plus its own model-specific alias mapping
(mapping each distinct ``target_name`` to a real species or independent parameter).

See ``docs/36_initial_conditions_dataset_import_increment.md``. Purely additive. Mirrors the
already-applied ``time_series_dataset``/``dataset_model_alias_mapping`` tables in spirit, but
deliberately separate tables, never a generalization of them -- see
``app.models.initial_conditions_dataset``/``app.models.initial_conditions_alias_mapping`` module
docstrings for why. Adds:

* ``initial_conditions_dataset``, ``initial_conditions_measurement_column``,
  ``initial_conditions_measurement_uncertainty_column``, ``initial_conditions_dataset_row``.
* A new enum, ``initial_conditions_alias_mapping_target_kind`` (``SPECIES``/``PARAMETER``), plus
  ``initial_conditions_alias_mapping_revision``/``initial_conditions_alias_mapping_assignment``,
  reusing the already-existing ``alias_mapping_assignment_status``/``alias_mapping_unit_finding``
  enum types.

No existing table/column is altered.

Revision ID: 0024_initial_conditions_dataset
Revises: 0023_model_antimony_import
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import InitialConditionsAliasMappingTargetKind

revision: str = "0024_initial_conditions_dataset"
down_revision: str | None = "0023_model_antimony_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_initial_conditions_alias_mapping_target_kind_enum = postgresql.ENUM(
    *[m.value for m in InitialConditionsAliasMappingTargetKind],
    name="initial_conditions_alias_mapping_target_kind",
)


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "initial_conditions_dataset",
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
        sa.Column("validation_findings", sa.Text(), nullable=False),
        sa.Column("saved_by", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_initial_conditions_dataset"),
        sa.ForeignKeyConstraint(
            ["dataset_reference_id"],
            ["dataset_reference.id"],
            name="fk_initial_conditions_dataset_dataset_reference_id_dr",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "dataset_reference_id", name="uq_initial_conditions_dataset_dataset_reference_id"
        ),
    )
    op.create_index(
        "ix_initial_conditions_dataset_dataset_reference_id",
        "initial_conditions_dataset",
        ["dataset_reference_id"],
    )

    op.create_table(
        "initial_conditions_measurement_column",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initial_conditions_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "declared_in_metadata", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_initial_conditions_measurement_column"),
        sa.ForeignKeyConstraint(
            ["initial_conditions_dataset_id"],
            ["initial_conditions_dataset.id"],
            name="fk_ic_measurement_column_dataset_id_icd",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "initial_conditions_dataset_id",
            "column_name",
            name="uq_ic_measurement_column_dataset_id_column_name",
        ),
    )
    op.create_index(
        "ix_ic_measurement_column_dataset_id",
        "initial_conditions_measurement_column",
        ["initial_conditions_dataset_id"],
    )

    op.create_table(
        "initial_conditions_measurement_uncertainty_column",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initial_conditions_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=False),
        sa.Column("measurement_column_name", sa.Text(), nullable=False),
        sa.Column(
            "statistic_kind",
            postgresql.ENUM(
                name="uncertainty_statistic_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ic_measurement_uncertainty_column"),
        sa.ForeignKeyConstraint(
            ["initial_conditions_dataset_id"],
            ["initial_conditions_dataset.id"],
            name="fk_ic_measurement_uncertainty_column_dataset_id_icd",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "initial_conditions_dataset_id",
            "column_name",
            name="uq_ic_measurement_uncertainty_column_dataset_id_column_name",
        ),
    )
    op.create_index(
        "ix_ic_measurement_uncertainty_column_dataset_id",
        "initial_conditions_measurement_uncertainty_column",
        ["initial_conditions_dataset_id"],
    )

    op.create_table(
        "initial_conditions_dataset_row",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initial_conditions_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("target_name", sa.String(), nullable=True),
        sa.Column("measurements", sa.Text(), nullable=False),
        sa.Column(
            "measurement_uncertainty", sa.Text(), nullable=False, server_default="{}"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_initial_conditions_dataset_row"),
        sa.ForeignKeyConstraint(
            ["initial_conditions_dataset_id"],
            ["initial_conditions_dataset.id"],
            name="fk_ic_dataset_row_dataset_id_icd",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "initial_conditions_dataset_id",
            "row_index",
            name="uq_ic_dataset_row_dataset_id_row_index",
        ),
    )
    op.create_index(
        "ix_ic_dataset_row_dataset_id",
        "initial_conditions_dataset_row",
        ["initial_conditions_dataset_id"],
    )

    _initial_conditions_alias_mapping_target_kind_enum.create(bind, checkfirst=True)

    op.create_table(
        "initial_conditions_alias_mapping_revision",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initial_conditions_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_species_catalog_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_parameter_catalog_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("saved_by", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ic_alias_mapping_revision"),
        sa.ForeignKeyConstraint(
            ["initial_conditions_dataset_id"],
            ["initial_conditions_dataset.id"],
            name="fk_ic_alias_mapping_revision_dataset_id_icd",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["model.id"], name="fk_ic_alias_mapping_revision_model_id_m",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_species_catalog_id"],
            ["model_species_catalog.id"],
            name="fk_ic_alias_mapping_revision_species_catalog_id_msc",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_parameter_catalog_id"],
            ["model_parameter_catalog.id"],
            name="fk_ic_alias_mapping_revision_parameter_catalog_id_mpc",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "initial_conditions_dataset_id",
            "model_id",
            "revision_number",
            name="uq_ic_alias_mapping_revision_dataset_model_number",
        ),
    )
    op.create_index(
        "ix_ic_alias_mapping_revision_dataset_id",
        "initial_conditions_alias_mapping_revision",
        ["initial_conditions_dataset_id"],
    )
    op.create_index(
        "ix_ic_alias_mapping_revision_model_id",
        "initial_conditions_alias_mapping_revision",
        ["model_id"],
    )
    op.create_index(
        "ix_ic_alias_mapping_revision_species_catalog_id",
        "initial_conditions_alias_mapping_revision",
        ["model_species_catalog_id"],
    )
    op.create_index(
        "ix_ic_alias_mapping_revision_parameter_catalog_id",
        "initial_conditions_alias_mapping_revision",
        ["model_parameter_catalog_id"],
    )

    op.create_table(
        "initial_conditions_alias_mapping_assignment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="alias_mapping_assignment_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "target_kind",
            postgresql.ENUM(
                *[m.value for m in InitialConditionsAliasMappingTargetKind],
                name="initial_conditions_alias_mapping_target_kind",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column(
            "unit_finding",
            postgresql.ENUM(name="alias_mapping_unit_finding", create_type=False),
            nullable=True,
        ),
        sa.Column("unit_comparison_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ic_alias_mapping_assignment"),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["initial_conditions_alias_mapping_revision.id"],
            name="fk_ic_alias_mapping_assignment_revision_id_icamr",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "revision_id", "target_name", name="uq_ic_alias_mapping_assignment_revision_target"
        ),
    )
    op.create_index(
        "ix_ic_alias_mapping_assignment_revision_id",
        "initial_conditions_alias_mapping_assignment",
        ["revision_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ic_alias_mapping_assignment_revision_id",
        table_name="initial_conditions_alias_mapping_assignment",
    )
    op.drop_table("initial_conditions_alias_mapping_assignment")

    op.drop_index(
        "ix_ic_alias_mapping_revision_parameter_catalog_id",
        table_name="initial_conditions_alias_mapping_revision",
    )
    op.drop_index(
        "ix_ic_alias_mapping_revision_species_catalog_id",
        table_name="initial_conditions_alias_mapping_revision",
    )
    op.drop_index(
        "ix_ic_alias_mapping_revision_model_id",
        table_name="initial_conditions_alias_mapping_revision",
    )
    op.drop_index(
        "ix_ic_alias_mapping_revision_dataset_id",
        table_name="initial_conditions_alias_mapping_revision",
    )
    op.drop_table("initial_conditions_alias_mapping_revision")

    bind = op.get_bind()
    _initial_conditions_alias_mapping_target_kind_enum.drop(bind, checkfirst=True)

    op.drop_index("ix_ic_dataset_row_dataset_id", table_name="initial_conditions_dataset_row")
    op.drop_table("initial_conditions_dataset_row")

    op.drop_index(
        "ix_ic_measurement_uncertainty_column_dataset_id",
        table_name="initial_conditions_measurement_uncertainty_column",
    )
    op.drop_table("initial_conditions_measurement_uncertainty_column")

    op.drop_index(
        "ix_ic_measurement_column_dataset_id",
        table_name="initial_conditions_measurement_column",
    )
    op.drop_table("initial_conditions_measurement_column")

    op.drop_index(
        "ix_initial_conditions_dataset_dataset_reference_id",
        table_name="initial_conditions_dataset",
    )
    op.drop_table("initial_conditions_dataset")
