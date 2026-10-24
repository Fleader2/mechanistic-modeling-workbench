"""Request/response schemas for the Joint Calibration Workflow configuration-only increment.

See ``docs/29_joint_calibration_workflow_design.md`` and ``docs/30
_joint_calibration_configuration_increment.md``/``docs/31
_joint_calibration_configuration_prerequisites_increment.md``.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.calibration import (
    CalibrationArm,
    CalibrationExperiment,
    CalibrationExperimentOutputWeighting,
    CalibrationExperimentVariableBinding,
    CalibrationJob,
    CalibrationJobRevision,
    CalibrationParameterRole,
)
from app.models.enums import (
    CalibrationBindingModelMeaning,
    CalibrationBindingValueSource,
    CalibrationExperimentRole,
    CalibrationFindingCategory,
    CalibrationFindingSeverity,
    CalibrationJobStatus,
    CalibrationObjectiveWeighting,
    CalibrationParameterRoleKind,
    CalibrationUncertaintySource,
    ModelRelationshipKind,
    UncertaintyStatisticKind,
)
from app.models.model_relationship import ModelRelationship
from app.persistence.calibration import CalibrationFinding, ExecutionCapability
from app.persistence.dataset_model_alias_mapping import get_current_mapping_revision
from app.persistence.initial_conditions_alias_mapping import (
    get_current_mapping_revision as get_current_ic_mapping_revision,
)


class VariableBindingItem(BaseModel):
    id: UUID
    model_meaning: CalibrationBindingModelMeaning
    target_component_id: str
    value_source: CalibrationBindingValueSource
    constant_value: Decimal | None
    constant_unit: str | None
    source_column_name: str | None
    source: str | None
    #: Required (non-``None``) if and only if ``model_meaning=INTERVENTION`` (docs/33).
    intervention_time: Decimal | None

    @classmethod
    def from_model(cls, binding: CalibrationExperimentVariableBinding) -> VariableBindingItem:
        return cls(
            id=binding.id,
            model_meaning=binding.model_meaning,
            target_component_id=binding.target_component_id,
            value_source=binding.value_source,
            constant_value=binding.constant_value,
            constant_unit=binding.constant_unit,
            source_column_name=binding.source_column_name,
            source=binding.source,
            intervention_time=binding.intervention_time,
        )


class OutputWeightingItem(BaseModel):
    """One output's own declared uncertainty source and relative weight (``docs/32``'s minimal
    error/weighting contract) -- see ``app.models.calibration
    .CalibrationExperimentOutputWeighting`` for the objective this configures."""

    id: UUID
    output_column_name: str
    uncertainty_source: CalibrationUncertaintySource
    assumed_sigma_value: Decimal | None
    assumed_sigma_unit: str | None
    #: Set only for ``USER_ASSUMED`` -- the curator's own declared statistic (standard
    #: deviation / variance / standard error).
    assumed_sigma_statistic_kind: UncertaintyStatisticKind | None
    #: The statistic this output's uncertainty value actually *is*, resolved for display
    #: regardless of source: for ``USER_ASSUMED`` this mirrors ``assumed_sigma_statistic_kind``;
    #: for ``MEASURED`` it is looked up from the dataset's own declared
    #: ``TimeSeriesMeasurementUncertaintyColumn.statistic_kind`` (never duplicated in this row
    #: -- see ``app.models.calibration.CalibrationExperimentOutputWeighting``); ``None`` for
    #: ``UNKNOWN``.
    effective_statistic_kind: UncertaintyStatisticKind | None
    relative_output_weight: Decimal
    provenance_note: str | None

    @classmethod
    def from_model(
        cls, weighting: CalibrationExperimentOutputWeighting, *, dataset
    ) -> OutputWeightingItem:
        if weighting.uncertainty_source is CalibrationUncertaintySource.MEASURED:
            effective_statistic_kind = next(
                (
                    c.statistic_kind
                    for c in dataset.measurement_uncertainty_columns
                    if c.measurement_column_name == weighting.output_column_name
                ),
                None,
            )
        else:
            effective_statistic_kind = weighting.assumed_sigma_statistic_kind
        return cls(
            id=weighting.id,
            output_column_name=weighting.output_column_name,
            uncertainty_source=weighting.uncertainty_source,
            assumed_sigma_value=weighting.assumed_sigma_value,
            assumed_sigma_unit=weighting.assumed_sigma_unit,
            assumed_sigma_statistic_kind=weighting.assumed_sigma_statistic_kind,
            effective_statistic_kind=effective_statistic_kind,
            relative_output_weight=weighting.relative_output_weight,
            provenance_note=weighting.provenance_note,
        )


class ExperimentItem(BaseModel):
    id: UUID
    time_series_dataset_id: UUID
    dataset_name: str
    role: CalibrationExperimentRole
    objective_weighting: CalibrationObjectiveWeighting
    weighting_notes: str | None
    alias_mapping_revision_id: UUID | None
    alias_mapping_revision_number: int | None
    #: ``True`` when a newer alias-mapping revision now exists than the one this experiment is
    #: pinned to -- computed fresh at read time, never stored (docs/29 §7's "revalidation,
    #: never deletion" table).
    mapping_is_stale: bool
    variable_bindings: list[VariableBindingItem]
    #: Every independent-variable column this experiment's own pinned dataset has declared --
    #: what a ``value_source=DATASET_COLUMN`` binding may legally name (docs/31).
    available_dataset_columns: list[str]
    #: Every output (measurement column) this experiment's own pinned dataset actually has --
    #: what ``output_column_name`` may legally name when declaring a weighting (docs/32).
    available_output_columns: list[str]
    #: The subset of ``available_output_columns`` for which the dataset itself declares a real
    #: measurement-uncertainty column -- i.e. where ``uncertainty_source=MEASURED`` is actually
    #: legal (docs/32).
    outputs_with_measured_uncertainty: list[str]
    output_weightings: list[OutputWeightingItem]
    #: Initial-Conditions Dataset Import increment (docs/36): this experiment's own optionally-
    #: pinned initial-conditions dataset -- entirely separate from ``time_series_dataset_id``
    #: (the calibration *target* data). ``None`` unless a scientist has pinned one.
    initial_conditions_dataset_id: UUID | None
    initial_conditions_dataset_name: str | None
    initial_conditions_alias_mapping_revision_id: UUID | None
    initial_conditions_alias_mapping_revision_number: int | None
    #: Mirrors ``mapping_is_stale``, one level down.
    initial_conditions_mapping_is_stale: bool
    #: Every measurement column of this experiment's own pinned initial-conditions dataset --
    #: what a ``value_source=INITIAL_CONDITIONS_DATASET`` binding may legally name
    #: (``source_column_name``). Empty if no initial-conditions dataset is pinned.
    available_initial_conditions_columns: list[str]

    @classmethod
    def from_model(cls, experiment: CalibrationExperiment, *, session) -> ExperimentItem:
        dataset = experiment.time_series_dataset
        current_revision = get_current_mapping_revision(
            session,
            time_series_dataset_id=experiment.time_series_dataset_id,
            model_id=experiment.arm.model_id,
        )
        pinned_revision_number = (
            experiment.alias_mapping_revision.revision_number
            if experiment.alias_mapping_revision is not None
            else None
        )
        current_revision_number = (
            current_revision.revision_number if current_revision is not None else None
        )

        ic_dataset = experiment.initial_conditions_dataset
        ic_pinned_revision_number = (
            experiment.initial_conditions_alias_mapping_revision.revision_number
            if experiment.initial_conditions_alias_mapping_revision is not None
            else None
        )
        ic_current_revision_number = None
        if ic_dataset is not None:
            ic_current_revision = get_current_ic_mapping_revision(
                session,
                initial_conditions_dataset_id=experiment.initial_conditions_dataset_id,
                model_id=experiment.arm.model_id,
            )
            ic_current_revision_number = (
                ic_current_revision.revision_number if ic_current_revision is not None else None
            )

        return cls(
            id=experiment.id,
            time_series_dataset_id=experiment.time_series_dataset_id,
            dataset_name=dataset.dataset_name or dataset.dataset_reference.name,
            role=experiment.role,
            objective_weighting=experiment.objective_weighting,
            weighting_notes=experiment.weighting_notes,
            alias_mapping_revision_id=experiment.alias_mapping_revision_id,
            alias_mapping_revision_number=pinned_revision_number,
            mapping_is_stale=(
                experiment.alias_mapping_revision_id is not None
                and pinned_revision_number != current_revision_number
            ),
            variable_bindings=[
                VariableBindingItem.from_model(b) for b in experiment.variable_bindings
            ],
            available_dataset_columns=[
                c.column_name for c in dataset.independent_variable_columns
            ],
            available_output_columns=[c.column_name for c in dataset.measurement_columns],
            outputs_with_measured_uncertainty=[
                c.measurement_column_name for c in dataset.measurement_uncertainty_columns
            ],
            output_weightings=[
                OutputWeightingItem.from_model(w, dataset=dataset)
                for w in experiment.output_weightings
            ],
            initial_conditions_dataset_id=experiment.initial_conditions_dataset_id,
            initial_conditions_dataset_name=(
                None
                if ic_dataset is None
                else (ic_dataset.dataset_name or ic_dataset.dataset_reference.name)
            ),
            initial_conditions_alias_mapping_revision_id=(
                experiment.initial_conditions_alias_mapping_revision_id
            ),
            initial_conditions_alias_mapping_revision_number=ic_pinned_revision_number,
            initial_conditions_mapping_is_stale=(
                experiment.initial_conditions_alias_mapping_revision_id is not None
                and ic_pinned_revision_number != ic_current_revision_number
            ),
            available_initial_conditions_columns=(
                []
                if ic_dataset is None
                else [c.column_name for c in ic_dataset.measurement_columns]
            ),
        )


class ArmItem(BaseModel):
    id: UUID
    model_id: UUID
    model_name: str
    role_label: str | None
    sequence_index: int
    experiments: list[ExperimentItem]

    @classmethod
    def from_model(cls, arm: CalibrationArm, *, session) -> ArmItem:
        return cls(
            id=arm.id,
            model_id=arm.model_id,
            model_name=arm.model.name,
            role_label=arm.role_label,
            sequence_index=arm.sequence_index,
            experiments=[ExperimentItem.from_model(e, session=session) for e in arm.experiments],
        )


class ParameterRoleItem(BaseModel):
    id: UUID
    parameter_name: str
    role: CalibrationParameterRoleKind
    #: Whether ``parameter_name`` (and, for a link role, ``reference_parameter_name``) was
    #: actually confirmed against a real, ``AVAILABLE`` ``ModelParameterCatalog`` at
    #: declaration time (docs/31) -- ``False`` only when no such catalog existed yet for the
    #: relevant model(s); never re-evaluated against a catalog captured later.
    catalog_validated: bool
    fixed_value: Decimal | None
    lower_bound: Decimal | None
    upper_bound: Decimal | None
    unit: str | None
    reference_arm_id: UUID | None
    reference_parameter_name: str | None
    coefficient_a: Decimal | None
    coefficient_a_is_fixed: bool
    coefficient_b: Decimal | None
    coefficient_b_is_fixed: bool
    arm_ids: list[UUID]

    @classmethod
    def from_model(cls, role: CalibrationParameterRole) -> ParameterRoleItem:
        return cls(
            id=role.id,
            parameter_name=role.parameter_name,
            role=role.role,
            catalog_validated=role.catalog_validated,
            fixed_value=role.fixed_value,
            lower_bound=role.lower_bound,
            upper_bound=role.upper_bound,
            unit=role.unit,
            reference_arm_id=role.reference_arm_id,
            reference_parameter_name=role.reference_parameter_name,
            coefficient_a=role.coefficient_a,
            coefficient_a_is_fixed=role.coefficient_a_is_fixed,
            coefficient_b=role.coefficient_b,
            coefficient_b_is_fixed=role.coefficient_b_is_fixed,
            arm_ids=[link.calibration_arm_id for link in role.arm_links],
        )


class CalibrationJobDetail(BaseModel):
    id: UUID
    subproject_id: UUID
    status: CalibrationJobStatus
    edit_version: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None
    reviewed_at: datetime | None
    arms: list[ArmItem]
    parameter_roles: list[ParameterRoleItem]

    @classmethod
    def from_model(cls, job: CalibrationJob, *, session) -> CalibrationJobDetail:
        return cls(
            id=job.id,
            subproject_id=job.subproject_id,
            status=job.status,
            edit_version=job.edit_version,
            created_at=job.created_at,
            updated_at=job.updated_at,
            created_by=job.created_by,
            updated_by=job.updated_by,
            reviewed_at=job.reviewed_at,
            arms=[ArmItem.from_model(a, session=session) for a in job.arms],
            parameter_roles=[ParameterRoleItem.from_model(r) for r in job.parameter_roles],
        )


class CalibrationJobSummary(BaseModel):
    id: UUID
    status: CalibrationJobStatus
    arm_count: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None

    @classmethod
    def from_model(cls, job: CalibrationJob) -> CalibrationJobSummary:
        return cls(
            id=job.id,
            status=job.status,
            arm_count=len(job.arms),
            created_at=job.created_at,
            updated_at=job.updated_at,
            created_by=job.created_by,
        )


class FindingItem(BaseModel):
    severity: CalibrationFindingSeverity
    category: CalibrationFindingCategory
    message: str
    involved_arm_ids: list[UUID]
    involved_experiment_ids: list[UUID]
    involved_parameter_role_ids: list[UUID]

    @classmethod
    def from_finding(cls, finding: CalibrationFinding) -> FindingItem:
        return cls(
            severity=finding.severity,
            category=finding.category,
            message=finding.message,
            involved_arm_ids=finding.involved_arm_ids,
            involved_experiment_ids=finding.involved_experiment_ids,
            involved_parameter_role_ids=finding.involved_parameter_role_ids,
        )


class ExecutionCapabilityItem(BaseModel):
    available: bool
    reason: str | None
    missing_capability: Literal["WHOLE_MODEL_EXECUTION"] | None

    @classmethod
    def from_capability(cls, capability: ExecutionCapability) -> ExecutionCapabilityItem:
        return cls(
            available=capability.available,
            reason=capability.reason,
            missing_capability=capability.missing_capability,
        )


class CalibrationReviewResult(BaseModel):
    """Screen 3's own content -- configuration-completeness findings and the wholly separate
    execution-capability check, never conflated (docs/29 §5 rule 5)."""

    job: CalibrationJobDetail
    findings: list[FindingItem]
    execution_capability: ExecutionCapabilityItem


class CalibrationJobRevisionSummary(BaseModel):
    """One row of a job's own revision history (docs/31) -- mirrors
    ``AliasMappingRevisionSummary``'s own established shape."""

    revision_number: int
    created_at: datetime
    created_by: str | None
    arm_count: int
    finding_count: int

    @classmethod
    def from_model(cls, revision: CalibrationJobRevision) -> CalibrationJobRevisionSummary:
        payload = json.loads(revision.snapshot_payload)
        return cls(
            revision_number=revision.revision_number,
            created_at=revision.created_at,
            created_by=revision.created_by,
            arm_count=len(payload.get("arms", [])),
            finding_count=len(payload.get("findings_at_capture_time", [])),
        )


