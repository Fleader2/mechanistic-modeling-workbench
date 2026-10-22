"""Model-Specific Alias Mapping increment: a scientist's own assignment of each time-series
dataset measurement column to an exact, real Antimony species identifier (or an explicit
decision to skip it), for one specific (dataset, model) pair.

See ``docs/27_model_specific_alias_mapping_increment.md``. Adds:

* Two new enums -- ``alias_mapping_assignment_status`` (``ASSIGNED``/``SKIPPED``/
  ``UNRESOLVED``, ``app.models.enums.AliasMappingAssignmentStatus``) and
  ``alias_mapping_unit_finding`` (``COMPATIBLE``/``INCOMPATIBLE``/``UNKNOWN``,
  ``app.models.enums.AliasMappingUnitFinding``).
* ``dataset_model_alias_mapping_revision`` -- one immutable, complete snapshot per save, for
  one (``time_series_dataset_id``, ``model_id``) pair. ``revision_number`` increments per
  pair, never reused. ``ON DELETE RESTRICT`` from ``time_series_dataset``/``model``/
  ``model_species_catalog`` -- every one of the three is an independently-meaningful record
  this revision's own provenance depends on, never silently orphaned.
* ``dataset_model_alias_mapping_assignment`` -- one row per measurement column, per revision.
  ``ON DELETE CASCADE`` from ``dataset_model_alias_mapping_revision`` (pure decomposition).

No existing column is altered or dropped, and no existing row's data changes.

Revision ID: 0018_dataset_model_alias_mapping
Revises: 0017_model_species_catalog
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import AliasMappingAssignmentStatus, AliasMappingUnitFinding

revision: str = "0018_dataset_model_alias_mapping"
down_revision: str | None = "0017_model_species_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_alias_mapping_assignment_status_enum = postgresql.ENUM(
    *[m.value for m in AliasMappingAssignmentStatus], name="alias_mapping_assignment_status"
)
_alias_mapping_unit_finding_enum = postgresql.ENUM(
    *[m.value for m in AliasMappingUnitFinding], name="alias_mapping_unit_finding"
)


def upgrade() -> None:
    bind = op.get_bind()
    _alias_mapping_assignment_status_enum.create(bind, checkfirst=True)
    _alias_mapping_unit_finding_enum.create(bind, checkfirst=True)

    op.create_table(
        "dataset_model_alias_mapping_revision",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("time_series_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_species_catalog_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("saved_by", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_alias_mapping_revision"),
        sa.ForeignKeyConstraint(
            ["time_series_dataset_id"],
            ["time_series_dataset.id"],
            name="fk_alias_mapping_revision_dataset_id_tsd",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["model.id"],
            name="fk_alias_mapping_revision_model_id_model",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_species_catalog_id"],
            ["model_species_catalog.id"],
            name="fk_alias_mapping_revision_catalog_id_msc",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "time_series_dataset_id",
            "model_id",
            "revision_number",
            name="uq_alias_mapping_revision_dataset_model_number",
        ),
    )
    op.create_index(
        "ix_alias_mapping_revision_dataset_id",
        "dataset_model_alias_mapping_revision",
        ["time_series_dataset_id"],
    )
    op.create_index(
        "ix_alias_mapping_revision_model_id",
        "dataset_model_alias_mapping_revision",
        ["model_id"],
    )
    op.create_index(
        "ix_alias_mapping_revision_catalog_id",
        "dataset_model_alias_mapping_revision",
        ["model_species_catalog_id"],
    )

    op.create_table(
        "dataset_model_alias_mapping_assignment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                *[m.value for m in AliasMappingAssignmentStatus],
                name="alias_mapping_assignment_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("target_antimony_species_id", sa.Text(), nullable=True),
        sa.Column(
            "unit_finding",
            postgresql.ENUM(
                *[m.value for m in AliasMappingUnitFinding],
                name="alias_mapping_unit_finding",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("unit_comparison_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_alias_mapping_assignment"),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["dataset_model_alias_mapping_revision.id"],
            name="fk_alias_mapping_assignment_revision_id_amr",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "revision_id", "column_name", name="uq_alias_mapping_assignment_revision_column"
        ),
    )
    op.create_index(
        "ix_alias_mapping_assignment_revision_id",
        "dataset_model_alias_mapping_assignment",
        ["revision_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_alias_mapping_assignment_revision_id",
        table_name="dataset_model_alias_mapping_assignment",
    )
    op.drop_table("dataset_model_alias_mapping_assignment")

    op.drop_index(
        "ix_alias_mapping_revision_catalog_id", table_name="dataset_model_alias_mapping_revision"
    )
    op.drop_index(
        "ix_alias_mapping_revision_model_id", table_name="dataset_model_alias_mapping_revision"
    )
    op.drop_index(
        "ix_alias_mapping_revision_dataset_id", table_name="dataset_model_alias_mapping_revision"
    )
    op.drop_table("dataset_model_alias_mapping_revision")

    bind = op.get_bind()
    _alias_mapping_unit_finding_enum.drop(bind, checkfirst=True)
    _alias_mapping_assignment_status_enum.drop(bind, checkfirst=True)
