"""Joint Calibration Workflow, configuration-only increment.

See ``docs/29_joint_calibration_workflow_design.md``, ``docs/30
_joint_calibration_configuration_increment.md``, and ``docs/31
_joint_calibration_configuration_prerequisites_increment.md`` (the configuration-prerequisites
revision folded directly into this not-yet-committed migration, rather than a separate
rename/alter migration on top of it -- see that document's own note on why). Adds:

* Nine new enums: ``model_relationship_kind``, ``calibration_job_status``,
  ``calibration_experiment_role``, ``calibration_objective_weighting``,
  ``calibration_binding_model_meaning``, ``calibration_binding_value_source``,
  ``calibration_parameter_role_kind``.
  (``calibration_finding_severity``/``calibration_finding_category`` back computed-on-demand
  review findings only -- never persisted, so no enum type is created for either.)
* ``model_relationship`` -- insert-only, an explicit declared fact between two ``Model`` rows.
* ``calibration_job`` and its own mutable-while-``DRAFT`` children: ``calibration_arm``,
  ``calibration_experiment``, ``calibration_experiment_variable_binding``,
  ``calibration_parameter_role``, ``calibration_parameter_role_arm``.
* ``calibration_job_revision`` -- insert-only, an immutable, versioned snapshot of a job's own
  complete configuration, captured each time "Complete review" succeeds.

No existing column is altered or dropped, and no existing row's data changes.

Revision ID: 0019_calibration_configuration
Revises: 0018_dataset_model_alias_mapping
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import (
    CalibrationBindingModelMeaning,
    CalibrationBindingValueSource,
    CalibrationExperimentRole,
    CalibrationJobStatus,
    CalibrationObjectiveWeighting,
    CalibrationParameterRoleKind,
    ModelRelationshipKind,
)

revision: str = "0019_calibration_configuration"
down_revision: str | None = "0018_dataset_model_alias_mapping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_model_relationship_kind_enum = postgresql.ENUM(
    *[m.value for m in ModelRelationshipKind], name="model_relationship_kind"
)
_calibration_job_status_enum = postgresql.ENUM(
    *[m.value for m in CalibrationJobStatus], name="calibration_job_status"
)
_calibration_experiment_role_enum = postgresql.ENUM(
    *[m.value for m in CalibrationExperimentRole], name="calibration_experiment_role"
)
_calibration_objective_weighting_enum = postgresql.ENUM(
    *[m.value for m in CalibrationObjectiveWeighting], name="calibration_objective_weighting"
)
_calibration_binding_model_meaning_enum = postgresql.ENUM(
    *[m.value for m in CalibrationBindingModelMeaning],
    name="calibration_binding_model_meaning",
)
_calibration_binding_value_source_enum = postgresql.ENUM(
    *[m.value for m in CalibrationBindingValueSource],
    name="calibration_binding_value_source",
)
_calibration_parameter_role_kind_enum = postgresql.ENUM(
    *[m.value for m in CalibrationParameterRoleKind], name="calibration_parameter_role_kind"
)


def upgrade() -> None:
    bind = op.get_bind()
    _model_relationship_kind_enum.create(bind, checkfirst=True)
    _calibration_job_status_enum.create(bind, checkfirst=True)
    _calibration_experiment_role_enum.create(bind, checkfirst=True)
    _calibration_objective_weighting_enum.create(bind, checkfirst=True)
    _calibration_binding_model_meaning_enum.create(bind, checkfirst=True)
    _calibration_binding_value_source_enum.create(bind, checkfirst=True)
    _calibration_parameter_role_kind_enum.create(bind, checkfirst=True)

    op.create_table(
        "model_relationship",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id_a", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id_b", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "relationship_kind",
            postgresql.ENUM(
                *[m.value for m in ModelRelationshipKind],
                name="model_relationship_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("role_label_a", sa.String(), nullable=True),
        sa.Column("role_label_b", sa.String(), nullable=True),
        sa.Column("declared_by", sa.String(), nullable=True),
        sa.Column(
            "declared_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_relationship"),
        sa.ForeignKeyConstraint(
            ["model_id_a"],
            ["model.id"],
            name="fk_model_relationship_model_id_a_model",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_id_b"],
            ["model.id"],
            name="fk_model_relationship_model_id_b_model",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_model_relationship_model_id_a", "model_relationship", ["model_id_a"])
    op.create_index("ix_model_relationship_model_id_b", "model_relationship", ["model_id_b"])

    op.create_table(
        "calibration_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subproject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                *[m.value for m in CalibrationJobStatus],
                name="calibration_job_status",
                create_type=False,
            ),
            nullable=False,
            server_default=CalibrationJobStatus.DRAFT.value,
        ),
        sa.Column("edit_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_calibration_job"),
        sa.ForeignKeyConstraint(
            ["subproject_id"],
            ["subproject.id"],
            name="fk_calibration_job_subproject_id_subproject",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_calibration_job_subproject_id", "calibration_job", ["subproject_id"])

    op.create_table(
        "calibration_job_revision",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calibration_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("snapshot_payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_calibration_job_revision"),
        sa.ForeignKeyConstraint(
            ["calibration_job_id"],
            ["calibration_job.id"],
            name="fk_calibration_job_revision_calibration_job_id_cj",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "calibration_job_id",
            "revision_number",
            name="uq_calibration_job_revision_job_id_number",
        ),
    )
    op.create_index(
        "ix_calibration_job_revision_calibration_job_id",
        "calibration_job_revision",
        ["calibration_job_id"],
    )

    op.create_table(
        "calibration_arm",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calibration_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_label", sa.String(), nullable=True),
        sa.Column("sequence_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_calibration_arm"),
        sa.ForeignKeyConstraint(
            ["calibration_job_id"],
            ["calibration_job.id"],
            name="fk_calibration_arm_calibration_job_id_cj",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["model.id"],
            name="fk_calibration_arm_model_id_model",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_calibration_arm_calibration_job_id", "calibration_arm", ["calibration_job_id"]
    )
    op.create_index("ix_calibration_arm_model_id", "calibration_arm", ["model_id"])

    op.create_table(
        "calibration_experiment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calibration_arm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("time_series_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias_mapping_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "role",
            postgresql.ENUM(
                *[m.value for m in CalibrationExperimentRole],
                name="calibration_experiment_role",
                create_type=False,
            ),
            nullable=False,
            server_default=CalibrationExperimentRole.CALIBRATION.value,
        ),
        sa.Column(
            "objective_weighting",
            postgresql.ENUM(
                *[m.value for m in CalibrationObjectiveWeighting],
                name="calibration_objective_weighting",
                create_type=False,
            ),
            nullable=False,
            server_default=CalibrationObjectiveWeighting.UNWEIGHTED.value,
        ),
        sa.Column("weighting_notes", sa.Text(), nullable=True),
        sa.Column("sequence_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_calibration_experiment"),
        sa.ForeignKeyConstraint(
            ["calibration_arm_id"],
            ["calibration_arm.id"],
            name="fk_calibration_experiment_calibration_arm_id_ca",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["time_series_dataset_id"],
            ["time_series_dataset.id"],
            name="fk_calibration_experiment_time_series_dataset_id_tsd",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["alias_mapping_revision_id"],
            ["dataset_model_alias_mapping_revision.id"],
            name="fk_calibration_experiment_alias_mapping_revision_id_amr",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_calibration_experiment_calibration_arm_id",
        "calibration_experiment",
        ["calibration_arm_id"],
    )
    op.create_index(
        "ix_calibration_experiment_time_series_dataset_id",
        "calibration_experiment",
        ["time_series_dataset_id"],
    )
    op.create_index(
        "ix_calibration_experiment_alias_mapping_revision_id",
        "calibration_experiment",
        ["alias_mapping_revision_id"],
    )

    op.create_table(
        "calibration_experiment_variable_binding",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calibration_experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "model_meaning",
            postgresql.ENUM(
                *[m.value for m in CalibrationBindingModelMeaning],
                name="calibration_binding_model_meaning",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("target_component_id", sa.Text(), nullable=False),
        sa.Column(
            "value_source",
            postgresql.ENUM(
                *[m.value for m in CalibrationBindingValueSource],
                name="calibration_binding_value_source",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("constant_value", sa.Numeric(), nullable=True),
        sa.Column("constant_unit", sa.String(), nullable=True),
        sa.Column("source_column_name", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_calibration_experiment_variable_binding"),
        sa.ForeignKeyConstraint(
            ["calibration_experiment_id"],
            ["calibration_experiment.id"],
            name="fk_calibration_experiment_variable_binding_experiment_id_ce",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_calibration_experiment_variable_binding_experiment_id",
        "calibration_experiment_variable_binding",
        ["calibration_experiment_id"],
    )

    op.create_table(
        "calibration_parameter_role",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calibration_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parameter_name", sa.Text(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                *[m.value for m in CalibrationParameterRoleKind],
                name="calibration_parameter_role_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "catalog_validated", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("fixed_value", sa.Numeric(), nullable=True),
        sa.Column("lower_bound", sa.Numeric(), nullable=True),
        sa.Column("upper_bound", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("reference_arm_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reference_parameter_name", sa.Text(), nullable=True),
        sa.Column("coefficient_a", sa.Numeric(), nullable=True),
        sa.Column("coefficient_a_is_fixed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("coefficient_b", sa.Numeric(), nullable=True),
        sa.Column("coefficient_b_is_fixed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_calibration_parameter_role"),
        sa.ForeignKeyConstraint(
            ["calibration_job_id"],
            ["calibration_job.id"],
            name="fk_calibration_parameter_role_calibration_job_id_cj",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reference_arm_id"],
            ["calibration_arm.id"],
            name="fk_calibration_parameter_role_reference_arm_id_ca",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_calibration_parameter_role_calibration_job_id",
        "calibration_parameter_role",
        ["calibration_job_id"],
    )
    op.create_index(
        "ix_calibration_parameter_role_reference_arm_id",
        "calibration_parameter_role",
        ["reference_arm_id"],
    )

    op.create_table(
        "calibration_parameter_role_arm",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calibration_parameter_role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calibration_arm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_calibration_parameter_role_arm"),
        sa.ForeignKeyConstraint(
            ["calibration_parameter_role_id"],
            ["calibration_parameter_role.id"],
            name="fk_calibration_parameter_role_arm_role_id_cpr",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["calibration_arm_id"],
            ["calibration_arm.id"],
            name="fk_calibration_parameter_role_arm_arm_id_ca",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "calibration_parameter_role_id",
            "calibration_arm_id",
            name="uq_calibration_parameter_role_arm_role_arm",
        ),
    )
    op.create_index(
        "ix_calibration_parameter_role_arm_role_id",
        "calibration_parameter_role_arm",
        ["calibration_parameter_role_id"],
    )
    op.create_index(
        "ix_calibration_parameter_role_arm_arm_id",
        "calibration_parameter_role_arm",
        ["calibration_arm_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_calibration_parameter_role_arm_arm_id", table_name="calibration_parameter_role_arm"
    )
    op.drop_index(
        "ix_calibration_parameter_role_arm_role_id", table_name="calibration_parameter_role_arm"
    )
    op.drop_table("calibration_parameter_role_arm")

    op.drop_index(
        "ix_calibration_parameter_role_reference_arm_id", table_name="calibration_parameter_role"
    )
    op.drop_index(
        "ix_calibration_parameter_role_calibration_job_id", table_name="calibration_parameter_role"
    )
    op.drop_table("calibration_parameter_role")

    op.drop_index(
        "ix_calibration_experiment_variable_binding_experiment_id",
        table_name="calibration_experiment_variable_binding",
    )
    op.drop_table("calibration_experiment_variable_binding")

    op.drop_index(
        "ix_calibration_experiment_alias_mapping_revision_id", table_name="calibration_experiment"
    )
    op.drop_index(
        "ix_calibration_experiment_time_series_dataset_id", table_name="calibration_experiment"
    )
    op.drop_index(
        "ix_calibration_experiment_calibration_arm_id", table_name="calibration_experiment"
    )
    op.drop_table("calibration_experiment")

    op.drop_index("ix_calibration_arm_model_id", table_name="calibration_arm")
    op.drop_index("ix_calibration_arm_calibration_job_id", table_name="calibration_arm")
    op.drop_table("calibration_arm")

    op.drop_index(
        "ix_calibration_job_revision_calibration_job_id", table_name="calibration_job_revision"
    )
    op.drop_table("calibration_job_revision")

    op.drop_index("ix_calibration_job_subproject_id", table_name="calibration_job")
    op.drop_table("calibration_job")

    op.drop_index("ix_model_relationship_model_id_b", table_name="model_relationship")
    op.drop_index("ix_model_relationship_model_id_a", table_name="model_relationship")
    op.drop_table("model_relationship")

    bind = op.get_bind()
    _calibration_parameter_role_kind_enum.drop(bind, checkfirst=True)
    _calibration_binding_value_source_enum.drop(bind, checkfirst=True)
    _calibration_binding_model_meaning_enum.drop(bind, checkfirst=True)
    _calibration_objective_weighting_enum.drop(bind, checkfirst=True)
    _calibration_experiment_role_enum.drop(bind, checkfirst=True)
    _calibration_job_status_enum.drop(bind, checkfirst=True)
    _model_relationship_kind_enum.drop(bind, checkfirst=True)