class CalibrationJobRevisionDetail(BaseModel):
    """One specific, historical revision, read back exactly as captured (docs/31) -- the raw
    snapshot payload, never re-derived against the job's own current (possibly since-changed)
    state."""

    revision_number: int
    created_at: datetime
    created_by: str | None
    snapshot: dict

    @classmethod
    def from_model(cls, revision: CalibrationJobRevision) -> CalibrationJobRevisionDetail:
        return cls(
            revision_number=revision.revision_number,
            created_at=revision.created_at,
            created_by=revision.created_by,
            snapshot=json.loads(revision.snapshot_payload),
        )


class ModelRelationshipItem(BaseModel):
    id: UUID
    model_id_a: UUID
    model_id_b: UUID
    relationship_kind: ModelRelationshipKind
    role_label_a: str | None
    role_label_b: str | None
    declared_by: str | None
    declared_at: datetime

    @classmethod
    def from_model(cls, relationship: ModelRelationship) -> ModelRelationshipItem:
        return cls(
            id=relationship.id,
            model_id_a=relationship.model_id_a,
            model_id_b=relationship.model_id_b,
            relationship_kind=relationship.relationship_kind,
            role_label_a=relationship.role_label_a,
            role_label_b=relationship.role_label_b,
            declared_by=relationship.declared_by,
            declared_at=relationship.declared_at,
        )


