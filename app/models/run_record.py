"""RunRecord: durable workflow execution history.

See ``docs/02_database_schema.md`` ("Table: run_record").

A durable version of what the integration harness today only keeps as
gitignored, regenerable ``artifacts/runs/<run_id>/`` output -- per the
architecture audit, the harness itself owns no persistent run history; the
Workbench is the first repository positioned to keep one. This table never
re-implements the harness's own contract-version-enforcement or invariant
checks -- it only records that a stage ran, its status, and a pointer to
whatever artifact/contract version it produced.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import RunStage, RunStatus
from app.models.model import Model
from app.models.subproject import Subproject

_RUN_STAGE = Enum(RunStage, name="run_stage", create_type=False)
_RUN_STATUS = Enum(RunStatus, name="run_status", create_type=False)


class RunRecord(Base):
    """One invocation of one pipeline stage (an agent or the harness itself)."""

    __tablename__ = "run_record"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    subproject_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subproject.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("model.id", ondelete="RESTRICT"), index=True
    )

    stage: Mapped[RunStage] = mapped_column(_RUN_STAGE, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        _RUN_STATUS,
        nullable=False,
        default=RunStatus.PENDING,
        server_default=RunStatus.PENDING.value,
    )

    #: The contract/artifact version this run's output declared, e.g.
    #: ``"1.6"`` (Agent 1) or ``"agent2-downstream-v1"`` (Agent 2 onward) --
    #: free text, since each stage's own contract version format differs and
    #: the Workbench never enforces or interprets it (that stays the
    #: harness's job).
    contract_version: Mapped[str | None] = mapped_column(String)

    #: Opaque pointer to this run's output artifact (e.g. a harness run
    #: directory). Never parsed or interpreted here.
    artifact_reference: Mapped[str | None] = mapped_column(Text)

    result_summary: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    subproject: Mapped[Subproject] = relationship()
    model: Mapped[Model | None] = relationship()


__all__ = ["RunRecord"]
