"""Read-only ``Project`` routes backing the "01 — All Projects" screen
(Figma node ``46:112``), the "02 — Current Project" screen (node ``46:203``),
and the "03 — Modeling Study" screen (node ``46:314``), file
``4tLH4HX0rdgPxjpNB1aJOW``.

Project/Study creation/editing, opening a model, and every other Figma
section, are out of scope -- see ``docs/16_projects_api_first_increment.md``,
``docs/17_current_project_increment.md``, and
``docs/18_modeling_study_increment.md``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import SessionDep
from app.api.errors import ApiError
from app.models.subproject import Subproject
from app.persistence.dataset_reference import count_dataset_references_by_subproject
from app.persistence.model import count_models_by_subproject, list_models
from app.persistence.project import get_project, list_projects
from app.persistence.subproject import (
    count_subprojects_by_project,
    get_subproject_for_project,
    list_subprojects,
)
from app.schemas.common import ErrorCode
from app.schemas.model import ModelListItem
from app.schemas.project import ProjectDetail, ProjectListItem
from app.schemas.subproject import SubprojectDetail, SubprojectListItem

router = APIRouter(prefix="/projects", tags=["projects"])


def _require_project(session: SessionDep, project_id: UUID) -> None:
    if get_project(session, project_id) is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No project exists with id {project_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


def _require_modeling_study(
    session: SessionDep, project_id: UUID, subproject_id: UUID
) -> Subproject:
    subproject = get_subproject_for_project(session, project_id, subproject_id)
    if subproject is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No Modeling Study exists with id {subproject_id} in project {project_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return subproject


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


@router.get(
    "/{project_id}/subprojects/{subproject_id}",
    response_model=SubprojectDetail,
    summary="Get one Modeling Study",
    description=(
        "Every column of one subproject ('Modeling Study'), scoped to its owning "
        "project -- a subproject id that exists but belongs to a different "
        "project is a 404, identical to one that does not exist at all, never a "
        "cross-project leak."
    ),
)
def get_one_modeling_study(
    project_id: UUID, subproject_id: UUID, session: SessionDep
) -> SubprojectDetail:
    _require_project(session, project_id)
    subproject = _require_modeling_study(session, project_id, subproject_id)
    return SubprojectDetail.model_validate(subproject)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/models",
    response_model=list[ModelListItem],
    summary="List one Modeling Study's models",
    description=(
        "Every model belonging to one Modeling Study, ordered by name. A 404 "
        "(never an empty list) for an unknown project id, an unknown study id, "
        "or a study id that belongs to a different project."
    ),
)
def list_modeling_study_models(
    project_id: UUID, subproject_id: UUID, session: SessionDep
) -> list[ModelListItem]:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    return [ModelListItem.model_validate(model) for model in list_models(session, subproject_id)]
