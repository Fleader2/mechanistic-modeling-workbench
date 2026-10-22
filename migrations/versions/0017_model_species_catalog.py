"""Model-Species Catalog Prerequisite increment: a durable, whole-model species/compartment
catalog, available without ever running a simulation.

See ``docs/26_model_species_catalog_prerequisite_increment.md``. Adds:

* Two new enums -- ``model_species_catalog_status`` (``AVAILABLE``/``UNAVAILABLE``,
  ``app.models.enums.ModelSpeciesCatalogStatus``) and ``model_species_kind``
  (``FLOATING``/``BOUNDARY``, ``app.models.enums.ModelSpeciesKind``).
* ``model_species_catalog`` -- one row per ``Model`` row, 1:1 (``ON DELETE CASCADE`` -- this
  table has no independent existence apart from describing that one Model, unlike
  ``time_series_dataset``'s own ``RESTRICT`` relationship to ``dataset_reference``). No row at
  all for a given ``model_id`` means "capture was never attempted" -- read identically to an
  explicit ``UNAVAILABLE`` row by every caller. Every row (success or failure) is pinned to the
  specific ``run_record`` that attempted it (``ON DELETE RESTRICT``).
* ``model_species`` -- one row per real, compiled species *verified* (via a real Antimony/
  RoadRunner load, never merely present in Agent 2's own structural network) to exist in the
  actually-loaded model. ``antimony_species_id`` is the one field a human ever sees or selects;
  ``canonical_species_id`` is internal provenance only. ``ON DELETE CASCADE`` from
  ``model_species_catalog`` (pure decomposition, no independent existence of its own).
* ``model_compartment`` -- the same real compartments, as their own validated set. ``ON DELETE
  CASCADE`` from ``model_species_catalog``.

No existing column is altered or dropped, and no existing row's data changes.

Revision ID: 0017_model_species_catalog
Revises: 0016_time_series_dataset
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import ModelSpeciesCatalogStatus, ModelSpeciesKind

revision: str = "0017_model_species_catalog"
down_revision: str | None = "0016_time_series_dataset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_model_species_catalog_status_enum = postgresql.ENUM(
    *[m.value for m in ModelSpeciesCatalogStatus], name="model_species_catalog_status"
)
_model_species_kind_enum = postgresql.ENUM(
    *[m.value for m in ModelSpeciesKind], name="model_species_kind"
)


def upgrade() -> None:
    bind = op.get_bind()
    _model_species_catalog_status_enum.create(bind, checkfirst=True)
    _model_species_kind_enum.create(bind, checkfirst=True)

    op.create_table(
        "model_species_catalog",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                *[m.value for m in ModelSpeciesCatalogStatus],
                name="model_species_catalog_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        sa.Column("source_run_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_antimony_artifact_reference", sa.Text(), nullable=True),
        sa.Column("source_antimony_checksum", sa.String(), nullable=True),
        sa.Column("unresolved_canonical_species_ids", sa.Text(), nullable=False),
        sa.Column("unmapped_canonical_species_ids", sa.Text(), nullable=False),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_species_catalog"),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["model.id"],
            name="fk_model_species_catalog_model_id_model",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_record_id"],
            ["run_record.id"],
            name="fk_model_species_catalog_source_run_record_id_rr",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("model_id", name="uq_model_species_catalog_model_id"),
    )
    op.create_index(
        "ix_model_species_catalog_model_id", "model_species_catalog", ["model_id"]
    )
    op.create_index(
        "ix_model_species_catalog_source_run_record_id",
        "model_species_catalog",
        ["source_run_record_id"],
    )

    op.create_table(
        "model_species",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_species_catalog_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("antimony_species_id", sa.Text(), nullable=False),
        sa.Column("canonical_species_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("compartment_id", sa.Text(), nullable=False),
        sa.Column("compartment_name", sa.String(), nullable=True),
        sa.Column(
            "kind",
            postgresql.ENUM(
                *[m.value for m in ModelSpeciesKind], name="model_species_kind", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("unit", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_model_species"),
        sa.ForeignKeyConstraint(
            ["model_species_catalog_id"],
            ["model_species_catalog.id"],
            name="fk_model_species_catalog_id_msc",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "model_species_catalog_id",
            "antimony_species_id",
            name="uq_model_species_catalog_id_antimony_species_id",
        ),
    )
    op.create_index(
        "ix_model_species_model_species_catalog_id", "model_species", ["model_species_catalog_id"]
    )

    op.create_table(
        "model_compartment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_species_catalog_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("compartment_id", sa.Text(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("volume_unit", sa.String(), nullable=True),
        sa.Column("species_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name="pk_model_compartment"),
        sa.ForeignKeyConstraint(
            ["model_species_catalog_id"],
            ["model_species_catalog.id"],
            name="fk_model_compartment_catalog_id_msc",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "model_species_catalog_id",
            "compartment_id",
            name="uq_model_compartment_catalog_id_compartment_id",
        ),
    )
    op.create_index(
        "ix_model_compartment_model_species_catalog_id",
        "model_compartment",
        ["model_species_catalog_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_compartment_model_species_catalog_id", table_name="model_compartment")
    op.drop_table("model_compartment")

    op.drop_index("ix_model_species_model_species_catalog_id", table_name="model_species")
    op.drop_table("model_species")

    op.drop_index(
        "ix_model_species_catalog_source_run_record_id", table_name="model_species_catalog"
    )
    op.drop_index("ix_model_species_catalog_model_id", table_name="model_species_catalog")
    op.drop_table("model_species_catalog")

    bind = op.get_bind()
    _model_species_kind_enum.drop(bind, checkfirst=True)
    _model_species_catalog_status_enum.drop(bind, checkfirst=True)