# --- Requests --------------------------------------------------------------------------------


class CreateCalibrationJobRequest(BaseModel):
    created_by: str | None = None


class AddArmRequest(BaseModel):
    model_id: UUID
    role_label: str | None = None
    expected_edit_version: int
    updated_by: str | None = None


class AddExperimentRequest(BaseModel):
    time_series_dataset_id: UUID
    role: CalibrationExperimentRole = CalibrationExperimentRole.CALIBRATION
    expected_edit_version: int
    updated_by: str | None = None


class SetExperimentMappingRequest(BaseModel):
    #: Identified by ``revision_number`` -- the one identifier the alias-mapping API itself
    #: exposes (docs/27); ``None`` clears the pin.
    alias_mapping_revision_number: int | None
    expected_edit_version: int
    updated_by: str | None = None


class SetExperimentInitialConditionsDatasetRequest(BaseModel):
    """Initial-Conditions Dataset Import increment (docs/36). ``None`` clears the pin (and,
    per ``set_experiment_initial_conditions_dataset``, always clears any pinned mapping
    revision too)."""

    initial_conditions_dataset_id: UUID | None
    expected_edit_version: int
    updated_by: str | None = None


class SetExperimentInitialConditionsMappingRequest(BaseModel):
    #: Identified by ``revision_number``, mirroring ``SetExperimentMappingRequest`` exactly.
    alias_mapping_revision_number: int | None
    expected_edit_version: int
    updated_by: str | None = None


