"""Calibration configuration close-out: the minimal error/weighting contract.

See ``docs/32_calibration_configuration_close_out_increment.md``. Purely additive, on top of
the already-applied ``0019_calibration_configuration``/``0020_calibration_prerequisites`` --
deliberately a *new* migration rather than another in-place edit of either of those (see
docs/32 §2's own migration-compatibility finding: editing an already-applied migration's file
in place, discovered the hard way during the ``0019`` rewrite in docs/31, is never repeated
here even though both of those files are themselves still locally uncommitted). Adds:

* One new enum value on the already-existing ``calibration_objective_weighting`` type --
  ``INVERSE_VARIANCE`` (``ALTER TYPE ... ADD VALUE``, the only additive-safe way to extend a
  Postgres enum; the superseded ``DECLARED_SIGMA`` label stays physically in the type, unused,
  since Postgres has no safe ``DROP VALUE`` short of recreating the type entirely -- see
  ``app.models.enums.CalibrationObjectiveWeighting``).
* Two new enums: ``calibration_uncertainty_source``, ``uncertainty_statistic_kind`` (the
  latter required wherever a real uncertainty value is captured, so a standard deviation, a
  variance, and a standard error are never treated interchangeably -- see
  ``app.models.enums.UncertaintyStatisticKind``).
* ``calibration_experiment_output_weighting`` -- one experiment's own declared uncertainty
  source and relative weight for one specific output. ``assumed_sigma_statistic_kind`` records
  which statistic a ``USER_ASSUMED`` value actually is.
* ``time_series_measurement_uncertainty_column`` -- the sibling of the already-existing
  ``time_series_independent_variable_column`` (0020), for Data-tab columns declared as
  already-computed, observation-level uncertainty for one measurement column.
  ``statistic_kind`` is required (``NOT NULL``, no default) -- the parser itself never creates
  a row here for a declaration whose own statistic cell is blank or unrecognized, so every row
  this table ever holds already has one.
* ``time_series_dataset_row.measurement_uncertainty`` -- a new, additive column mirroring the
  already-existing ``independent_variables`` column exactly, defaulted to ``'{}'`` so every row
  saved before this increment reads back byte-identical to before.

No existing column is altered or dropped, and no existing row's data changes.

Revision ID: 0021_calibration_uncertainty
Revises: 0020_calibration_prerequisites
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.models.enums import CalibrationUncertaintySource, UncertaintyStatisticKind

revision: str = "0021_calibration_uncertainty"
down_revision: str | None = "0020_calibration_prerequisites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_calibration_uncertainty_source_enum = postgresql.ENUM(
    *[m.value for m in CalibrationUncertaintySource], name="calibration_uncertainty_source"
)
_uncertainty_statistic_kind_enum = postgresql.ENUM(
    *[m.value for m in UncertaintyStatisticKind], name="uncertainty_statistic_kind"
)


def upgrade() -> None:
    bind = op.get_bind()

    # Additive-safe enum extension -- never used within this same migration/transaction (PG
    # forbids that), and never removed on downgrade (Postgres has no safe way to drop a single
    # enum label without recreating the type; see module docstring).
    op.execute(
        "ALTER TYPE calibration_objective_weighting ADD VALUE IF NOT EXISTS 'INVERSE_VARIANCE'"
    )

    _calibration_uncertainty_source_enum.create(bind, checkfirst=True)
    _uncertainty_statistic_kind_enum.create(bind, checkfirst=True)

    op.create_table(
        "calibration_experiment_output_weighting",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calibration_experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("output_column_name", sa.Text(), nullable=False),
        sa.Column(
            "uncertainty_source",
            postgresql.ENUM(
                *[m.value for m in CalibrationUncertaintySource],
                name="calibration_uncertainty_source",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("assumed_sigma_value", sa.Numeric(), nullable=True),
        sa.Column("assumed_sigma_unit", sa.String(), nullable=True),
        sa.Column(
            "assumed_sigma_statistic_kind",
            postgresql.ENUM(
                *[m.value for m in UncertaintyStatisticKind],
                name="uncertainty_statistic_kind",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "relative_output_weight", sa.Numeric(), nullable=False, server_default="1"
        ),
        sa.Column("provenance_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_calibration_experiment_output_weighting"),
        sa.ForeignKeyConstraint(
            ["calibration_experiment_id"],
            ["calibration_experiment.id"],
            name="fk_calibration_experiment_output_weighting_experiment_id_ce",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "calibration_experiment_id",
            "output_column_name",
            name="uq_calibration_experiment_output_weighting_experiment_output",
        ),
    )
    op.create_index(
        "ix_calibration_experiment_output_weighting_experiment_id",
        "calibration_experiment_output_weighting",
        ["calibration_experiment_id"],
    )

    op.create_table(
        "time_series_measurement_uncertainty_column",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("time_series_dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=False),
        sa.Column("measurement_column_name", sa.Text(), nullable=False),
        sa.Column(
            "statistic_kind",
            postgresql.ENUM(
                *[m.value for m in UncertaintyStatisticKind],
                name="uncertainty_statistic_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_time_series_measurement_uncertainty_column"),
        sa.ForeignKeyConstraint(
            ["time_series_dataset_id"],
            ["time_series_dataset.id"],
            name="fk_ts_measurement_uncertainty_column_dataset_id_tsd",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "time_series_dataset_id",
            "column_name",
            name="uq_ts_measurement_uncertainty_column_dataset_id_column_name",
        ),
    )
    op.create_index(
        "ix_ts_measurement_uncertainty_column_dataset_id",
        "time_series_measurement_uncertainty_column",
        ["time_series_dataset_id"],
    )

    op.add_column(
        "time_series_dataset_row",
        sa.Column(
            "measurement_uncertainty", sa.Text(), nullable=False, server_default="{}"
        ),
    )


def downgrade() -> None:
    op.drop_column("time_series_dataset_row", "measurement_uncertainty")

    op.drop_index(
        "ix_ts_measurement_uncertainty_column_dataset_id",
        table_name="time_series_measurement_uncertainty_column",
    )
    op.drop_table("time_series_measurement_uncertainty_column")

    op.drop_index(
        "ix_calibration_experiment_output_weighting_experiment_id",
        table_name="calibration_experiment_output_weighting",
    )
    op.drop_table("calibration_experiment_output_weighting")

    bind = op.get_bind()
    _calibration_uncertainty_source_enum.drop(bind, checkfirst=True)
    _uncertainty_statistic_kind_enum.drop(bind, checkfirst=True)

    # The 'INVERSE_VARIANCE' label added to calibration_objective_weighting in upgrade() is
    # deliberately left in place -- see module docstring.
