"""Read-only ``Project`` routes backing the "01 — All Projects" screen
(Figma node ``46:112``), the "02 — Current Project" screen (node ``46:203``),
the "03 — Modeling Study" screen (node ``46:314``), the "05 — Model
Overview" screen (node ``46:564``), and the "05 — Module set drafts and
explicit saving" screens (node ``112:671``), file ``4tLH4HX0rdgPxjpNB1aJOW``.

Project/Study/Model creation/editing, scientific execution, and every other
Figma section, are out of scope -- see
``docs/16_projects_api_first_increment.md``,
``docs/17_current_project_increment.md``,
``docs/18_modeling_study_increment.md``,
``docs/19_model_overview_increment.md``, and
``docs/21_module_set_first_increment.md``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import SessionDep
from app.api.errors import ApiError
from app.models.model import Model
from app.models.module_set import ModuleSetDraft, ModuleSetVersion
from app.models.subproject import Subproject
from app.persistence.dataset_reference import count_dataset_references_by_subproject
from app.persistence.model import (
    count_models_by_subproject,
    get_model,
    get_model_for_subproject,
    list_child_models,
    list_models,
)
from app.persistence.model_module import count_model_modules_by_run
from app.persistence.module_boundary_port import list_boundary_ports_for_module
from app.persistence.module_set import (
    ModuleSetDraftAlreadyResolved,
    create_draft_from_run,
    discard_draft,
    get_draft_for_subproject,
    get_module_set_for_subproject,
    get_module_set_version_by_number,
    list_drafts_for_subproject,
    list_module_sets_for_subproject,
    save_draft,
)
from app.persistence.project import get_project, list_projects
from app.persistence.run_record import list_hierarchical_runs_for_subproject
from app.persistence.subproject import (
    count_subprojects_by_project,
    get_subproject_for_project,
    list_subprojects,
)
from app.schemas.common import ErrorCode
from app.schemas.model import ModelDetail, ModelLineage, ModelListItem
from app.schemas.module_set import (
    BoundaryPortItem,
    CreateModuleSetDraftRequest,
    HierarchicalRunSummary,
    ModuleSetDraftDetail,
    ModuleSetSummary,
    ModuleSetVersionDetail,
    SaveModuleSetDraftRequest,
)
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


def _require_model(session: SessionDep, subproject_id: UUID, model_id: UUID) -> Model:
    model = get_model_for_subproject(session, subproject_id, model_id)
    if model is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No model exists with id {model_id} in Modeling Study {subproject_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return model


def _require_module_set_draft(
    session: SessionDep, subproject_id: UUID, draft_id: UUID
) -> ModuleSetDraft:
    draft = get_draft_for_subproject(session, subproject_id, draft_id)
    if draft is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No module-set draft exists with id {draft_id} in Modeling Study {subproject_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return draft


def _require_module_set_version(
    session: SessionDep, subproject_id: UUID, module_set_id: UUID, version: int
) -> ModuleSetVersion:
    module_set = get_module_set_for_subproject(session, subproject_id, module_set_id)
    if module_set is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No module set exists with id {module_set_id} in Modeling Study {subproject_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    version_row = get_module_set_version_by_number(session, module_set_id, version)
    if version_row is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"Module set {module_set_id} has no version {version}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return version_row


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


@router.get(
    "/{project_id}/subprojects/{subproject_id}/models/{model_id}",
    response_model=ModelDetail,
    summary="Get one model",
    description=(
        "Every column of one model, scoped to its owning Modeling Study and "
        "project -- a model id that exists but belongs to a different study "
        "(or a study belonging to a different project) is a 404, identical to "
        "one that does not exist at all, never a cross-study/cross-project leak."
    ),
)
def get_one_model(
    project_id: UUID, subproject_id: UUID, model_id: UUID, session: SessionDep
) -> ModelDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    model = _require_model(session, subproject_id, model_id)
    return ModelDetail.model_validate(model)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/models/{model_id}/lineage",
    response_model=ModelLineage,
    summary="Get one model's version lineage",
    description=(
        "The parent/child Model rows linked via parent_model_id -- the only "
        "version lineage this schema durably records (no run or execution is "
        "ever required to compute it). A parent or child that exists but "
        "belongs to a different Modeling Study is never included here "
        "cross-study; its existence is disclosed via "
        "parent_out_of_scope/children_out_of_scope_count instead."
    ),
)
def get_model_lineage_route(
    project_id: UUID, subproject_id: UUID, model_id: UUID, session: SessionDep
) -> ModelLineage:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    model = _require_model(session, subproject_id, model_id)

    parent: ModelListItem | None = None
    parent_out_of_scope = False
    if model.parent_model_id is not None:
        parent_row = get_model(session, model.parent_model_id)
        if parent_row is not None and parent_row.subproject_id == subproject_id:
            parent = ModelListItem.model_validate(parent_row)
        else:
            parent_out_of_scope = True

    all_children = list_child_models(session, model.id)
    in_scope_children = [c for c in all_children if c.subproject_id == subproject_id]

    return ModelLineage(
        parent=parent,
        parent_out_of_scope=parent_out_of_scope,
        children=[ModelListItem.model_validate(c) for c in in_scope_children],
        children_out_of_scope_count=len(all_children) - len(in_scope_children),
    )


@router.get(
    "/{project_id}/subprojects/{subproject_id}/hierarchical-runs",
    response_model=list[HierarchicalRunSummary],
    summary="List hierarchical runs a module-set draft can be started from",
    description=(
        "Every SUCCEEDED, model-bearing hierarchical-search run for one Modeling Study, newest "
        "first, with its own materialized-module count. A 404 for an unknown project/study id; "
        "an empty list (not a 404) when the study has no draftable runs yet."
    ),
)
def list_draftable_hierarchical_runs(
    project_id: UUID, subproject_id: UUID, session: SessionDep
) -> list[HierarchicalRunSummary]:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    runs = list_hierarchical_runs_for_subproject(session, subproject_id)
    module_counts = count_model_modules_by_run(session)
    return [
        HierarchicalRunSummary(
            id=run.id,
            model_id=run.model_id,
            created_at=run.created_at,
            module_count=module_counts.get(run.id, 0),
        )
        for run in runs
    ]


@router.post(
    "/{project_id}/subprojects/{subproject_id}/module-set-drafts",
    response_model=ModuleSetDraftDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a module-set draft from an existing hierarchical run",
    description=(
        "Seeds a new, open draft verbatim from one existing run's own materialized modules -- "
        "never edits, re-derives, or creates any ModelModule/HierarchyNode/RunRecord row. A 404 "
        "for an unknown project/study id; a 422 for a run that does not belong to this study, "
        "is not a SUCCEEDED hierarchical run, has no associated model, or has no modules."
    ),
)
def create_module_set_draft(
    project_id: UUID,
    subproject_id: UUID,
    body: CreateModuleSetDraftRequest,
    session: SessionDep,
) -> ModuleSetDraftDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    try:
        draft = create_draft_from_run(
            session=session, subproject_id=subproject_id, run_record_id=body.run_record_id
        )
    except ValueError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, str(exc), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    session.commit()
    return ModuleSetDraftDetail.from_draft(draft)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/module-set-drafts",
    response_model=list[ModuleSetDraftDetail],
    summary="List one Modeling Study's module-set drafts",
    description=(
        "Every OPEN or SAVED draft for one Modeling Study, newest first -- DISCARDED drafts are "
        "hidden from this default listing (the decided rule), never shown unless explicitly "
        "requested."
    ),
)
def list_module_set_drafts(
    project_id: UUID, subproject_id: UUID, session: SessionDep
) -> list[ModuleSetDraftDetail]:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    drafts = list_drafts_for_subproject(session, subproject_id)
    return [ModuleSetDraftDetail.from_draft(draft) for draft in drafts]


@router.get(
    "/{project_id}/subprojects/{subproject_id}/module-set-drafts/{draft_id}",
    response_model=ModuleSetDraftDetail,
    summary="Inspect one module-set draft",
    description=(
        "Read-only: its own hierarchy (derive from each member's resolved ModelModule) and "
        "member list. A 404 for a draft that exists but belongs to a different study/project, "
        "identical to one that does not exist at all."
    ),
)
def get_module_set_draft(
    project_id: UUID, subproject_id: UUID, draft_id: UUID, session: SessionDep
) -> ModuleSetDraftDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    draft = _require_module_set_draft(session, subproject_id, draft_id)
    return ModuleSetDraftDetail.from_draft(draft)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/module-set-drafts/{draft_id}"
    "/members/{member_id}/boundary-ports",
    response_model=list[BoundaryPortItem],
    summary="Inspect one draft member's own structural interface and boundary treatments",
    description=(
        "The resolved ModelModule's own already-derived ModuleBoundaryPort rows -- never "
        "re-derived here, and never mutated (this increment ships no boundary-decision "
        "endpoint). A 404 for an unknown draft, or a member id that exists but belongs to a "
        "different draft."
    ),
)
def get_draft_member_boundary_ports(
    project_id: UUID,
    subproject_id: UUID,
    draft_id: UUID,
    member_id: UUID,
    session: SessionDep,
) -> list[BoundaryPortItem]:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    draft = _require_module_set_draft(session, subproject_id, draft_id)
    member = next((m for m in draft.members if m.id == member_id), None)
    if member is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No member exists with id {member_id} in draft {draft_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    ports = list_boundary_ports_for_module(session, member.model_module_id)
    return [BoundaryPortItem.from_port(port) for port in ports]


@router.post(
    "/{project_id}/subprojects/{subproject_id}/module-set-drafts/{draft_id}/discard",
    response_model=ModuleSetDraftDetail,
    summary="Discard one module-set draft",
    description=(
        "Soft-marks the draft DISCARDED -- never hard-deleted, never creates any ModuleSet/"
        "ModuleSetVersion/ModelModule row. A 409 if the draft is already SAVED or DISCARDED "
        "(duplicate-discard protection)."
    ),
)
def discard_module_set_draft(
    project_id: UUID, subproject_id: UUID, draft_id: UUID, session: SessionDep
) -> ModuleSetDraftDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    _require_module_set_draft(session, subproject_id, draft_id)
    try:
        draft = discard_draft(session, draft_id)
    except ModuleSetDraftAlreadyResolved as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            f"This draft is already {exc.draft.status.value}.",
            status_code=status.HTTP_409_CONFLICT,
            context={"status": exc.draft.status.value},
        ) from exc
    session.commit()
    return ModuleSetDraftDetail.from_draft(draft)


@router.post(
    "/{project_id}/subprojects/{subproject_id}/module-set-drafts/{draft_id}/save",
    response_model=ModuleSetVersionDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Explicitly save one module-set draft",
    description=(
        "mode='new_set' creates a new ModuleSet (version 1); mode='new_version' adds the next "
        "version to an existing one. Never creates a new ModelModule row in this increment -- "
        "every member already references an existing, unedited module. A 409 if the draft is "
        "already SAVED/DISCARDED (duplicate-save protection, returning which version it already "
        "became); a 422 for a missing set_name/existing_set_id, or an attempt to pin a new "
        "version of an existing set to a different model version than its latest version "
        "already pins (changing that pin requires explicit revalidation, not yet supported)."
    ),
)
def save_module_set_draft(
    project_id: UUID,
    subproject_id: UUID,
    draft_id: UUID,
    body: SaveModuleSetDraftRequest,
    session: SessionDep,
) -> ModuleSetVersionDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    _require_module_set_draft(session, subproject_id, draft_id)
    try:
        version = save_draft(
            session=session,
            draft_id=draft_id,
            mode=body.mode,
            set_name=body.set_name,
            existing_set_id=body.existing_set_id,
            version_note=body.version_note,
            saved_by=body.saved_by,
        )
    except ModuleSetDraftAlreadyResolved as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            f"This draft was already saved as version {exc.draft.resulting_version.version}."
            if exc.draft.resulting_version is not None
            else f"This draft is already {exc.draft.status.value}.",
            status_code=status.HTTP_409_CONFLICT,
            context={
                "status": exc.draft.status.value,
                "resulting_version_id": str(exc.draft.resulting_version_id)
                if exc.draft.resulting_version_id
                else None,
            },
        ) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, str(exc), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    session.commit()
    return ModuleSetVersionDetail.from_version(version)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/module-sets",
    response_model=list[ModuleSetSummary],
    summary="List one Modeling Study's module sets",
    description=(
        "Every module set for one study, ordered by stable_identifier, with its own latest "
        "version's summary."
    ),
)
def list_module_sets(
    project_id: UUID, subproject_id: UUID, session: SessionDep
) -> list[ModuleSetSummary]:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    module_sets = list_module_sets_for_subproject(session, subproject_id)
    return [ModuleSetSummary.from_module_set(module_set) for module_set in module_sets]


@router.get(
    "/{project_id}/subprojects/{subproject_id}/module-sets/{module_set_id}/versions/{version}",
    response_model=ModuleSetVersionDetail,
    summary="Reopen one saved module-set version",
    description=(
        "Always read-only -- reopening never creates or mutates anything. A 404 for an unknown "
        "module set, or a version number that set does not have."
    ),
)
def get_module_set_version_route(
    project_id: UUID,
    subproject_id: UUID,
    module_set_id: UUID,
    version: int,
    session: SessionDep,
) -> ModuleSetVersionDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    version_row = _require_module_set_version(session, subproject_id, module_set_id, version)
    return ModuleSetVersionDetail.from_version(version_row)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/module-sets/{module_set_id}/versions/{version}"
    "/members/{member_id}/boundary-ports",
    response_model=list[BoundaryPortItem],
    summary="Inspect one saved version member's own structural interface and boundary treatments",
    description=(
        "The resolved ModelModule's own already-derived ModuleBoundaryPort rows -- never "
        "re-derived or mutated here. A 404 for an unknown version, or a member id that exists "
        "but belongs to a different version."
    ),
)
def get_version_member_boundary_ports(
    project_id: UUID,
    subproject_id: UUID,
    module_set_id: UUID,
    version: int,
    member_id: UUID,
    session: SessionDep,
) -> list[BoundaryPortItem]:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    version_row = _require_module_set_version(session, subproject_id, module_set_id, version)
    member = next((m for m in version_row.members if m.id == member_id), None)
    if member is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No member exists with id {member_id} in version {version} of module set "
            f"{module_set_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    ports = list_boundary_ports_for_module(session, member.model_module_id)
    return [BoundaryPortItem.from_port(port) for port in ports]
