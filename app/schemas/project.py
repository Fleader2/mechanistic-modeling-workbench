"""Response schemas for ``/api/v1/projects``.

Both schemas expose exactly the columns ``Project`` (see
``app/models/project.py``) actually has -- no field is invented to match a
Figma label that has no backend counterpart (e.g. "Investigator," "Start
date," "Scope / condition," "Knowledge sources," an "Objective" at the
project level). A missing counterpart is the frontend's problem to disclose
honestly, not this schema's problem to paper over.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ProjectType, WorkflowLifecycleStatus
from app.models.project import Project


class ProjectListItem(BaseModel):
    """One row of the "01 — All Projects" table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    stable_identifier: str
    title: str
    project_type: ProjectType
    biological_context_summary: str | None
    study_count: int

    @classmethod
    def from_project(cls, project: Project, *, study_count: int) -> ProjectListItem:
        return cls(
            id=project.id,
            stable_identifier=project.stable_identifier,
            title=project.title,
            project_type=project.project_type,
            biological_context_summary=project.biological_context_summary,
            study_count=study_count,
        )


class ProjectDetail(BaseModel):
    """Every column of one ``Project`` row, for the row-selection preview panel."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    stable_identifier: str
    title: str
    description: str | None
    project_type: ProjectType
    agent1_organism_id: UUID | None
    biological_context_summary: str | None
    strain_genotype_notes: str | None
    biological_process: str | None
    disease: str | None
    tissue: str | None
    cell_type: str | None
    status: WorkflowLifecycleStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


__all__ = ["ProjectDetail", "ProjectListItem"]
