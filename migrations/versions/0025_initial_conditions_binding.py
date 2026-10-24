"""Initial-Conditions Dataset Import increment, part 2: wires the new dataset type
(``0024``) into calibration configuration.

See ``docs/36_initial_conditions_dataset_import_increment.md``. Purely additive. Adds:

* One new enum value on the already-existing ``calibration_binding_value_source`` type --
  ``INITIAL_CONDITIONS_DATASET`` (``ALTER TYPE ... ADD VALUE``, the only additive-safe way to
  extend a Postgres enum -- identical precedent to ``0021``'s own ``INVERSE_VARIANCE`` addition;
  see ``app.models.enums.CalibrationBindingValueSource``).
* ``calibration_experiment.initial_conditions_dataset_id`` (nullable FK, ``RESTRICT``) and
  ``calibration_experiment.initial_conditions_alias_mapping_revision_id`` (nullable FK,
  ``RESTRICT``) -- an experiment's own optionally-pinned initial-conditions dataset, entirely
  separate from its existing ``time_series_dataset_id`` (the calibration *target* data).

No existing column is altered or dropped, and no existing row's data changes -- every
pre-existing ``calibration_experiment`` row reads back byte-identical (both new columns
``NULL``, which is already-correct for a row that predates this increment).

Revision ID: 0025_initial_conditions_binding
Revises: 0024_initial_conditions_dataset
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_initial_conditions_binding"
down_revision: str | None = "0024_initial_conditions_dataset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Additive-safe enum extension -- never used within this same migration/transaction (PG
    # forbids that), and never removed on downgrade (Postgres has no safe way to drop a single
    # enum label without recreating the type; see module docstring).
    op.execute(
        "ALTER TYPE calibration_binding_value_source ADD VALUE IF NOT EXISTS "
        "'INITIAL_CONDITIONS_DATASET'"
    )

    op.add_column(
        "calibration_experiment",
        sa.Column("initial_conditions_dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_calibration_experiment_initial_conditions_dataset_id_icd",
        "calibration_experiment",
        "initial_conditions_dataset",
        ["initial_conditions_dataset_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_calibration_experiment_initial_conditions_dataset_id",
        "calibration_experiment",
        ["initial_conditions_dataset_id"],
    )

    op.add_column(
        "calibration_experiment",
        sa.Column(
            "initial_conditions_alias_mapping_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_calibration_experiment_ic_alias_mapping_revision_id_icamr",
        "calibration_experiment",
        "initial_conditions_alias_mapping_revision",
        ["initial_conditions_alias_mapping_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_calibration_experiment_ic_alias_mapping_revision_id",
        "calibration_experiment",
        ["initial_conditions_alias_mapping_revision_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_calibration_experiment_ic_alias_mapping_revision_id",
        table_name="calibration_experiment",
    )
    op.drop_constraint(
        "fk_calibration_experiment_ic_alias_mapping_revision_id_icamr",
        "calibration_experiment",
        type_="foreignkey",
    )
    op.drop_column("calibration_experiment", "initial_conditions_alias_mapping_revision_id")

    op.drop_index(
        "ix_calibration_experiment_initial_conditions_dataset_id",
        table_name="calibration_experiment",
    )
    op.drop_constraint(
        "fk_calibration_experiment_initial_conditions_dataset_id_icd",
        "calibration_experiment",
        type_="foreignkey",
    )
    op.drop_column("calibration_experiment", "initial_conditions_dataset_id")

    # The 'INITIAL_CONDITIONS_DATASET' label added to calibration_binding_value_source in
    # upgrade() is deliberately left in place -- see module docstring.
