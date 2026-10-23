"""Whole-Model Experimental-Scenario Evaluation increment: the reliable prediction primitive
Agent 4 will later call inside joint optimization. Prediction only -- never fitting.

See ``docs/33_whole_model_experimental_scenario_evaluation_increment.md``. Purely additive, on
top of the already-applied ``0019``-``0021`` calibration-configuration migrations (same
deliberate "new migration, never an in-place edit of an already-applied one" discipline
``0021`` itself documents). Adds:

* ``calibration_experiment_variable_binding.intervention_time`` (nullable ``NUMERIC``) plus a
  ``CHECK`` constraint requiring it set if and only if ``model_meaning='INTERVENTION'`` -- see
  ``app.models.calibration.CalibrationExperimentVariableBinding``'s own docstring for why this
  is required (without it, ``INTERVENTION`` would be behaviorally indistinguishable from
  ``INITIAL_VALUE``/``PARAMETER_OVERRIDE``, both of which always take effect at ``t=0``).
* ``run_record.calibration_experiment_id`` (nullable FK, ``RESTRICT``) -- distinguishes a
  scenario-evaluation run from every other kind of run, mirroring ``module_set_member_id``'s
  own identical precedent (``0015``).
* ``calibration_scenario_evaluation_snapshot`` -- one immutable, versioned record of exactly
  what was used to evaluate one scenario (``run_record_id`` unique, 1:1), mirroring
  ``module_execution_snapshot`` (``0008``). Unlike ``run_record.module_set_member_id``'s own
  single-table partial unique index (``0015``), duplicate-active-run detection here cannot be
  a database constraint: the columns that identify "the same scenario" (``condition_id``,
  ``input_hash``) live on this table, while run status lives on ``run_record``, and Postgres
  partial-index predicates cannot reference another table. Enforced instead at the persistence
  layer (``app.persistence.calibration_scenario_evaluation.submit_scenario_evaluation``) --
  a disclosed, best-effort check, not a database-level guarantee (see that module's own
  docstring).

**No existing column is altered or dropped, and no existing row's data changes.** Every
pre-existing ``run_record``/``calibration_experiment_variable_binding`` row keeps reading back
byte-identical to before (``calibration_experiment_id=NULL``/``intervention_time=NULL``
respectively -- both already-correct for a pre-existing, non-``INTERVENTION`` row).

Revision ID: 0022_calibration_scenario_eval
Revises: 0021_calibration_uncertainty
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_calibration_scenario_eval"
down_revision: str | None = "0021_calibration_uncertainty"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "calibration_experiment_variable_binding",
        sa.Column("intervention_time", sa.Numeric(), nullable=True),
    )
    op.create_check_constraint(
        "ck_calibration_experiment_variable_binding_intervention_time",
        "calibration_experiment_variable_binding",
        "(model_meaning = 'INTERVENTION' AND intervention_time IS NOT NULL) OR "
        "(model_meaning != 'INTERVENTION' AND intervention_time IS NULL)",
    )

    op.add_column(
        "run_record",
        sa.Column("calibration_experiment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_run_record_calibration_experiment_id_ce",
        "run_record",
        "calibration_experiment",
        ["calibration_experiment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_run_record_calibration_experiment_id", "run_record", ["calibration_experiment_id"]
    )

    op.create_table(
        "calibration_scenario_evaluation_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calibration_experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calibration_job_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("condition_id", sa.Text(), nullable=True),
        sa.Column("input_hash", sa.String(), nullable=False),
        sa.Column("snapshot_payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_calibration_scenario_evaluation_snapshot"),
        sa.ForeignKeyConstraint(
            ["calibration_experiment_id"],
            ["calibration_experiment.id"],
            name="fk_calibration_scenario_evaluation_snapshot_experiment_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["calibration_job_revision_id"],
            ["calibration_job_revision.id"],
            name="fk_calibration_scenario_evaluation_snapshot_revision_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_record_id"],
            ["run_record.id"],
            name="fk_calibration_scenario_evaluation_snapshot_run_record_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "run_record_id", name="uq_calibration_scenario_evaluation_snapshot_run_record_id"
        ),
    )
    op.create_index(
        "ix_calibration_scenario_evaluation_snapshot_experiment_id",
        "calibration_scenario_evaluation_snapshot",
        ["calibration_experiment_id"],
    )
    op.create_index(
        "ix_calibration_scenario_evaluation_snapshot_revision_id",
        "calibration_scenario_evaluation_snapshot",
        ["calibration_job_revision_id"],
    )
    # A plain (non-partial, non-unique) index for the persistence layer's own application-side
    # duplicate-active-run lookup (module docstring: this cannot be a database constraint).
    op.create_index(
        "ix_calibration_scenario_evaluation_snapshot_dedup_lookup",
        "calibration_scenario_evaluation_snapshot",
        ["calibration_experiment_id", "condition_id", "input_hash"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_calibration_scenario_evaluation_snapshot_dedup_lookup",
        table_name="calibration_scenario_evaluation_snapshot",
    )
    op.drop_index(
        "ix_calibration_scenario_evaluation_snapshot_revision_id",
        table_name="calibration_scenario_evaluation_snapshot",
    )
    op.drop_index(
        "ix_calibration_scenario_evaluation_snapshot_experiment_id",
        table_name="calibration_scenario_evaluation_snapshot",
    )
    op.drop_table("calibration_scenario_evaluation_snapshot")

    op.drop_index("ix_run_record_calibration_experiment_id", table_name="run_record")
    op.drop_constraint(
        "fk_run_record_calibration_experiment_id_ce", "run_record", type_="foreignkey"
    )
    op.drop_column("run_record", "calibration_experiment_id")

    op.drop_constraint(
        "ck_calibration_experiment_variable_binding_intervention_time",
        "calibration_experiment_variable_binding",
        type_="check",
    )
    op.drop_column("calibration_experiment_variable_binding", "intervention_time")
