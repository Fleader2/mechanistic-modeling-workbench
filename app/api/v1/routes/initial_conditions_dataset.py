"""Initial-Conditions Dataset Import increment: upload a long-format initial-conditions
dataset (one row per target species/parameter, e.g. one cell type's own protein/metabolite
abundance profile), preview/save it, and map its own distinct ``target_name`` values to real
model species/parameters. See ``docs/36_initial_conditions_dataset_import_increment.md``.

Mirrors the time-series dataset's own preview/save/list/get and alias-mapping routes exactly
-- a deliberately separate router/dataset type, never a generalization of them (see
``app.models.initial_conditions_dataset``/``app.models.initial_conditions_alias_mapping``
module docstrings for why).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Response, UploadFile, status

from app.api.deps import SessionDep
from app.api.errors import ApiError
from app.api.v1.routes.projects import _require_model, _require_modeling_study, _require_project
from app.initial_conditions.parser import (
    InitialConditionsWorkbookMalformedError,
    parse_initial_conditions_workbook,
)
from app.initial_conditions.template import generate_initial_conditions_template_workbook
from app.models.initial_conditions_dataset import InitialConditionsDataset
from app.persistence.initial_conditions_alias_mapping import (
    AmbiguousMappingTargetError,
    AssignmentInput,
    DuplicateMappingTargetIdError,
    InvalidMappingTargetIdError,
    InvalidMappingTargetNameError,
    MappingCatalogsUnavailableError,
    MappingRevisionStaleError,
    get_current_mapping_revision,
    get_mapping_revision,
    list_mapping_revisions,
    save_mapping_revision,
)
from app.persistence.initial_conditions_dataset import (
    get_initial_conditions_dataset,
    list_initial_conditions_datasets_for_subproject,
    persist_initial_conditions_dataset,
)
from app.persistence.model_parameter_catalog import get_model_parameter_catalog
from app.persistence.model_species_catalog import get_model_species_catalog
from app.schemas.common import ErrorCode
from app.schemas.initial_conditions_alias_mapping import (
    InitialConditionsAliasMappingDetail,
    InitialConditionsAliasMappingRevisionSummary,
    SaveInitialConditionsAliasMappingRequest,
)
from app.schemas.initial_conditions_dataset import (
    InitialConditionsDatasetDetail,
    InitialConditionsDatasetListItem,
    InitialConditionsWorkbookPreview,
)

router = APIRouter(prefix="/projects", tags=["initial-conditions-dataset"])


def _require_initial_conditions_dataset(
    session: SessionDep, subproject_id: UUID, dataset_id: UUID
) -> InitialConditionsDataset:
    dataset = get_initial_conditions_dataset(session, dataset_id)
    if dataset is None or dataset.dataset_reference.subproject_id != subproject_id:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No initial-conditions dataset exists with id {dataset_id} in Modeling Study "
            f"{subproject_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return dataset


@router.get(
    "/{project_id}/subprojects/{subproject_id}/datasets/initial-conditions/template",
    summary="Download the blank two-tab initial-conditions dataset Excel template",
    description=(
        "A generic, reusable .xlsx template (Metadata + Data tabs) -- identical regardless of "
        "which project/study it is requested under. A 404 for an unknown project/study."
    ),
)
def download_initial_conditions_dataset_template(
    project_id: UUID, subproject_id: UUID, session: SessionDep
) -> Response:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    return Response(
        content=generate_initial_conditions_template_workbook(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                'attachment; filename="initial_conditions_dataset_template.xlsx"'
            )
        },
    )


@router.post(
    "/{project_id}/subprojects/{subproject_id}/datasets/initial-conditions/preview",
    response_model=InitialConditionsWorkbookPreview,
    summary="Parse an uploaded initial-conditions workbook and preview it -- never persisted",
    description=(
        "A 422 (never a 500, never a partial result) if the workbook is malformed -- missing "
        "a required sheet, no Data-tab header row, no 'target_name' column, or no measurement "
        "columns -- with every such problem in the error context."
    ),
)
async def preview_initial_conditions_dataset(
    project_id: UUID,
    subproject_id: UUID,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
) -> InitialConditionsWorkbookPreview:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    data = await file.read()
    try:
        parsed = parse_initial_conditions_workbook(data)
    except InitialConditionsWorkbookMalformedError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "This workbook could not be imported.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context={
                "findings": [
                    {"code": f.code, "severity": f.severity, "message": f.message}
                    for f in exc.findings
                ]
            },
        ) from exc
    dataset_name = parsed.metadata.get("dataset_name") or (
        file.filename.rsplit(".", 1)[0] if file.filename else "untitled"
    )
    return InitialConditionsWorkbookPreview.from_parsed(
        parsed,
        original_filename=file.filename or "untitled.xlsx",
        effective_dataset_name=dataset_name,
    )


@router.post(
    "/{project_id}/subprojects/{subproject_id}/datasets/initial-conditions",
    response_model=InitialConditionsDatasetDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Save an uploaded initial-conditions dataset workbook",
    description=(
        "Re-parses and durably persists the uploaded .xlsx -- never trusts a client-side echo "
        "of an earlier preview. Re-saving byte-identical content already saved for this "
        "project/name reuses the existing dataset rather than duplicating it."
    ),
)
async def save_initial_conditions_dataset(
    project_id: UUID,
    subproject_id: UUID,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    saved_by: Annotated[str | None, Form()] = None,
) -> InitialConditionsDatasetDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    data = await file.read()
    try:
        result = persist_initial_conditions_dataset(
            session=session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename=file.filename or "untitled.xlsx",
            workbook_bytes=data,
            saved_by=saved_by,
        )
    except InitialConditionsWorkbookMalformedError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "This workbook could not be imported.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context={
                "findings": [
                    {"code": f.code, "severity": f.severity, "message": f.message}
                    for f in exc.findings
                ]
            },
        ) from exc
    session.commit()
    assert result.entity_id is not None
    dataset = get_initial_conditions_dataset(session, result.entity_id)
    assert dataset is not None
    return InitialConditionsDatasetDetail.from_model(dataset)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/datasets/initial-conditions",
    response_model=list[InitialConditionsDatasetListItem],
    summary="List every saved initial-conditions dataset for one Modeling Study",
    description="Newest first. Nothing is ever deleted. A 404 for an unknown project/study.",
)
def list_initial_conditions_datasets(
    project_id: UUID, subproject_id: UUID, session: SessionDep
) -> list[InitialConditionsDatasetListItem]:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    datasets = list_initial_conditions_datasets_for_subproject(session, subproject_id)
    return [InitialConditionsDatasetListItem.from_model(d) for d in datasets]


@router.get(
    "/{project_id}/subprojects/{subproject_id}/datasets/initial-conditions/{dataset_id}",
    response_model=InitialConditionsDatasetDetail,
    summary="Reopen one saved initial-conditions dataset -- read-only",
)
def get_one_initial_conditions_dataset(
    project_id: UUID, subproject_id: UUID, dataset_id: UUID, session: SessionDep
) -> InitialConditionsDatasetDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    dataset = _require_initial_conditions_dataset(session, subproject_id, dataset_id)
    return InitialConditionsDatasetDetail.from_model(dataset)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/datasets/initial-conditions/{dataset_id}"
    "/alias-mapping/{model_id}",
    response_model=InitialConditionsAliasMappingDetail,
    summary="The current alias-mapping revision for one (initial-conditions dataset, model) pair",
    description=(
        "The current mapping, or an all-UNRESOLVED/never-saved state if none exists yet -- "
        "plus the model's own verified species and parameter catalogs and every distinct "
        "target_name's own source identity. A 404 for an unknown dataset or model."
    ),
)
def get_current_initial_conditions_alias_mapping(
    project_id: UUID, subproject_id: UUID, dataset_id: UUID, model_id: UUID, session: SessionDep
) -> InitialConditionsAliasMappingDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    dataset = _require_initial_conditions_dataset(session, subproject_id, dataset_id)
    _require_model(session, subproject_id, model_id)
    species_catalog = get_model_species_catalog(session, model_id)
    parameter_catalog = get_model_parameter_catalog(session, model_id)
    revision = get_current_mapping_revision(
        session, initial_conditions_dataset_id=dataset_id, model_id=model_id
    )
    return InitialConditionsAliasMappingDetail.build(
        dataset=dataset,
        model_id=model_id,
        species_catalog=species_catalog,
        parameter_catalog=parameter_catalog,
        revision=revision,
    )


@router.post(
    "/{project_id}/subprojects/{subproject_id}/datasets/initial-conditions/{dataset_id}"
    "/alias-mapping/{model_id}",
    response_model=InitialConditionsAliasMappingDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Save a new alias-mapping revision for one (initial-conditions dataset, model) pair",
    description=(
        "Always creates a new, immutable revision. A 409 if expected_revision_number is stale "
        "or neither catalog is AVAILABLE; a 422 for an unknown target_name, an invalid/"
        "ambiguous target id, or two target_names assigned to the identical target."
    ),
)
def save_initial_conditions_alias_mapping(
    project_id: UUID,
    subproject_id: UUID,
    dataset_id: UUID,
    model_id: UUID,
    body: SaveInitialConditionsAliasMappingRequest,
    session: SessionDep,
) -> InitialConditionsAliasMappingDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    dataset = _require_initial_conditions_dataset(session, subproject_id, dataset_id)
    _require_model(session, subproject_id, model_id)
    species_catalog = get_model_species_catalog(session, model_id)
    parameter_catalog = get_model_parameter_catalog(session, model_id)
    try:
        revision = save_mapping_revision(
            session=session,
            dataset=dataset,
            model_id=model_id,
            model_species_catalog=species_catalog,
            model_parameter_catalog=parameter_catalog,
            assignments=[
                AssignmentInput(
                    target_name=a.target_name,
                    status=a.status,
                    target_kind=a.target_kind,
                    target_id=a.target_id,
                )
                for a in body.assignments
            ],
            expected_revision_number=body.expected_revision_number,
            saved_by=body.saved_by,
        )
    except MappingCatalogsUnavailableError as exc:
        raise ApiError(
            ErrorCode.CONFLICT, str(exc), status_code=status.HTTP_409_CONFLICT
        ) from exc
    except MappingRevisionStaleError as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "This mapping was changed since you last loaded it.",
            status_code=status.HTTP_409_CONFLICT,
            context={
                "current_revision_number": (
                    0
                    if exc.current_revision is None
                    else exc.current_revision.revision_number
                )
            },
        ) from exc
    except InvalidMappingTargetNameError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "One or more assignments name a target_name that is not real in this dataset.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context={"unknown_target_names": exc.unknown_target_names},
        ) from exc
    except AmbiguousMappingTargetError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "One or more target ids match both a real species and a real independent "
            "parameter -- never guessed.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context={"ambiguous": exc.ambiguous},
        ) from exc
    except InvalidMappingTargetIdError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "One or more assignments name an id that is not a real, independent target in "
            "this model's own verified catalog(s).",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context={"invalid": exc.invalid},
        ) from exc
    except DuplicateMappingTargetIdError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "More than one target_name is assigned to the identical target -- never silently "
            "combined.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context={"conflicts": exc.conflicts},
        ) from exc
    session.commit()
    dataset = _require_initial_conditions_dataset(session, subproject_id, dataset_id)
    return InitialConditionsAliasMappingDetail.build(
        dataset=dataset,
        model_id=model_id,
        species_catalog=species_catalog,
        parameter_catalog=parameter_catalog,
        revision=revision,
    )


@router.get(
    "/{project_id}/subprojects/{subproject_id}/datasets/initial-conditions/{dataset_id}"
    "/alias-mapping/{model_id}/revisions",
    response_model=list[InitialConditionsAliasMappingRevisionSummary],
    summary="Every alias-mapping revision ever saved for one (dataset, model) pair",
    description="Newest first. Nothing is ever deleted.",
)
def list_initial_conditions_alias_mapping_revisions(
    project_id: UUID, subproject_id: UUID, dataset_id: UUID, model_id: UUID, session: SessionDep
) -> list[InitialConditionsAliasMappingRevisionSummary]:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    _require_initial_conditions_dataset(session, subproject_id, dataset_id)
    _require_model(session, subproject_id, model_id)
    revisions = list_mapping_revisions(
        session, initial_conditions_dataset_id=dataset_id, model_id=model_id
    )
    return [InitialConditionsAliasMappingRevisionSummary.from_revision(r) for r in revisions]


@router.get(
    "/{project_id}/subprojects/{subproject_id}/datasets/initial-conditions/{dataset_id}"
    "/alias-mapping/{model_id}/revisions/{revision_number}",
    response_model=InitialConditionsAliasMappingDetail,
    summary="Reopen one specific, historical alias-mapping revision -- read-only",
)
def get_one_initial_conditions_alias_mapping_revision(
    project_id: UUID,
    subproject_id: UUID,
    dataset_id: UUID,
    model_id: UUID,
    revision_number: int,
    session: SessionDep,
) -> InitialConditionsAliasMappingDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    dataset = _require_initial_conditions_dataset(session, subproject_id, dataset_id)
    _require_model(session, subproject_id, model_id)
    revision = get_mapping_revision(
        session,
        initial_conditions_dataset_id=dataset_id,
        model_id=model_id,
        revision_number=revision_number,
    )
    if revision is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No alias-mapping revision {revision_number} exists for dataset {dataset_id} "
            f"and model {model_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return InitialConditionsAliasMappingDetail.build(
        dataset=dataset,
        model_id=model_id,
        species_catalog=revision.model_species_catalog,
        parameter_catalog=revision.model_parameter_catalog,
        revision=revision,
    )


__all__ = ["router"]
