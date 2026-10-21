"""Response schemas for ``/api/v1/projects/{project_id}/subprojects``.

``SubprojectListItem`` follows ``app.schemas.project.ProjectListItem``'s own
precedent: it exposes only the subset of ``Subproject`` columns the
"02 — Current Project" Figma screen's "Modeling Studies" table actually
shows (Study / Scientific question / Models / Datasets), plus the two
derived aggregate counts -- not every column ``Subproject`` has. See
``docs/17_current_project_increment.md``.

``SubprojectDetail`` follows ``app.schemas.project.ProjectDetail``'s own
precedent instead: every column ``Subproject`` actually has, for the
"03 — Modeling Study" detail screen (``docs/18_modeling_study_increment.md``).
Figma's richer, per-project-type "Study information" fields (e.g.
"Biological scope" / "Conditions" / "Success criterion" for one project,
"Tissue / cell type" / "Condition / intervention" / "Seeds" for another) have
no backing column here and are never invented -- only ``objective``,
``task_type``, ``status``, and ``notes`` are real.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import SubprojectTaskType, WorkflowLifecycleStatus
from app.models.subproject import Subproject


class SubprojectListItem(BaseModel):
    """One row of the "Modeling Studies" table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    objective: str | None
    model_count: int
    dataset_count: int

    @classmethod
    def from_subproject(
        cls, subproject: Subproject, *, model_count: int, dataset_count: int
    ) -> SubprojectListItem:
        return cls(
            id=subproject.id,
            title=subproject.title,
            objective=subproject.objective,
            model_count=model_count,
            dataset_count=dataset_count,
        )


class SubprojectDetail(BaseModel):
    """Every column of one ``Subproject`` row, for the "03 — Modeling Study" screen."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    objective: str | None
    task_type: SubprojectTaskType
    status: WorkflowLifecycleStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


__all__ = ["SubprojectDetail", "SubprojectListItem"]
