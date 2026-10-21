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
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import RunStage, RunStatus
from app.models.model import Model
from app.models.model_build_request import ModelBuildRequest
from app.models.subproject import Subproject

if TYPE_CHECKING:
    # Executable-Module Materialization increment: type-checking-only, to avoid a real circular
    # import (``model_module.py`` itself imports ``RunRecord``) -- resolved at runtime purely
    # by name via ``relationship(foreign_keys=...)`` below, never actually evaluated as a bare
    # annotation (``from __future__ import annotations`` keeps every annotation a deferred
    # string).
    from app.models.model_module import ModelModule

    # Module-Set Edited-Module Materialization increment: identical type-checking-only
    # avoidance of a real circular import (``module_set.py`` itself imports ``ModelModule``,
    # which imports ``RunRecord``).
    from app.models.module_set import ModuleSetMember

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
    #: Scoped-Build Support increment: the ``ModelBuildRequest`` that scoped this run, when one
    #: was supplied. Associated here rather than onto ``Model`` -- a ``Model`` row's own
    #: lineage is independent of which specific run attempt built it, while ``RunRecord``
    #: already records every other request parameter a run was invoked with (``model_id``).
    model_build_request_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_build_request.id",
            ondelete="RESTRICT",
            name="fk_run_record_model_build_request_id_mbr",
        ),
        index=True,
    )
    #: Executable-Module Materialization increment: the ``ModelModule`` this run simulated --
    #: set only for a module-simulation run (``stage=RunStage.AGENT3``, Agent 2 then Agent 3
    #: against one accepted hierarchy module's own artifact); ``NULL`` for every other stage,
    #: including an ordinary whole-model Agent 3 run as part of ``FULL_PIPELINE``.
    model_module_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_module.id", ondelete="RESTRICT", name="fk_run_record_model_module_id_mm"),
        index=True,
    )
    #: Module-Set Edited-Module Materialization increment: the ``ModuleSetMember`` this run
    #: simulated -- set only for a module-set-scoped simulation run (``stage=RunStage.AGENT3``,
    #: Agent 2 rebuild from this member's own current reaction selection, then Agent 3);
    #: ``NULL`` for every other run, including an ordinary unedited-module simulation (which
    #: sets ``model_module_id`` alone, exactly as before this increment). A run's
    #: ``model_module_id`` is still set alongside this for the member's own underlying module,
    #: for cross-cutting module-level queries -- but only this column distinguishes *which*
    #: module-set member's own (possibly-edited) selection was actually simulated.
    module_set_member_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "module_set_member.id",
            ondelete="RESTRICT",
            name="fk_run_record_module_set_member_id_msm",
        ),
        index=True,
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
    #: Scoped-Build Support increment: a JSON-encoded list of warning strings a scoped build
    #: returned (e.g. an unresolved ModelBuildRequest reference, an unsupported pathway
    #: constraint) -- opaque to the Workbench, never parsed or interpreted here, matching
    #: ``artifact_reference``'s own "store, never interpret" policy.
    warnings: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    subproject: Mapped[Subproject] = relationship()
    model: Mapped[Model | None] = relationship()
    model_build_request: Mapped[ModelBuildRequest | None] = relationship()
    model_module: Mapped[ModelModule | None] = relationship(
        foreign_keys="RunRecord.model_module_id"
    )
    module_set_member: Mapped[ModuleSetMember | None] = relationship(
        foreign_keys="RunRecord.module_set_member_id"
    )


__all__ = ["RunRecord"]
