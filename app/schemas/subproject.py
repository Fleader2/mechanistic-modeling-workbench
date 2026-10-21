"""Response schema for ``GET /api/v1/projects/{project_id}/subprojects``.

Follows ``app.schemas.project.ProjectListItem``'s own precedent: exposes only
the subset of ``Subproject`` columns the "02 — Current Project" Figma
screen's "Modeling Studies" table actually shows (Study / Scientific
question / Models / Datasets), plus the two derived aggregate counts -- not
every column ``Subproject`` has. ``task_type``/``status``/``notes`` are
already available for a future screen; see
``docs/17_current_project_increment.md``.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

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


__all__ = ["SubprojectListItem"]
