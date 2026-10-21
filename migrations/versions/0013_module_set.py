"""Module-Set Domain Model, first increment: a durable, versioned, user-curated grouping of
``ModelModule`` rows, additive above the existing hierarchy/materialization schema.

See ``docs/20_module_set_domain_contract.md`` (the full proposal, as revised) and
``docs/21_module_set_first_increment.md`` (what this increment actually implements).

Adds:

* Two new enum types -- ``module_set_origin_method`` (``AUTOMATED``/``MANUAL``/``MIXED_EDITED``)
  and ``module_set_draft_status`` (``OPEN``/``DISCARDED``/``SAVED``).
* ``module_set`` -- one durable identity row per named, study-scoped module-partitioning scheme.
* ``module_set_version`` -- one immutable, saved version per set, pinning exactly one ``model``
  row. ``RESTRICT`` from `module_set`/`model`/`run_record` -- a durable record with its own
  independent lineage, never "no independent existence apart from its parent."
* ``module_set_member`` -- one row per module in one saved version, ``CASCADE``-deleted from its
  owning version (no independent meaning apart from it), always referencing a real, pre-existing
  ``model_module`` row (``RESTRICT`` -- a module materialized before this version existed outlives
  being merely *referenced* by it).
* ``module_set_draft`` -- mutable working state, ``RESTRICT`` throughout (a durable record of what
  was drafted, even once discarded -- soft-marked, never dropped). A partial unique index enforces
  at most one ``OPEN`` draft per existing set at a time.
* ``module_set_draft_member`` -- one row per module in one draft, ``CASCADE``-deleted from its
  owning draft, always referencing a real, pre-existing ``model_module`` row (``RESTRICT``).

**No column on any existing table is added, dropped, or altered.** In particular,
``model_module.run_record_id`` stays exactly as it is today (``NOT NULL``) -- the schema change
`docs/20` originally proposed for it is deferred to whichever increment builds manual module
editing, after a dependency audit found it would break four already-shipped execution/derivation
entrypoints if applied now (`docs/20` §2.1). This increment's own ``module_set_member``/
``module_set_draft_member`` rows only ever *reference* an existing, unedited ``model_module`` row;
they never need one to exist without a real hierarchical run behind it.

Revision ID: 0013_module_set
Revises: 0012_unit_resolution
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import ModuleSetDraftStatus, ModuleSetOriginMethod

revision: str = "0013_module_set"
down_revision: str | None = "0012_unit_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_module_set_origin_method_enum = postgresql.ENUM(
    *[m.value for m in ModuleSetOriginMethod], name="module_set_origin_method"
)
_module_set_draft_status_enum = postgresql.ENUM(
    *[m.value for m in ModuleSetDraftStatus], name="module_set_draft_status"
)


def upgrade() -> None:
    bind = op.get_bind()
    _module_set_origin_method_enum.create(bind, checkfirst=True)
    _module_set_draft_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "module_set",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subproject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stable_identifier", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_module_set"),
        sa.ForeignKeyConstraint(
            ["subproject_id"],
            ["subproject.id"],
            name="fk_module_set_subproject_id_subproject",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_module_set_subproject_id", "module_set", ["subproject_id"])

    op.create_table(
        "module_set_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "origin_method",
            postgresql.ENUM(
                *[m.value for m in ModuleSetOriginMethod],
                name="module_set_origin_method",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("generation_run_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_note", sa.Text(), nullable=True),
        sa.Column(
            "saved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("saved_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_module_set_version"),
        sa.ForeignKeyConstraint(
            ["module_set_id"],
            ["module_set.id"],
            name="fk_module_set_version_module_set_id_ms",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["model.id"],
            name="fk_module_set_version_model_id_model",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["generation_run_record_id"],
            ["run_record.id"],
            name="fk_module_set_version_generation_run_record_id_rr",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"],
            ["module_set_version.id"],
            name="fk_module_set_version_base_version_id_msv",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "module_set_id", "version", name="uq_module_set_version_set_id_version"
        ),
    )
    op.create_index("ix_module_set_version_module_set_id", "module_set_version", ["module_set_id"])

    op.create_table(
        "module_set_member",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_set_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_module_set_member"),
        sa.ForeignKeyConstraint(
            ["module_set_version_id"],
            ["module_set_version.id"],
            name="fk_module_set_member_module_set_version_id_msv",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_module_id"],
            ["model_module.id"],
            name="fk_module_set_member_model_module_id_mm",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_module_set_member_module_set_version_id", "module_set_member", ["module_set_version_id"]
    )

    op.create_table(
        "module_set_draft",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subproject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_set_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("base_run_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "origin_method",
            postgresql.ENUM(
                *[m.value for m in ModuleSetOriginMethod],
                name="module_set_origin_method",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                *[m.value for m in ModuleSetDraftStatus],
                name="module_set_draft_status",
                create_type=False,
            ),
            nullable=False,
            server_default=ModuleSetDraftStatus.OPEN.value,
        ),
        sa.Column("resulting_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_module_set_draft"),
        sa.ForeignKeyConstraint(
            ["subproject_id"],
            ["subproject.id"],
            name="fk_module_set_draft_subproject_id_subproject",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["model.id"],
            name="fk_module_set_draft_model_id_model",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["module_set_id"],
            ["module_set.id"],
            name="fk_module_set_draft_module_set_id_ms",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"],
            ["module_set_version.id"],
            name="fk_module_set_draft_base_version_id_msv",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_run_record_id"],
            ["run_record.id"],
            name="fk_module_set_draft_base_run_record_id_rr",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resulting_version_id"],
            ["module_set_version.id"],
            name="fk_module_set_draft_resulting_version_id_msv",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_module_set_draft_subproject_id", "module_set_draft", ["subproject_id"])
    op.create_index(
        "uq_module_set_draft_open_per_set",
        "module_set_draft",
        ["module_set_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN' AND module_set_id IS NOT NULL"),
    )

    op.create_table(
        "module_set_draft_member",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_module_set_draft_member"),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["module_set_draft.id"],
            name="fk_module_set_draft_member_draft_id_msd",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_module_id"],
            ["model_module.id"],
            name="fk_module_set_draft_member_model_module_id_mm",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_module_set_draft_member_draft_id", "module_set_draft_member", ["draft_id"])


def downgrade() -> None:
    op.drop_index("ix_module_set_draft_member_draft_id", table_name="module_set_draft_member")
    op.drop_table("module_set_draft_member")

    op.drop_index("uq_module_set_draft_open_per_set", table_name="module_set_draft")
    op.drop_index("ix_module_set_draft_subproject_id", table_name="module_set_draft")
    op.drop_table("module_set_draft")

    op.drop_index("ix_module_set_member_module_set_version_id", table_name="module_set_member")
    op.drop_table("module_set_member")

    op.drop_index("ix_module_set_version_module_set_id", table_name="module_set_version")
    op.drop_table("module_set_version")

    op.drop_index("ix_module_set_subproject_id", table_name="module_set")
    op.drop_table("module_set")

    bind = op.get_bind()
    _module_set_draft_status_enum.drop(bind, checkfirst=True)
    _module_set_origin_method_enum.drop(bind, checkfirst=True)
