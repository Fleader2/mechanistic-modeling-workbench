"""CalibrationScenarioEvaluationSnapshot: an immutable, versioned record of exactly what was
used to evaluate one experimental scenario against one saved ``CalibrationJobRevision`` --
the Whole-Model Experimental-Scenario Evaluation increment's own provenance table.

Mirrors ``app.models.module_execution_snapshot.ModuleExecutionSnapshot``'s own established
discipline exactly: one row per execution (``run_record_id`` unique -- 1:1), created once, at
request-construction time (before any harness subprocess is invoked, so a snapshot exists even
for a run that later fails during execution), and never updated afterward -- a later edit to
the job's own live draft (which never touches an already-captured ``CalibrationJobRevision``;
see that model's own docstring) can, even less, ever alter a historical evaluation snapshot.

``ON DELETE RESTRICT`` from every FK: like ``ModuleExecutionSnapshot``, this is a durable,
independently-meaningful provenance record, never ephemeral workflow bookkeeping.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.calibration import CalibrationExperiment, CalibrationJobRevision
from app.models.run_record import RunRecord


class CalibrationScenarioEvaluationSnapshot(Base):
    """One immutable, versioned capture of one scenario evaluation's own exact inputs."""

    __tablename__ = "calibration_scenario_evaluation_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "run_record_id", name="uq_calibration_scenario_evaluation_snapshot_run_record_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    calibration_experiment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "calibration_experiment.id",
            ondelete="RESTRICT",
            name="fk_calibration_scenario_evaluation_snapshot_experiment_id",
        ),
        nullable=False,
        index=True,
    )
    calibration_job_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "calibration_job_revision.id",
            ondelete="RESTRICT",
            name="fk_calibration_scenario_evaluation_snapshot_revision_id",
        ),
        nullable=False,
        index=True,
    )
    run_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "run_record.id",
            ondelete="RESTRICT",
            name="fk_calibration_scenario_evaluation_snapshot_run_record_id",
        ),
        nullable=False,
    )

    #: The dataset's own recorded condition this evaluation is scoped to (e.g. a
    #: ``condition_legend`` value) -- ``NULL`` for an experiment with no declared condition
    #: column at all. Never a free-form label: when set, every ``DATASET_COLUMN``-sourced
    #: binding value is required to be identical across every row of this experiment+condition
    #: (see ``app.persistence.calibration_scenario_evaluation`` for exactly where this
    #: "never treat successive dose rows as a dosing schedule" rejection happens).
    condition_id: Mapped[str | None] = mapped_column(Text)

    #: ``sha256`` hex digest of the canonical (sorted-key) JSON encoding of
    #: ``{calibration_experiment_id, calibration_job_revision_id, condition_id,
    #: candidate_parameter_values, solver_settings}`` -- deterministic and always computable
    #: before any harness subprocess is invoked, so a snapshot exists even for a run that later
    #: fails. Used only for duplicate-active-run detection, enforced at the persistence layer
    #: (``app.persistence.calibration_scenario_evaluation.submit_scenario_evaluation`` -- never
    #: a database constraint, since the columns that identify "the same scenario" live here
    #: while run status lives on ``RunRecord``, and Postgres partial-index predicates cannot
    #: reference another table) -- deliberately scoped to a genuinely identical resubmission,
    #: never to "any new submission for this experiment," since re-evaluating the identical
    #: scenario against a *different* candidate parameter vector is the normal, expected way
    #: Agent 4's future joint-optimization loop will call this repeatedly.
    input_hash: Mapped[str] = mapped_column(String, nullable=False)

    #: Opaque, pre-serialized JSON object -- decoded nowhere except
    #: ``app.schemas.calibration_scenario_evaluation``'s own documented reader, matching
    #: ``ModuleExecutionSnapshot.snapshot_payload``'s own established "opaque TEXT blob"
    #: discipline. Carries the pinned model artifact reference, the resolved bindings actually
    #: applied, the requested times/output ids (aligned to real dataset rows where
    #: applicable), the candidate parameter values supplied, and the solver settings used.
    snapshot_payload: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str | None] = mapped_column(String)

    calibration_experiment: Mapped[CalibrationExperiment] = relationship()
    calibration_job_revision: Mapped[CalibrationJobRevision] = relationship()
    run_record: Mapped[RunRecord] = relationship()


__all__ = ["CalibrationScenarioEvaluationSnapshot"]
