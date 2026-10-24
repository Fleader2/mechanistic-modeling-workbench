"""Whole-Model Antimony Import increment: upload an already-written Antimony text file
directly, preview its compilation/fidelity findings, then explicitly save it as a new,
independent, ``IMPORTED`` whole-model version -- bypassing the Agent1->Agent2 build pipeline
entirely. See ``docs/34_whole_model_antimony_import_increment.md``.

Mirrors the time-series-dataset preview/save split exactly: preview never persists anything;
save re-verifies the supplied text itself, never trusting a client-side echo of an earlier
preview. Calibration (fitting) execution is untouched and stays unavailable regardless --
nothing here is scenario evaluation or calibration, both of which an imported model already
reaches, unmodified, through the existing routes once its species/parameter catalog exists.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.deps import SessionDep
from app.api.errors import ApiError
from app.api.v1.routes.projects import _require_model, _require_modeling_study, _require_project
from app.orchestration.model_antimony_import_orchestrator import (
    AntimonyImportHarnessUnavailableError,
    AntimonyImportVerificationFailedError,
    preview_antimony_import,
    save_antimony_import,
)
from app.persistence.model_import_provenance import get_model_import_provenance
from app.persistence.model_species_catalog import get_model_species_catalog
from app.schemas.common import ErrorCode
from app.schemas.model import ModelDetail
from app.schemas.model_antimony_import import (
    AntimonyImportPreviewResponse,
    AntimonySourceResponse,
    ModelImportProvenanceItem,
)
from app.storage import read_artifact

router = APIRouter(prefix="/projects", tags=["model-antimony-import"])


@router.post(
    "/{project_id}/subprojects/{subproject_id}/models/antimony-import/preview",
    response_model=AntimonyImportPreviewResponse,
    summary="Preview an uploaded Antimony file's compilation and fidelity findings",
    description=(
        "Parses and real-compiles the uploaded Antimony text (through the real executability "
        "check and Agent 2's own import fidelity audit) and returns everything it would "
        "import, without writing anything to the database. A malformed/unreadable upload is "
        "still a 200 with load_succeeded=false -- compilation failure is a real, disclosed "
        "outcome here, never a 422 or 500 (never a substantive file read failure, though -- "
        "an empty or non-UTF-8 file is a 422)."
    ),
)
async def preview_model_antimony_import(
    project_id: UUID,
    subproject_id: UUID,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
) -> AntimonyImportPreviewResponse:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    antimony_text = await _read_antimony_text(file)
    try:
        preview = preview_antimony_import(antimony_text)
    except AntimonyImportHarnessUnavailableError as exc:
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            "Could not reach the integration harness to preview this upload.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            context={"detail": str(exc)},
        ) from exc
    return AntimonyImportPreviewResponse.from_preview(preview)


@router.post(
    "/{project_id}/subprojects/{subproject_id}/models/antimony-import",
    response_model=ModelDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Save an uploaded Antimony file as a new, independent imported model",
    description=(
        "Re-verifies the uploaded text itself -- never trusts a client-side echo of an "
        "earlier preview -- then atomically persists a new Model row (source_type=IMPORTED), "
        "its species/parameter/compartment catalog, and an immutable import-provenance "
        "record. A 422 if the text does not compile/load (never creates a Model row in that "
        "case -- a failure never leaves a model falsely marked ready). Re-uploading byte-"
        "identical text always creates a new, independent model -- never silently merged with "
        "an earlier one."
    ),
)
async def save_model_antimony_import(
    project_id: UUID,
    subproject_id: UUID,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()],
    source_reference: Annotated[str | None, Form()] = None,
    verification_notes: Annotated[str | None, Form()] = None,
    created_by: Annotated[str | None, Form()] = None,
) -> ModelDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    if not name or not name.strip():
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "A model name is required.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    antimony_text = await _read_antimony_text(file)
    try:
        model = save_antimony_import(
            session,
            subproject_id=subproject_id,
            model_name=name.strip(),
            antimony_text=antimony_text,
            original_filename=file.filename or "untitled.antimony",
            source_reference=source_reference,
            verification_notes=verification_notes,
            created_by=created_by,
        )
    except AntimonyImportVerificationFailedError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "This Antimony file could not be imported.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context={"detail": exc.message},
        ) from exc
    except AntimonyImportHarnessUnavailableError as exc:
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            "Could not reach the integration harness to import this upload.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            context={"detail": str(exc)},
        ) from exc
    return ModelDetail.model_validate(model)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/models/{model_id}/antimony-source",
    response_model=AntimonySourceResponse,
    summary="The read-only Antimony source text for one model's own pinned, verified artifact",
    description=(
        "Any model with a captured species catalog (imported or built) -- read back exactly "
        "as saved, never re-derived. A 404 for an unknown model, or one with no captured "
        "species catalog at all (nothing to show)."
    ),
)
def get_model_antimony_source(
    project_id: UUID, subproject_id: UUID, model_id: UUID, session: SessionDep
) -> AntimonySourceResponse:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    _require_model(session, subproject_id, model_id)
    catalog = get_model_species_catalog(session, model_id)
    if catalog is None or not catalog.source_antimony_artifact_reference:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No Antimony source is available for model {model_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    antimony_text = read_artifact(catalog.source_antimony_artifact_reference).decode("utf-8")
    return AntimonySourceResponse(antimony_text=antimony_text)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/models/{model_id}/import-provenance",
    response_model=ModelImportProvenanceItem | None,
    summary="One imported model's own upload provenance and fidelity-audit findings",
    description=(
        "``null`` for a model that was not imported through this increment's own upload path "
        "(a GENERATED/DERIVED model, or one imported before this table existed) -- never "
        "fabricated. A 404 for an unknown model."
    ),
)
def get_model_import_provenance_route(
    project_id: UUID, subproject_id: UUID, model_id: UUID, session: SessionDep
) -> ModelImportProvenanceItem | None:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    _require_model(session, subproject_id, model_id)
    provenance = get_model_import_provenance(session, model_id)
    return None if provenance is None else ModelImportProvenanceItem.from_model(provenance)


async def _read_antimony_text(file: UploadFile) -> str:
    data = await file.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "This file is not valid UTF-8 text.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc


__all__ = ["router"]
