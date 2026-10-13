"""Project: the long-lived scientific/organizational effort a user manages.

See ``docs/02_database_schema.md`` ("Table: project") and
``docs/01_workbench_architecture.md``.

Per the architecture audit, ``Project`` is split from Agent 1's own
(to-be-retired) ``project`` table: the Workbench owns the *container* --
identity, title, lifecycle status -- while the underlying biological
framing is a reference/copy of whatever Agent 1 record describes that
biology, never a live call back into Agent 1's database.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ProjectType, WorkflowLifecycleStatus

if TYPE_CHECKING:
    from app.models.subproject import Subproject

_PROJECT_TYPE = Enum(ProjectType, name="project_type", create_type=False)
_WORKFLOW_LIFECYCLE_STATUS = Enum(
    WorkflowLifecycleStatus, name="workflow_lifecycle_status", create_type=False
)


class Project(Base):
    """One long-lived project a user manages across the five-agent pipeline.

    ``agent1_organism_id`` and the free-text biological-context fields below
    are a one-time *copy* of whatever Agent 1 told the Workbench when the
    project was created (e.g. via a future ``Agent1BiologicalContextView``
    contract, see ``app/contracts/agent1.py``) -- never a live foreign key
    into Agent 1's database, which the Workbench cannot reach and must
    never assume it can reach.
    """

    __tablename__ = "project"
    __table_args__ = (UniqueConstraint("stable_identifier", name="uq_project_stable_identifier"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    stable_identifier: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    project_type: Mapped[ProjectType] = mapped_column(_PROJECT_TYPE, nullable=False)

    #: A copied Agent 1 ``organism.id`` -- never a foreign key (see module docstring).
    agent1_organism_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    biological_context_summary: Mapped[str | None] = mapped_column(Text)
    strain_genotype_notes: Mapped[str | None] = mapped_column(Text)
    biological_process: Mapped[str | None] = mapped_column(Text)
    disease: Mapped[str | None] = mapped_column(String)
    tissue: Mapped[str | None] = mapped_column(String)
    cell_type: Mapped[str | None] = mapped_column(String)

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

    subprojects: Mapped[list[Subproject]] = relationship(back_populates="project")


__all__ = ["Project"]
