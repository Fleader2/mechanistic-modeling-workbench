"""Subproject: one specific modeling effort/objective within a Project.

See ``docs/02_database_schema.md`` ("Table: subproject").
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import SubprojectTaskType, WorkflowLifecycleStatus
from app.models.project import Project

if TYPE_CHECKING:
    from app.models.model import Model
    from app.models.model_build_request import ModelBuildRequest

_SUBPROJECT_TASK_TYPE = Enum(SubprojectTaskType, name="subproject_task_type", create_type=False)
_WORKFLOW_LIFECYCLE_STATUS = Enum(
    WorkflowLifecycleStatus, name="workflow_lifecycle_status", create_type=False
)


class Subproject(Base):
    """One specific modeling effort/objective belonging to a ``Project``.

    ``task_type`` names which stage of the five-agent pipeline this
    subproject is currently driving -- a pure orchestration/workflow fact,
    never a biochemical one.
    """

    __tablename__ = "subproject"
    __table_args__ = (
        UniqueConstraint("project_id", "title", name="uq_subproject_project_id_title"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("project.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String, nullable=False)
    objective: Mapped[str | None] = mapped_column(Text)

    task_type: Mapped[SubprojectTaskType] = mapped_column(_SUBPROJECT_TASK_TYPE, nullable=False)

    status: Mapped[WorkflowLifecycleStatus] = mapped_column(
        _WORKFLOW_LIFECYCLE_STATUS,
        nullable=False,
        default=WorkflowLifecycleStatus.ACTIVE,
        server_default=WorkflowLifecycleStatus.ACTIVE.value,
    )

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="subprojects")
    build_request: Mapped[ModelBuildRequest | None] = relationship(
        back_populates="subproject", cascade="all, delete-orphan", passive_deletes=True
    )
    models: Mapped[list[Model]] = relationship(back_populates="subproject")


__all__ = ["Subproject"]
