"""Initial Workbench schema baseline.

Creates fourteen tables (``project``, ``subproject``, ``dataset_reference``,
``model``, ``model_build_request`` and its eight child tables
``model_build_request_species``, ``model_build_request_reaction``,
``model_build_request_gene_protein``, ``model_build_request_compartment``,
``model_build_request_regulatory_interaction``,
``model_build_request_enzyme_state``, ``model_build_request_pathway``,
``model_build_request_assumption``, and
``modeling_decision``/``modeling_decision_option``, and ``run_record``) and
fourteen native enum types.

See ``docs/02_database_schema.md`` and ``docs/01_workbench_architecture.md``
for the full design rationale.

``modeling_decision.selected_option_id`` is a genuine forward reference to
``modeling_decision_option``, a table that does not exist yet when
``modeling_decision`` is created. It is created here as a plain nullable
column with no inline foreign key, and the foreign key constraint is added
via a separate ``op.create_foreign_key`` call once
``modeling_decision_option`` exists (see ``upgrade()``'s own comment at
that call) -- the identical pattern used for the same problem in Agent 1's
own migration ``0020_project_subproject_model``.

Revision ID: 0001_initial_workbench_schema
Revises:
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.naming import conv

from app.models.enums import (
    ConfidenceClass,
    ModelBuildRequestGeneProteinRole,
    ModelBuildRequestPathwayRole,
    ModelBuildRequestReactionRole,
    ModelBuildRequestSpeciesRole,
    ModelingDecisionResolutionSource,
    ModelingDecisionStatus,
    ModelSourceType,
    ModelStatus,
    ProjectType,
    RunStage,
    RunStatus,
    SubprojectTaskType,
    WorkflowLifecycleStatus,
)

revision: str = "0001_initial_workbench_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_project_type_enum = postgresql.ENUM(*[m.value for m in ProjectType], name="project_type")
_workflow_lifecycle_status_enum = postgresql.ENUM(
    *[m.value for m in WorkflowLifecycleStatus], name="workflow_lifecycle_status"
)
_subproject_task_type_enum = postgresql.ENUM(
    *[m.value for m in SubprojectTaskType], name="subproject_task_type"
)
_model_source_type_enum = postgresql.ENUM(*[m.value for m in ModelSourceType], name="model_source_type")
_model_status_enum = postgresql.ENUM(*[m.value for m in ModelStatus], name="model_status")
_mbr_species_role_enum = postgresql.ENUM(
    *[m.value for m in ModelBuildRequestSpeciesRole], name="model_build_request_species_role"
)
_mbr_reaction_role_enum = postgresql.ENUM(
    *[m.value for m in ModelBuildRequestReactionRole], name="model_build_request_reaction_role"
)
_mbr_gene_protein_role_enum = postgresql.ENUM(
    *[m.value for m in ModelBuildRequestGeneProteinRole],
    name="model_build_request_gene_protein_role",
)
_mbr_pathway_role_enum = postgresql.ENUM(
    *[m.value for m in ModelBuildRequestPathwayRole], name="model_build_request_pathway_role"
)
_modeling_decision_status_enum = postgresql.ENUM(
    *[m.value for m in ModelingDecisionStatus], name="modeling_decision_status"
)
_modeling_decision_resolution_source_enum = postgresql.ENUM(
    *[m.value for m in ModelingDecisionResolutionSource],
    name="modeling_decision_resolution_source",
)
_confidence_class_enum = postgresql.ENUM(*[m.value for m in ConfidenceClass], name="confidence_class")
_run_stage_enum = postgresql.ENUM(*[m.value for m in RunStage], name="run_stage")
_run_status_enum = postgresql.ENUM(*[m.value for m in RunStatus], name="run_status")


def upgrade() -> None:
    bind = op.get_bind()
    _project_type_enum.create(bind, checkfirst=True)
    _workflow_lifecycle_status_enum.create(bind, checkfirst=True)
    _subproject_task_type_enum.create(bind, checkfirst=True)
    _model_source_type_enum.create(bind, checkfirst=True)
    _model_status_enum.create(bind, checkfirst=True)
    _mbr_species_role_enum.create(bind, checkfirst=True)
    _mbr_reaction_role_enum.create(bind, checkfirst=True)
    _mbr_gene_protein_role_enum.create(bind, checkfirst=True)
    _mbr_pathway_role_enum.create(bind, checkfirst=True)
    _modeling_decision_status_enum.create(bind, checkfirst=True)
    _modeling_decision_resolution_source_enum.create(bind, checkfirst=True)
    _confidence_class_enum.create(bind, checkfirst=True)
    _run_stage_enum.create(bind, checkfirst=True)
    _run_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "project",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stable_identifier", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "project_type",
            postgresql.ENUM(*[m.value for m in ProjectType], name="project_type", create_type=False),
            nullable=False,
        ),
        sa.Column("agent1_organism_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("biological_context_summary", sa.Text(), nullable=True),
        sa.Column("strain_genotype_notes", sa.Text(), nullable=True),
        sa.Column("biological_process", sa.Text(), nullable=True),
        sa.Column("disease", sa.String(), nullable=True),
        sa.Column("tissue", sa.String(), nullable=True),
        sa.Column("cell_type", sa.String(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                *[m.value for m in WorkflowLifecycleStatus],
                name="workflow_lifecycle_status",
                create_type=False,
            ),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_project"),
        sa.UniqueConstraint("stable_identifier", name="uq_project_stable_identifier"),
    )
    op.create_index("ix_project_agent1_organism_id", "project", ["agent1_organism_id"])

    op.create_table(
        "subproject",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column(
            "task_type",
            postgresql.ENUM(
                *[m.value for m in SubprojectTaskType], name="subproject_task_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                *[m.value for m in WorkflowLifecycleStatus],
                name="workflow_lifecycle_status",
                create_type=False,
            ),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subproject"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name="fk_subproject_project_id_project", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("project_id", "title", name="uq_subproject_project_id_title"),
    )
    op.create_index("ix_subproject_project_id", "subproject", ["project_id"])

    op.create_table(
        "dataset_reference",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subproject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dataset_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("agent1_entity_type", sa.String(), nullable=True),
        sa.Column("agent1_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("biological_context_notes", sa.Text(), nullable=True),
        sa.Column("artifact_reference", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=True),
        sa.Column("version_label", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dataset_reference"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name="fk_dataset_reference_project_id_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subproject_id"],
            ["subproject.id"],
            name="fk_dataset_reference_subproject_id_subproject",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_dataset_reference_project_id", "dataset_reference", ["project_id"])
    op.create_index("ix_dataset_reference_subproject_id", "dataset_reference", ["subproject_id"])

    op.create_table(
        "model",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subproject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stable_identifier", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "source_type",
            postgresql.ENUM(
                *[m.value for m in ModelSourceType], name="model_source_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(*[m.value for m in ModelStatus], name="model_status", create_type=False),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("artifact_reference", sa.Text(), nullable=True),
        sa.Column("parent_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_label", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model"),
        sa.ForeignKeyConstraint(
            ["subproject_id"],
            ["subproject.id"],
            name="fk_model_subproject_id_subproject",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_model_id"], ["model.id"], name="fk_model_parent_model_id_model", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("stable_identifier", name="uq_model_stable_identifier"),
    )
    op.create_index("ix_model_subproject_id", "model", ["subproject_id"])
    op.create_index("ix_model_parent_model_id", "model", ["parent_model_id"])

    op.create_table(
        "model_build_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subproject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_build_request"),
        sa.ForeignKeyConstraint(
            ["subproject_id"],
            ["subproject.id"],
            name="fk_model_build_request_subproject_id_subproject",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_model_build_request_subproject_id", "model_build_request", ["subproject_id"], unique=True
    )

    op.create_table(
        "model_build_request_species",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_build_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                *[m.value for m in ModelBuildRequestSpeciesRole],
                name="model_build_request_species_role",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("agent1_entity_type", sa.String(), nullable=True),
        sa.Column("agent1_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_identifier", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_build_request_species"),
        sa.ForeignKeyConstraint(
            ["model_build_request_id"],
            ["model_build_request.id"],
            name="fk_mbr_species_model_build_request_id_mbr",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_model_build_request_species_model_build_request_id",
        "model_build_request_species",
        ["model_build_request_id"],
    )

    op.create_table(
        "model_build_request_reaction",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_build_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                *[m.value for m in ModelBuildRequestReactionRole],
                name="model_build_request_reaction_role",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("agent1_entity_type", sa.String(), nullable=True),
        sa.Column("agent1_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_identifier", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_build_request_reaction"),
        sa.ForeignKeyConstraint(
            ["model_build_request_id"],
            ["model_build_request.id"],
            name="fk_mbr_reaction_model_build_request_id_mbr",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_model_build_request_reaction_model_build_request_id",
        "model_build_request_reaction",
        ["model_build_request_id"],
    )

    op.create_table(
        "model_build_request_gene_protein",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_build_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                *[m.value for m in ModelBuildRequestGeneProteinRole],
                name="model_build_request_gene_protein_role",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("agent1_entity_type", sa.String(), nullable=True),
        sa.Column("agent1_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_identifier", sa.String(), nullable=True),
        sa.Column("localization_entity_type", sa.String(), nullable=True),
        sa.Column("localization_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("localization_raw_identifier", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_build_request_gene_protein"),
        sa.ForeignKeyConstraint(
            ["model_build_request_id"],
            ["model_build_request.id"],
            name="fk_mbr_gene_protein_model_build_request_id_mbr",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_model_build_request_gene_protein_model_build_request_id",
        "model_build_request_gene_protein",
        ["model_build_request_id"],
    )

    op.create_table(
        "model_build_request_compartment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_build_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent1_entity_type", sa.String(), nullable=True),
        sa.Column("agent1_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_identifier", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_build_request_compartment"),
        sa.ForeignKeyConstraint(
            ["model_build_request_id"],
            ["model_build_request.id"],
            name="fk_mbr_compartment_model_build_request_id_mbr",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_model_build_request_compartment_model_build_request_id",
        "model_build_request_compartment",
        ["model_build_request_id"],
    )

    op.create_table(
        "model_build_request_regulatory_interaction",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_build_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent1_entity_type", sa.String(), nullable=True),
        sa.Column("agent1_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_identifier", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_build_request_regulatory_interaction"),
        sa.ForeignKeyConstraint(
            ["model_build_request_id"],
            ["model_build_request.id"],
            name="fk_mbr_reg_interaction_model_build_request_id_mbr",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_mbr_reg_interaction_model_build_request_id",
        "model_build_request_regulatory_interaction",
        ["model_build_request_id"],
    )

    op.create_table(
        "model_build_request_enzyme_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_build_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent1_entity_type", sa.String(), nullable=True),
        sa.Column("agent1_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_identifier", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_build_request_enzyme_state"),
        sa.ForeignKeyConstraint(
            ["model_build_request_id"],
            ["model_build_request.id"],
            name="fk_mbr_enzyme_state_model_build_request_id_mbr",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_model_build_request_enzyme_state_model_build_request_id",
        "model_build_request_enzyme_state",
        ["model_build_request_id"],
    )

    op.create_table(
        "model_build_request_pathway",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_build_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                *[m.value for m in ModelBuildRequestPathwayRole],
                name="model_build_request_pathway_role",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("external_pathway_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_build_request_pathway"),
        sa.ForeignKeyConstraint(
            ["model_build_request_id"],
            ["model_build_request.id"],
            name="fk_mbr_pathway_model_build_request_id_mbr",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_model_build_request_pathway_model_build_request_id",
        "model_build_request_pathway",
        ["model_build_request_id"],
    )

    op.create_table(
        "model_build_request_assumption",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_build_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assumption", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_build_request_assumption"),
        sa.ForeignKeyConstraint(
            ["model_build_request_id"],
            ["model_build_request.id"],
            name="fk_mbr_assumption_model_build_request_id_mbr",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_model_build_request_assumption_model_build_request_id",
        "model_build_request_assumption",
        ["model_build_request_id"],
    )

    # modeling_decision.selected_option_id is created here as a plain nullable
    # column with no foreign key -- modeling_decision_option does not exist
    # yet. The constraint is added below, after that table is created (see
    # module docstring).
    op.create_table(
        "modeling_decision",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subproject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("decision_type", sa.String(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                *[m.value for m in ModelingDecisionStatus],
                name="modeling_decision_status",
                create_type=False,
            ),
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column("selected_option_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "resolution_source",
            postgresql.ENUM(
                *[m.value for m in ModelingDecisionResolutionSource],
                name="modeling_decision_resolution_source",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_modeling_decision"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name="fk_modeling_decision_project_id_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subproject_id"],
            ["subproject.id"],
            name="fk_modeling_decision_subproject_id_subproject",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["model.id"], name="fk_modeling_decision_model_id_model", ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_modeling_decision_project_id", "modeling_decision", ["project_id"])
    op.create_index("ix_modeling_decision_subproject_id", "modeling_decision", ["subproject_id"])
    op.create_index("ix_modeling_decision_model_id", "modeling_decision", ["model_id"])
    op.create_index(
        "ix_modeling_decision_selected_option_id", "modeling_decision", ["selected_option_id"]
    )

    op.create_table(
        "modeling_decision_option",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Numeric(), nullable=True),
        sa.Column(
            "confidence_class",
            postgresql.ENUM(name="confidence_class", create_type=False),
            nullable=True,
        ),
        sa.Column("impact_summary", sa.Text(), nullable=True),
        sa.Column("recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_modeling_decision_option"),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["modeling_decision.id"],
            name="fk_modeling_decision_option_decision_id_modeling_decision",
            ondelete="CASCADE",
        ),
        # conv() marks the name as already final -- see Agent 1's
        # 0006_kinetic_measurement.py for the identical note on why this is
        # required to avoid the "ck" naming convention mangling an
        # already-explicit name.
        sa.CheckConstraint(
            "confidence_score IS NULL OR confidence_score BETWEEN 0 AND 100",
            name=conv("ck_modeling_decision_option_confidence_score_range"),
        ),
    )
    op.create_index(
        "ix_modeling_decision_option_decision_id", "modeling_decision_option", ["decision_id"]
    )

    # The deferred forward-reference FK -- see module docstring.
    op.create_foreign_key(
        "fk_modeling_decision_selected_option_id_mdec_opt",
        "modeling_decision",
        "modeling_decision_option",
        ["selected_option_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "run_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subproject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "stage",
            postgresql.ENUM(*[m.value for m in RunStage], name="run_stage", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(*[m.value for m in RunStatus], name="run_status", create_type=False),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("contract_version", sa.String(), nullable=True),
        sa.Column("artifact_reference", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_run_record"),
        sa.ForeignKeyConstraint(
            ["subproject_id"],
            ["subproject.id"],
            name="fk_run_record_subproject_id_subproject",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["model.id"], name="fk_run_record_model_id_model", ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_run_record_subproject_id", "run_record", ["subproject_id"])
    op.create_index("ix_run_record_model_id", "run_record", ["model_id"])


def downgrade() -> None:
    op.drop_index("ix_run_record_model_id", table_name="run_record")
    op.drop_index("ix_run_record_subproject_id", table_name="run_record")
    op.drop_table("run_record")

    op.drop_constraint(
        "fk_modeling_decision_selected_option_id_mdec_opt",
        "modeling_decision",
        type_="foreignkey",
    )

    op.drop_index("ix_modeling_decision_option_decision_id", table_name="modeling_decision_option")
    op.drop_table("modeling_decision_option")

    op.drop_index("ix_modeling_decision_selected_option_id", table_name="modeling_decision")
    op.drop_index("ix_modeling_decision_model_id", table_name="modeling_decision")
    op.drop_index("ix_modeling_decision_subproject_id", table_name="modeling_decision")
    op.drop_index("ix_modeling_decision_project_id", table_name="modeling_decision")
    op.drop_table("modeling_decision")

    op.drop_index(
        "ix_model_build_request_assumption_model_build_request_id",
        table_name="model_build_request_assumption",
    )
    op.drop_table("model_build_request_assumption")

    op.drop_index(
        "ix_model_build_request_pathway_model_build_request_id",
        table_name="model_build_request_pathway",
    )
    op.drop_table("model_build_request_pathway")

    op.drop_index(
        "ix_mbr_reg_interaction_model_build_request_id",
        table_name="model_build_request_regulatory_interaction",
    )
    op.drop_table("model_build_request_regulatory_interaction")

    op.drop_index(
        "ix_model_build_request_enzyme_state_model_build_request_id",
        table_name="model_build_request_enzyme_state",
    )
    op.drop_table("model_build_request_enzyme_state")

    op.drop_index(
        "ix_model_build_request_compartment_model_build_request_id",
        table_name="model_build_request_compartment",
    )
    op.drop_table("model_build_request_compartment")

    op.drop_index(
        "ix_model_build_request_gene_protein_model_build_request_id",
        table_name="model_build_request_gene_protein",
    )
    op.drop_table("model_build_request_gene_protein")

    op.drop_index(
        "ix_model_build_request_reaction_model_build_request_id",
        table_name="model_build_request_reaction",
    )
    op.drop_table("model_build_request_reaction")

    op.drop_index(
        "ix_model_build_request_species_model_build_request_id",
        table_name="model_build_request_species",
    )
    op.drop_table("model_build_request_species")

    op.drop_index("ix_model_build_request_subproject_id", table_name="model_build_request")
    op.drop_table("model_build_request")

    op.drop_index("ix_model_parent_model_id", table_name="model")
    op.drop_index("ix_model_subproject_id", table_name="model")
    op.drop_table("model")

    op.drop_index("ix_dataset_reference_subproject_id", table_name="dataset_reference")
    op.drop_index("ix_dataset_reference_project_id", table_name="dataset_reference")
    op.drop_table("dataset_reference")

    op.drop_index("ix_subproject_project_id", table_name="subproject")
    op.drop_table("subproject")

    op.drop_index("ix_project_agent1_organism_id", table_name="project")
    op.drop_table("project")

    bind = op.get_bind()
    _run_status_enum.drop(bind, checkfirst=True)
    _run_stage_enum.drop(bind, checkfirst=True)
    _confidence_class_enum.drop(bind, checkfirst=True)
    _modeling_decision_resolution_source_enum.drop(bind, checkfirst=True)
    _modeling_decision_status_enum.drop(bind, checkfirst=True)
    _mbr_pathway_role_enum.drop(bind, checkfirst=True)
    _mbr_gene_protein_role_enum.drop(bind, checkfirst=True)
    _mbr_reaction_role_enum.drop(bind, checkfirst=True)
    _mbr_species_role_enum.drop(bind, checkfirst=True)
    _model_status_enum.drop(bind, checkfirst=True)
    _model_source_type_enum.drop(bind, checkfirst=True)
    _subproject_task_type_enum.drop(bind, checkfirst=True)
    _workflow_lifecycle_status_enum.drop(bind, checkfirst=True)
    _project_type_enum.drop(bind, checkfirst=True)
