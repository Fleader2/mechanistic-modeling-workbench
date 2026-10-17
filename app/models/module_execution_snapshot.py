"""ModuleExecutionSnapshot: an immutable, versioned record of exactly what was used to execute
one module-scoped Agent 3/Agent 4 run (Module-Level Agent4 Calibration with Immutable
Execution-Condition Provenance increment).

See ``docs/09_module_level_agent4_calibration.md``. A ``ModuleBoundaryPort``'s own
``treatment_type``/``initial_value`` can be revised later (a human reviewer changes their
mind), and a ``DatasetReference`` is not itself schema-enforced immutable -- so neither can
serve, on its own, as the durable record of "what this *specific, already-completed* execution
actually used." This table exists to close that gap: one row per execution
(``run_record_id`` unique -- 1:1, the idempotency key repeated requests for the identical run
always resolve against), created once, at request-construction time, and never updated
afterward (no ``updated_at`` column, and no persistence function in this repository ever
issues an ``UPDATE`` against it) -- a later change to a boundary decision, a dataset's own
catalog row, or anything else, never alters a historical snapshot already on file.

``ON DELETE RESTRICT`` from both ``model_module`` and ``run_record``: like ``model_module``
itself, this is a durable, independently-meaningful provenance record, never ephemeral
workflow bookkeeping -- the "has its own lineage" precedent, not the "no independent existence
apart from its parent" precedent ``module_boundary_port``'s own ``CASCADE`` uses.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ModuleExecutionKind
from app.models.model_module import ModelModule
from app.models.run_record import RunRecord

_MODULE_EXECUTION_KIND = Enum(ModuleExecutionKind, name="module_execution_kind", create_type=False)


class ModuleExecutionSnapshot(Base):
    """One immutable, versioned capture of a module-scoped execution's own exact inputs."""

    __tablename__ = "module_execution_snapshot"
    __table_args__ = (
        UniqueConstraint("run_record_id", name="uq_module_execution_snapshot_run_record_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    model_module_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_module.id",
            ondelete="RESTRICT",
            name="fk_module_execution_snapshot_model_module_id",
        ),
        nullable=False,
        index=True,
    )
    run_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "run_record.id", ondelete="RESTRICT", name="fk_module_execution_snapshot_run_record_id"
        ),
        nullable=False,
    )

    #: Denormalized from ``run_record.stage`` at creation time -- see module docstring.
    execution_kind: Mapped[ModuleExecutionKind] = mapped_column(
        _MODULE_EXECUTION_KIND, nullable=False
    )

    #: ``sha256`` hex digest of the canonical (sorted-key) JSON encoding of the exact Agent 2
    #: materialization input (``attach_payload`` + its own merged ``module_ports``) this
    #: execution used -- deterministic and always computable before any harness subprocess is
    #: invoked, so a snapshot exists even for a run that later fails during execution. Never a
    #: hash of Agent 2's own *output*, since that is only known after a successful round trip
    #: and this snapshot must be creatable regardless of outcome (see
    #: ``app.orchestration.module_calibration_orchestrator`` for exactly where this is
    #: computed and when the snapshot is created relative to the harness call).
    module_artifact_hash: Mapped[str] = mapped_column(String, nullable=False)

    #: Opaque, pre-serialized JSON object -- decoded nowhere except
    #: ``app.persistence.module_execution_snapshot.read_snapshot_payload``, the one documented
    #: site, matching ``ModelModule.attach_payload``'s own established "opaque TEXT blob"
    #: discipline. Always carries ``{"boundary_ports", "contract_versions"}``; carries
    #: ``{"calibration_config", "dataset_references"}`` only for ``execution_kind
    #: =CALIBRATION`` (``None``/absent for ``SIMULATION``, which has neither); carries
    #: ``{"module_handoff_summary"}`` once the underlying harness call actually completes
    #: (absent if the run failed before a module artifact was ever materialized).
    snapshot_payload: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    model_module: Mapped[ModelModule] = relationship()
    run_record: Mapped[RunRecord] = relationship()


__all__ = ["ModuleExecutionSnapshot"]