class SetExperimentRoleRequest(BaseModel):
    role: CalibrationExperimentRole
    expected_edit_version: int
    updated_by: str | None = None


class SetExperimentObjectiveWeightingRequest(BaseModel):
    objective_weighting: CalibrationObjectiveWeighting
    weighting_notes: str | None = None
    expected_edit_version: int
    updated_by: str | None = None


class SetExperimentOutputWeightingRequest(BaseModel):
    output_column_name: str
    uncertainty_source: CalibrationUncertaintySource
    assumed_sigma_value: Decimal | None = None
    assumed_sigma_unit: str | None = None
    assumed_sigma_statistic_kind: UncertaintyStatisticKind | None = None
    relative_output_weight: Decimal = Decimal("1")
    provenance_note: str | None = None
    expected_edit_version: int
    updated_by: str | None = None


class AddVariableBindingRequest(BaseModel):
    model_meaning: CalibrationBindingModelMeaning
    target_component_id: str
    value_source: CalibrationBindingValueSource
    constant_value: Decimal | None = None
    constant_unit: str | None = None
    source_column_name: str | None = None
    source: str | None = None
    #: Required if and only if ``model_meaning=INTERVENTION`` (docs/33) --
    #: ``app.persistence.calibration.add_variable_binding`` enforces this.
    intervention_time: Decimal | None = None
    expected_edit_version: int
    updated_by: str | None = None


