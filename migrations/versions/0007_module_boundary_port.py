"""Boundary-Condition Semantics: persist explicit boundary-condition treatment decisions for
one ``ModelModule``'s own boundary species, and track that module's own readiness to be
simulated.

Adds:

* Three new enum types -- ``module_port_direction`` (the Workbench's own copy of Agent 2's
  identical ``ModulePortDirection`` vocabulary), ``module_boundary_treatment_type``
  (``EXTERNALLY_CONTROLLED``/``PRESCRIBED_INPUT``/``DYNAMIC_COUPLING``/``UNRESOLVED``), and
  ``module_boundary_resolution_status`` (``PENDING_REVIEW``/``RESOLVED``).
* ``model_module.execution_status`` -- a new, non-nullable column
  (``model_module_execution_status`` enum: ``VIEW_ONLY``/``REQUIRES_BOUNDARY_REVIEW``/
  ``SIMULATION_READY``), defaulting to ``VIEW_ONLY`` (every pre-existing row is unaffected).
* ``module_boundary_port`` -- one row per ``(model_module, species_id, direction)``,
  ``CASCADE``-deleted from ``model_module`` (no independent meaning apart from the module it
  describes, unlike ``model_module`` itself).

See ``docs/08_boundary_condition_semantics.md``.

Revision ID: 0007_module_boundary_port
Revises: 0006_model_module
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import (
    ModelModuleExecutionStatus,
    ModuleBoundaryResolutionStatus,
    ModuleBoundaryTreatmentType,
    ModulePortDirection,
)

revision: str = "0007_module_boundary_port"
down_revision: str | None = "0006_model_module"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_module_port_direction_enum = postgresql.ENUM(
    *[m.value for m in ModulePortDirection], name="module_port_direction"
)
_module_boundary_treatment_type_enum = postgresql.ENUM(
    *[m.value for m in ModuleBoundaryTreatmentType], name="module_boundary_treatment_type"
)
_module_boundary_resolution_status_enum = postgresql.ENUM(
    *[m.value for m in ModuleBoundaryResolutionStatus], name="module_boundary_resolution_status"
)
_model_module_execution_status_enum = postgresql.ENUM(
    *[m.value for m in ModelModuleExecutionStatus], name="model_module_execution_status"
)


def upgrade() -> None:
    bind = op.get_bind()
    _module_port_direction_enum.create(bind, checkfirst=True)
    _module_boundary_treatment_type_enum.create(bind, checkfirst=True)
    _module_boundary_resolution_status_enum.create(bind, checkfirst=True)
    _model_module_execution_status_enum.create(bind, checkfirst=True)

    op.add_column(
        "model_module",
        sa.Column(
            "execution_status",
            postgresql.ENUM(
                *[m.value for m in ModelModuleExecutionStatus],
                name="model_module_execution_status",
                create_type=False,
            ),
            nullable=False,
            server_default=ModelModuleExecutionStatus.VIEW_ONLY.value,
        ),
    )

    op.create_table(
        "module_boundary_port",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("port_id", sa.Text(), nullable=False),
        sa.Column("species_id", sa.Text(), nullable=False),
        sa.Column(
            "direction",
            postgresql.ENUM(
                *[m.value for m in ModulePortDirection],
                name="module_port_direction",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "treatment_type",
            postgresql.ENUM(
                *[m.value for m in ModuleBoundaryTreatmentType],
                name="module_boundary_treatment_type",
                create_type=False,
            ),
            nullable=False,
            server_default=ModuleBoundaryTreatmentType.UNRESOLVED.value,
        ),
        sa.Column(
            "resolution_status",
            postgresql.ENUM(
                *[m.value for m in ModuleBoundaryResolutionStatus],
                name="module_boundary_resolution_status",
                create_type=False,
            ),
            nullable=False,
            server_default=ModuleBoundaryResolutionStatus.PENDING_REVIEW.value,
        ),
        sa.Column("initial_value", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("value_source", sa.String(), nullable=True),
        sa.Column("provenance_notes", sa.Text(), nullable=True),
        sa.Column("derived_automatically", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_module_boundary_port"),
        sa.ForeignKeyConstraint(
            ["model_module_id"],
            ["model_module.id"],
            name="fk_module_boundary_port_model_module_id_mm",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "model_module_id",
            "species_id",
            "direction",
            name="uq_module_boundary_port_module_species_direction",
        ),
    )
    op.create_index(
        "ix_module_boundary_port_model_module_id", "module_boundary_port", ["model_module_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_module_boundary_port_model_module_id", table_name="module_boundary_port")
    op.drop_table("module_boundary_port")

    op.drop_column("model_module", "execution_status")

    bind = op.get_bind()
    _model_module_execution_status_enum.drop(bind, checkfirst=True)
    _module_boundary_resolution_status_enum.drop(bind, checkfirst=True)
    _module_boundary_treatment_type_enum.drop(bind, checkfirst=True)
    _module_port_direction_enum.drop(bind, checkfirst=True)
