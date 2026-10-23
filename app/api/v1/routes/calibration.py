"""Joint Calibration Workflow, configuration-only increment: routes for the "Models &
experimental data" / "Variables, parameters & experimental settings" / "Review & readiness"
screens (``docs/29_joint_calibration_workflow_design.md``, ``docs/30
_joint_calibration_configuration_increment.md``).

No route here ever submits, runs, or simulates anything -- there is no execution capability to
call yet (docs/29 §6). Every mutating route returns the whole, freshly-reloaded
``CalibrationJobDetail`` so the frontend always has the job's current ``edit_version`` without
a second round trip.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import SessionDep
from app.api.errors import ApiError
from app.api.v1.routes.projects import _require_model, _require_modeling_study, _require_project
from app.persistence.calibration import (
    CalibrationJobStaleEdit,
    CalibrationReviewBlocked,
    ReferencedArmNotRemovable,
    add_arm,
    add_experiment,
    add_parameter_role,
    add_variable_binding,
    complete_review,
    compute_findings,
    create_job,
    execution_capability,
    get_job_for_subproject,
    get_job_revision,
    list_job_revisions,
    list_jobs_for_subproject,
    remove_arm,
    remove_experiment,
    remove_experiment_output_weighting,
    remove_parameter_role,
    remove_variable_binding,
    set_experiment_mapping,
    set_experiment_objective_weighting,
    set_experiment_output_weighting,
    set_experiment_role,
)
from app.persistence.model_relationship import (
    declare_model_relationship,
    list_model_relationships_for_models,
)
from app.schemas.calibration import (
    AddArmRequest,
    AddExperimentRequest,
    AddParameterRoleRequest,
    AddVariableBindingRequest,
    CalibrationJobDetail,
    CalibrationJobRevisionDetail,
    CalibrationJobRevisionSummary,
    CalibrationJobSummary,
    CalibrationReviewResult,
    CompleteReviewRequest,
    CreateCalibrationJobRequest,
    DeclareModelRelationshipRequest,
    ExecutionCapabilityItem,
    FindingItem,
    ModelRelationshipItem,
    SetExperimentMappingRequest,
    SetExperimentObjectiveWeightingRequest,
    SetExperimentOutputWeightingRequest,
    SetExperimentRoleRequest,
)
from app.schemas.common import ErrorCode

router = APIRouter(prefix="/projects", tags=["calibration"])


def _require_job(session: SessionDep, subproject_id: UUID, job_id: UUID):
    job = get_job_for_subproject(session, subproject_id, job_id)
    if job is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No calibration job exists with id {job_id} in Modeling Study {subproject_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return job


def _stale(exc: CalibrationJobStaleEdit) -> ApiError:
    return ApiError(
        ErrorCode.CONFLICT,
        "This calibration job was edited since you last loaded it.",
        status_code=status.HTTP_409_CONFLICT,
        context={"current_edit_version": exc.job.edit_version},
    )


@router.post(
    "/{project_id}/subprojects/{subproject_id}/model-relationships",
    response_model=ModelRelationshipItem,
    status_code=status.HTTP_201_CREATED,
    summary="Declare a relationship between two model versions",
    description=(
        "Insert-only -- never edits or supersedes an earlier declaration. A 422 for either "
        "model id not belonging to this Modeling Study, or for declaring a model related to "
        "itself."
    ),
)
def declare_model_relationship_route(
    project_id: UUID,
    subproject_id: UUID,
    body: DeclareModelRelationshipRequest,
    session: SessionDep,
) -> ModelRelationshipItem:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    _require_model(session, subproject_id, body.model_id_a)
    _require_model(session, subproject_id, body.model_id_b)
    try:
        relationship = declare_model_relationship(
            session,
            model_id_a=body.model_id_a,
            model_id_b=body.model_id_b,
            relationship_kind=body.relationship_kind,
            role_label_a=body.role_label_a,
            role_label_b=body.role_label_b,
            declared_by=body.declared_by,
        )
    except ValueError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, str(exc), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    session.commit()
    return ModelRelationshipItem.from_model(relationship)


@router.post(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs",
    response_model=CalibrationJobDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new, empty calibration-job draft",
)
def create_calibration_job(
    project_id: UUID,
    subproject_id: UUID,
    body: CreateCalibrationJobRequest,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = create_job(session, subproject_id=subproject_id, created_by=body.created_by)
    session.commit()
    job = _require_job(session, subproject_id, job.id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs",
    response_model=list[CalibrationJobSummary],
    summary="List one Modeling Study's calibration jobs",
)
def list_calibration_jobs(
    project_id: UUID, subproject_id: UUID, session: SessionDep
) -> list[CalibrationJobSummary]:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    jobs = list_jobs_for_subproject(session, subproject_id)
    return [CalibrationJobSummary.from_model(job) for job in jobs]


@router.get(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}",
    response_model=CalibrationJobDetail,
    summary="Reopen one calibration job",
)
def get_calibration_job(
    project_id: UUID, subproject_id: UUID, job_id: UUID, session: SessionDep
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/model-relationships",
    response_model=list[ModelRelationshipItem],
    summary="Every declared relationship touching one of this job's own arms' models",
    description=(
        "Screen 1's own 'show model-relationship controls only when relevant' gate: an empty "
        "list means this job's models have no declared relationship, and the section is "
        "structurally absent, not collapsed."
    ),
)
def list_job_model_relationships(
    project_id: UUID, subproject_id: UUID, job_id: UUID, session: SessionDep
) -> list[ModelRelationshipItem]:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    model_ids = {arm.model_id for arm in job.arms}
    relationships = list_model_relationships_for_models(session, model_ids)
    return [ModelRelationshipItem.from_model(r) for r in relationships]


@router.post(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/arms",
    response_model=CalibrationJobDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add one whole-model-version arm to a calibration job",
    description=(
        "Always a Model, never a ModelModule (docs/29 §6). A 409 if expected_edit_version is "
        "stale; a 422 for a model_id not belonging to this Modeling Study."
    ),
)
def add_calibration_arm(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    body: AddArmRequest,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    _require_model(session, subproject_id, body.model_id)
    try:
        add_arm(
            session,
            job=job,
            model_id=body.model_id,
            role_label=body.role_label,
            expected_edit_version=body.expected_edit_version,
            updated_by=body.updated_by,
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.delete(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/arms/{arm_id}",
    response_model=CalibrationJobDetail,
    summary="Remove one arm from a calibration job",
    description=(
        "A 409 if expected_edit_version is stale, or a parameter-role link still references "
        "this arm (remove or repoint that first)."
    ),
)
def remove_calibration_arm(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    arm_id: UUID,
    expected_edit_version: int,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        remove_arm(session, job=job, arm_id=arm_id, expected_edit_version=expected_edit_version)
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except ReferencedArmNotRemovable as exc:
        raise ApiError(ErrorCode.CONFLICT, str(exc), status_code=status.HTTP_409_CONFLICT) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, str(exc), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.post(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/arms/{arm_id}/experiments",
    response_model=CalibrationJobDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Assign one dataset to an arm as a new experiment",
    description=(
        "If a current alias-mapping revision already exists for (dataset, arm's model), it is "
        "pinned automatically -- still visible and editable on Screen 2, never hidden."
    ),
)
def add_calibration_experiment(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    arm_id: UUID,
    body: AddExperimentRequest,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    arm = next((a for a in job.arms if a.id == arm_id), None)
    if arm is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No arm exists with id {arm_id} in calibration job {job_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    try:
        add_experiment(
            session,
            job=job,
            arm=arm,
            time_series_dataset_id=body.time_series_dataset_id,
            role=body.role,
            expected_edit_version=body.expected_edit_version,
            updated_by=body.updated_by,
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.delete(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/experiments/{experiment_id}",
    response_model=CalibrationJobDetail,
    summary="Remove one experiment from a calibration job",
)
def remove_calibration_experiment(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    experiment_id: UUID,
    expected_edit_version: int,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        remove_experiment(
            session,
            job=job,
            experiment_id=experiment_id,
            expected_edit_version=expected_edit_version,
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.NOT_FOUND, str(exc), status_code=status.HTTP_404_NOT_FOUND
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.patch(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/experiments/{experiment_id}/mapping",
    response_model=CalibrationJobDetail,
    summary="Re-pin (or clear) one experiment's own alias-mapping revision",
    description="Always an explicit scientist action -- a re-saved mapping is never auto-repinned.",
)
def set_calibration_experiment_mapping(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    experiment_id: UUID,
    body: SetExperimentMappingRequest,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        set_experiment_mapping(
            session,
            job=job,
            experiment_id=experiment_id,
            alias_mapping_revision_number=body.alias_mapping_revision_number,
            expected_edit_version=body.expected_edit_version,
            updated_by=body.updated_by,
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, str(exc), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.patch(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/experiments/{experiment_id}/role",
    response_model=CalibrationJobDetail,
    summary="Designate one experiment as calibration or held-out validation evidence",
)
def set_calibration_experiment_role(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    experiment_id: UUID,
    body: SetExperimentRoleRequest,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        set_experiment_role(
            session,
            job=job,
            experiment_id=experiment_id,
            role=body.role,
            expected_edit_version=body.expected_edit_version,
            updated_by=body.updated_by,
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.NOT_FOUND, str(exc), status_code=status.HTTP_404_NOT_FOUND
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.patch(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/experiments/{experiment_id}"
    "/objective-weighting",
    response_model=CalibrationJobDetail,
    summary="Declare one experiment's own objective weighting / error assumption",
)
def set_calibration_experiment_objective_weighting(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    experiment_id: UUID,
    body: SetExperimentObjectiveWeightingRequest,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        set_experiment_objective_weighting(
            session,
            job=job,
            experiment_id=experiment_id,
            objective_weighting=body.objective_weighting,
            weighting_notes=body.weighting_notes,
            expected_edit_version=body.expected_edit_version,
            updated_by=body.updated_by,
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.NOT_FOUND, str(exc), status_code=status.HTTP_404_NOT_FOUND
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.put(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/experiments/{experiment_id}"
    "/output-weightings",
    response_model=CalibrationJobDetail,
    summary="Declare (or replace) one output's own uncertainty source and relative weight",
    description=(
        "Upsert on (experiment, output_column_name) -- docs/32's minimal error/weighting "
        "contract. output_column_name is validated against the experiment's own pinned "
        "dataset's real measurement columns; uncertainty_source=MEASURED additionally "
        "requires the dataset to declare a matching measurement-uncertainty column; "
        "uncertainty_source=USER_ASSUMED requires a strictly positive, finite "
        "assumed_sigma_value plus assumed_sigma_statistic_kind (standard deviation / variance "
        "/ standard error -- never left implicit), unit-checked against the output's own "
        "declared unit when both are present. A 422 for any of these, a conflicting "
        "combination of source and sigma fields, or a non-positive/non-finite "
        "relative_output_weight."
    ),
)
def set_calibration_experiment_output_weighting(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    experiment_id: UUID,
    body: SetExperimentOutputWeightingRequest,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        set_experiment_output_weighting(
            session,
            job=job,
            experiment_id=experiment_id,
            output_column_name=body.output_column_name,
            uncertainty_source=body.uncertainty_source,
            assumed_sigma_value=body.assumed_sigma_value,
            assumed_sigma_unit=body.assumed_sigma_unit,
            assumed_sigma_statistic_kind=body.assumed_sigma_statistic_kind,
            relative_output_weight=body.relative_output_weight,
            provenance_note=body.provenance_note,
            expected_edit_version=body.expected_edit_version,
            updated_by=body.updated_by,
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, str(exc), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.delete(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/output-weightings"
    "/{weighting_id}",
    response_model=CalibrationJobDetail,
    summary="Remove one declared output weighting",
)
def remove_calibration_experiment_output_weighting(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    weighting_id: UUID,
    expected_edit_version: int,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        remove_experiment_output_weighting(
            session,
            job=job,
            weighting_id=weighting_id,
            expected_edit_version=expected_edit_version,
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.NOT_FOUND, str(exc), status_code=status.HTTP_404_NOT_FOUND
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.post(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/experiments/{experiment_id}"
    "/variable-bindings",
    response_model=CalibrationJobDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add one independent-variable binding to an experiment",
    description=(
        "Every binding states its own explicit model meaning (INITIAL_VALUE/"
        "PARAMETER_OVERRIDE/INTERVENTION, docs/31) -- target_component_id is validated "
        "server-side against whichever of the model's own species/parameter catalog is "
        "relevant and actually AVAILABLE; a 422 for a name confirmed absent, or confirmed a "
        "DERIVED (assignment-rule) parameter, which is never an independent target. "
        "value_source=DATASET_COLUMN additionally requires source_column_name to name a real, "
        "declared independent-variable column of this experiment's own pinned dataset."
    ),
)
def add_calibration_variable_binding(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    experiment_id: UUID,
    body: AddVariableBindingRequest,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        add_variable_binding(
            session,
            job=job,
            experiment_id=experiment_id,
            model_meaning=body.model_meaning,
            target_component_id=body.target_component_id,
            value_source=body.value_source,
            constant_value=body.constant_value,
            constant_unit=body.constant_unit,
            source_column_name=body.source_column_name,
            source=body.source,
            expected_edit_version=body.expected_edit_version,
            updated_by=body.updated_by,
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, str(exc), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.delete(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/variable-bindings/{binding_id}",
    response_model=CalibrationJobDetail,
    summary="Remove one independent-variable binding",
)
def remove_calibration_variable_binding(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    binding_id: UUID,
    expected_edit_version: int,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        remove_variable_binding(
            session, job=job, binding_id=binding_id, expected_edit_version=expected_edit_version
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.NOT_FOUND, str(exc), status_code=status.HTTP_404_NOT_FOUND
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.post(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/parameter-roles",
    response_model=CalibrationJobDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Declare one parameter's role across a calibration job",
    description=(
        "Collected even for a one-arm job (MODEL_SPECIFIC/FIXED with bounds); the cross-arm "
        "EXACT_EQUALITY/EXACT_AFFINE_LINK/SOFT_PRIOR_LINK roles only matter once a job has two "
        "or more arms (docs/29 §5/§7). parameter_name is validated server-side against each "
        "covering arm's own ModelParameterCatalog whenever that catalog is AVAILABLE (docs/31) "
        "-- a 422 for a name confirmed absent or confirmed a DERIVED parameter; curator-"
        "declared and disclosed as unvalidated only when no catalog exists yet."
    ),
)
def add_calibration_parameter_role(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    body: AddParameterRoleRequest,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        add_parameter_role(
            session,
            job=job,
            parameter_name=body.parameter_name,
            role=body.role,
            arm_ids=body.arm_ids,
            fixed_value=body.fixed_value,
            lower_bound=body.lower_bound,
            upper_bound=body.upper_bound,
            unit=body.unit,
            reference_arm_id=body.reference_arm_id,
            reference_parameter_name=body.reference_parameter_name,
            coefficient_a=body.coefficient_a,
            coefficient_a_is_fixed=body.coefficient_a_is_fixed,
            coefficient_b=body.coefficient_b,
            coefficient_b_is_fixed=body.coefficient_b_is_fixed,
            expected_edit_version=body.expected_edit_version,
            updated_by=body.updated_by,
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, str(exc), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.delete(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/parameter-roles/{role_id}",
    response_model=CalibrationJobDetail,
    summary="Remove one parameter role",
)
def remove_calibration_parameter_role(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    role_id: UUID,
    expected_edit_version: int,
    session: SessionDep,
) -> CalibrationJobDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        remove_parameter_role(
            session, job=job, parameter_role_id=role_id, expected_edit_version=expected_edit_version
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except ValueError as exc:
        raise ApiError(
            ErrorCode.NOT_FOUND, str(exc), status_code=status.HTTP_404_NOT_FOUND
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationJobDetail.from_model(job, session=session)


@router.get(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/review",
    response_model=CalibrationReviewResult,
    summary="Preview Screen 3 -- every finding, computed fresh, and the execution-capability check",
    description=(
        "Read-only and always callable, at any edit_version -- never mutates the job. "
        "Configuration-completeness findings and the execution-capability check are reported "
        "separately and never conflated: a single model, fully and correctly configured, is "
        "reported complete but still not execution-ready (docs/29 §5 rule 5)."
    ),
)
def preview_calibration_review(
    project_id: UUID, subproject_id: UUID, job_id: UUID, session: SessionDep
) -> CalibrationReviewResult:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    findings = compute_findings(job)
    return CalibrationReviewResult(
        job=CalibrationJobDetail.from_model(job, session=session),
        findings=[FindingItem.from_finding(f) for f in findings],
        execution_capability=ExecutionCapabilityItem.from_capability(execution_capability(job)),
    )


@router.post(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/complete-review",
    response_model=CalibrationReviewResult,
    summary="Complete review -- requires zero blocking (ERROR) findings",
    description=(
        "A 409 if expected_edit_version is stale; a 422 (never silently rejected with no "
        "detail) if at least one ERROR-severity finding still exists, with every finding in "
        "the error context. Succeeding never means the job is executable -- see "
        "execution_capability in the response, always unavailable in this increment."
    ),
)
def complete_calibration_review(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    body: CompleteReviewRequest,
    session: SessionDep,
) -> CalibrationReviewResult:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    job = _require_job(session, subproject_id, job_id)
    try:
        job, findings, _revision = complete_review(
            session,
            job=job,
            expected_edit_version=body.expected_edit_version,
            updated_by=body.updated_by,
        )
    except CalibrationJobStaleEdit as exc:
        raise _stale(exc) from exc
    except CalibrationReviewBlocked as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "This job cannot complete review while it has unresolved blocking findings.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context={
                "findings": [
                    FindingItem.from_finding(f).model_dump(mode="json") for f in exc.findings
                ]
            },
        ) from exc
    session.commit()
    job = _require_job(session, subproject_id, job_id)
    return CalibrationReviewResult(
        job=CalibrationJobDetail.from_model(job, session=session),
        findings=[FindingItem.from_finding(f) for f in findings],
        execution_capability=ExecutionCapabilityItem.from_capability(execution_capability(job)),
    )


@router.get(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/revisions",
    response_model=list[CalibrationJobRevisionSummary],
    summary="Every immutable revision ever captured for one calibration job",
    description=(
        "Newest first. Each revision is captured only by a successful 'Complete review' "
        "(docs/31) -- a later draft edit never changes an earlier one; it only ever adds a "
        "new revision the next time review completes."
    ),
)
def list_calibration_job_revisions(
    project_id: UUID, subproject_id: UUID, job_id: UUID, session: SessionDep
) -> list[CalibrationJobRevisionSummary]:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    _require_job(session, subproject_id, job_id)
    revisions = list_job_revisions(session, job_id)
    return [CalibrationJobRevisionSummary.from_model(r) for r in revisions]


@router.get(
    "/{project_id}/subprojects/{subproject_id}/calibration-jobs/{job_id}/revisions/{revision_number}",
    response_model=CalibrationJobRevisionDetail,
    summary="Reopen one specific, historical calibration-job revision -- read-only",
    description=(
        "Exactly as captured at review-completion time, never re-derived against the job's "
        "own current (possibly since-edited) state. A 404 for an unknown job/revision number."
    ),
)
def get_calibration_job_revision(
    project_id: UUID,
    subproject_id: UUID,
    job_id: UUID,
    revision_number: int,
    session: SessionDep,
) -> CalibrationJobRevisionDetail:
    _require_project(session, project_id)
    _require_modeling_study(session, project_id, subproject_id)
    _require_job(session, subproject_id, job_id)
    revision = get_job_revision(session, job_id, revision_number)
    if revision is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No revision {revision_number} exists for calibration job {job_id}.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return CalibrationJobRevisionDetail.from_model(revision)