class AddParameterRoleRequest(BaseModel):
    parameter_name: str
    role: CalibrationParameterRoleKind
    arm_ids: list[UUID]
    fixed_value: Decimal | None = None
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None
    unit: str | None = None
    reference_arm_id: UUID | None = None
    reference_parameter_name: str | None = None
    coefficient_a: Decimal | None = None
    coefficient_a_is_fixed: bool = True
    coefficient_b: Decimal | None = None
    coefficient_b_is_fixed: bool = True
    expected_edit_version: int
    updated_by: str | None = None


class CompleteReviewRequest(BaseModel):
    expected_edit_version: int
    updated_by: str | None = None


class DeclareModelRelationshipRequest(BaseModel):
    model_id_a: UUID
    model_id_b: UUID
    relationship_kind: ModelRelationshipKind
    role_label_a: str | None = None
    role_label_b: str | None = None
    declared_by: str | None = None


__all__ = [
    "AddArmRequest",
    "AddExperimentRequest",
    "AddParameterRoleRequest",
    "AddVariableBindingRequest",
    "ArmItem",
    "CalibrationJobDetail",
    "CalibrationJobRevisionDetail",
    "CalibrationJobRevisionSummary",
    "CalibrationJobSummary",
    "CalibrationReviewResult",
    "CompleteReviewRequest",
    "CreateCalibrationJobRequest",
    "DeclareModelRelationshipRequest",
    "ExecutionCapabilityItem",
    "ExperimentItem",
    "FindingItem",
    "ModelRelationshipItem",
    "OutputWeightingItem",
    "ParameterRoleItem",
    "SetExperimentInitialConditionsDatasetRequest",
    "SetExperimentInitialConditionsMappingRequest",
    "SetExperimentMappingRequest",
    "SetExperimentObjectiveWeightingRequest",
    "SetExperimentOutputWeightingRequest",
    "SetExperimentRoleRequest",
    "VariableBindingItem",
]
