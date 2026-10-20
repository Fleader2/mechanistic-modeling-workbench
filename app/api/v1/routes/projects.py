"""Read-only ``Project`` routes backing the "01 — All Projects" screen
(Figma node ``46:112``, file ``4tLH4HX0rdgPxjpNB1aJOW``).

Project creation/editing, and every other Figma section, are out of scope
for this increment -- see ``docs/16_projects_api_first_increment.md``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import SessionDep
from app.api.errors import ApiError
from app.persistence.project import get_project, list_projects
from app.persistence.subproject import count_subprojects_by_project
from app.schemas.common import ErrorCode
from app.schemas.project import ProjectDetail, ProjectListItem

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "",
    response_model=list[ProjectListItem],
    summary="List all projects",
    description=(
        "Every project, ordered by title, with a derived study count computed "
        "in one aggregate query (never one query per project)."
    ),
)
def list_all_projects(session: SessionDep) -> list[ProjectListItem]:
    projects = list_projects(session)
    study_counts = count_subprojects_by_project(session)
    return [
        ProjectListItem.from_project(project, study_count=study_counts.get(project.id, 0))
        for project in projects
    ]


@router.get(
    "/{project_id}",
    response_model=ProjectDetail,
    summary="Get one project",
    description="Every column of one project, for the row-selection preview panel.",
)
def get_one_project(project_id: UUID, session: SessionDep) -> ProjectDetail:
    project = get_project(session, project_id)
    if project is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No project exists with id {project_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return ProjectDetail.model_validate(project)
