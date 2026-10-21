"""Read-only ``Project`` routes backing the "01 — All Projects" screen
(Figma node ``46:112``) and the "02 — Current Project" screen (node
``46:203``), file ``4tLH4HX0rdgPxjpNB1aJOW``.

Project creation/editing, opening a Modeling Study, and every other Figma
section, are out of scope -- see ``docs/16_projects_api_first_increment.md``
and ``docs/17_current_project_increment.md``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import SessionDep
from app.api.errors import ApiError
from app.persistence.dataset_reference import count_dataset_references_by_subproject
from app.persistence.model import count_models_by_subproject
from app.persistence.project import get_project, list_projects
from app.persistence.subproject import count_subprojects_by_project, list_subprojects
from app.schemas.common import ErrorCode
from app.schemas.project import ProjectDetail, ProjectListItem
from app.schemas.subproject import SubprojectListItem

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


@router.get(
    "/{project_id}/subprojects",
    response_model=list[SubprojectListItem],
    summary="List one project's Modeling Studies",
    description=(
        "Every subproject ('Modeling Study') belonging to one project, ordered by "
        "title, with per-study model and dataset counts each computed in one "
        "aggregate query (never one query per study). A 404, not an empty list, "
        "for an unknown project id."
    ),
)
def list_project_modeling_studies(
    project_id: UUID, session: SessionDep
) -> list[SubprojectListItem]:
    project = get_project(session, project_id)
    if project is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No project exists with id {project_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    subprojects = list_subprojects(session, project_id)
    model_counts = count_models_by_subproject(session)
    dataset_counts = count_dataset_references_by_subproject(session)
    return [
        SubprojectListItem.from_subproject(
            subproject,
            model_count=model_counts.get(subproject.id, 0),
            dataset_count=dataset_counts.get(subproject.id, 0),
        )
        for subproject in subprojects
    ]
