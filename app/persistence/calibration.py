"""CalibrationJob persistence: create and edit a configuration-only joint-calibration draft,
and compute every review finding fresh, on demand, from its own live child rows.

See ``app.models.calibration``, ``docs/29_joint_calibration_workflow_design.md`` (the design,
especially §5's execution contract and §13's revision), and ``docs/30
_joint_calibration_configuration_increment.md`` (what this module actually implements).

Every mutating function below takes ``expected_edit_version`` and raises
``CalibrationJobStaleEdit`` on a mismatch -- the identical optimistic-concurrency discipline
``app.persistence.module_set.edit_draft_member`` already establishes for ``ModuleSetDraft``.
Every mutation that succeeds increments ``CalibrationJob.edit_version`` by exactly one.

Ownership (project/subproject) checks live at the API route layer, mirroring
``app.api.v1.routes.projects``'s own established ``_require_*`` pattern -- this module trusts
its own callers' contract for *which* subproject a given id belongs to, identical to
``app.persistence.module_set``'s own documented discipline, but still independently re-validates
every cross-entity fact this module itself is responsible for asserting (e.g. that a dataset or
model actually belongs to the job's own subproject).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.calibration import (
    CalibrationArm,
    CalibrationExperiment,
    CalibrationExperimentOutputWeighting,
    CalibrationExperimentVariableBinding,
    CalibrationJob,
    CalibrationJobRevision,
    CalibrationParameterRole,
    CalibrationParameterRoleArm,
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
    MeasurementValueStatus,
    ModelParameterCatalogStatus,
    ModelParameterKind,
    ModelSpeciesCatalogStatus,
    UncertaintyStatisticKind,
)
from app.persistence.dataset_model_alias_mapping import (
    get_current_mapping_revision,
    get_mapping_revision,
)
from app.persistence.model_parameter_catalog import get_model_parameter_catalog
from app.persistence.model_species_catalog import get_model_species_catalog
from app.units import UnitComparisonStatus, compare_units

_LINK_ROLES = {
    CalibrationParameterRoleKind.EXACT_EQUALITY,
    CalibrationParameterRoleKind.EXACT_AFFINE_LINK,
    CalibrationParameterRoleKind.SOFT_PRIOR_LINK,
}
_HARD_LINK_ROLES = {
    CalibrationParameterRoleKind.EXACT_EQUALITY,
    CalibrationParameterRoleKind.EXACT_AFFINE_LINK,
}


class CalibrationJobStaleEdit(ValueError):
    """Raised when ``expected_edit_version`` no longer matches the job's own current
    ``edit_version`` -- someone/something else edited this job first."""

    def __init__(self, job: CalibrationJob, expected_edit_version: int) -> None:
        self.job = job
        self.expected_edit_version = expected_edit_version
        super().__init__(
            f"CalibrationJob {job.id} is at edit_version {job.edit_version}, not "
            f"{expected_edit_version} -- it was edited since last read"
        )


class CalibrationReviewBlocked(ValueError):
    """Raised by ``complete_review`` when at least one ``ERROR``-severity finding exists --
    review never completes over a configuration that is not yet internally consistent, even
    though "Run" would stay disabled regardless (§5 rule 5 is a separate, always-additional
    check)."""

    def __init__(self, findings: list[CalibrationFinding]) -> None:
        self.findings = findings
        super().__init__(
            f"{len([f for f in findings if f.severity == 'ERROR'])} blocking finding(s)"
        )


class ReferencedArmNotRemovable(ValueError):
    """Raised by ``remove_arm`` when at least one ``CalibrationParameterRole`` in this job
    names this arm as its own ``reference_arm_id`` -- the arm must stay until that link is
    removed or repointed (mirrors the database's own ``ON DELETE RESTRICT`` on that foreign
    key, checked here first so the caller gets a clear, actionable message rather than a raw
    integrity error)."""


def _bump(job: CalibrationJob) -> None:
    job.edit_version += 1
    # Any successful edit drops a REVIEWED job back to DRAFT (docs/29 §7) -- enforced here,
    # once, rather than trusted to every individual mutating function's own caller.
    job.status = CalibrationJobStatus.DRAFT


def _check_version(job: CalibrationJob, expected_edit_version: int) -> None:
    if job.edit_version != expected_edit_version:
        raise CalibrationJobStaleEdit(job, expected_edit_version)


def _validate_target_against_catalogs(
    session: Session,
    *,
    model_id: UUID,
    target_component_id: str,
    allow_species: bool,
    allow_parameters: bool,
) -> bool:
    """Validate ``target_component_id`` against whichever real, ``AVAILABLE`` catalog/catalogs
    ``allow_species``/``allow_parameters`` permit (docs/31). Returns ``True`` (catalog-
    validated) once a match is confirmed; returns ``False`` (curator-declared, disclosed as
    unvalidated) only when **no** relevant catalog is available at all for this model.

    Raises ``ValueError`` when: a real catalog *is* available but the name matches nothing in
    it (never silently accepted as curator-declared just because one check failed); or the
    name matches a real parameter whose own ``kind`` is ``DERIVED`` -- an assignment-rule
    quantity is never an independent calibration target, regardless of what a curator
    believes about it (docs/29 §1 row 15; ``app.models.model_parameter_catalog
    .ModelParameterKind``).
    """
    checked_any_catalog = False

    if allow_species:
        species_catalog = get_model_species_catalog(session, model_id)
        if (
            species_catalog is not None
            and species_catalog.status is ModelSpeciesCatalogStatus.AVAILABLE
        ):
            checked_any_catalog = True
            if target_component_id in {s.antimony_species_id for s in species_catalog.species}:
                return True

    if allow_parameters:
        parameter_catalog = get_model_parameter_catalog(session, model_id)
        if (
            parameter_catalog is not None
            and parameter_catalog.status is ModelParameterCatalogStatus.AVAILABLE
        ):
            checked_any_catalog = True
            known = {p.antimony_parameter_id: p for p in parameter_catalog.parameters}
            match = known.get(target_component_id)
            if match is not None:
                if match.kind is ModelParameterKind.DERIVED:
                    raise ValueError(
                        f"{target_component_id!r} is a derived (assignment-rule) parameter in "
                        f"model {model_id}'s own verified parameter catalog -- never an "
                        "independent calibration target, regardless of how it is declared"
                    )
                return True

    if checked_any_catalog:
        raise ValueError(
            f"{target_component_id!r} is not a real, independent target in model {model_id}'s "
            "own verified catalog(s)"
        )
    return False


# --- Job lifecycle -----------------------------------------------------------------------


def create_job(
    session: Session, *, subproject_id: UUID, created_by: str | None = None
) -> CalibrationJob:
    job = CalibrationJob(subproject_id=subproject_id, created_by=created_by, updated_by=created_by)
    session.add(job)
    session.flush()
    return job


def get_job(session: Session, job_id: UUID) -> CalibrationJob | None:
    return session.get(
        CalibrationJob,
        job_id,
        options=[
            selectinload(CalibrationJob.arms)
            .selectinload(CalibrationArm.experiments)
            .selectinload(CalibrationExperiment.variable_bindings),
            selectinload(CalibrationJob.arms)
            .selectinload(CalibrationArm.experiments)
            .selectinload(CalibrationExperiment.output_weightings),
            selectinload(CalibrationJob.parameter_roles).selectinload(
                CalibrationParameterRole.arm_links
            ),
        ],
    )


def get_job_for_subproject(
    session: Session, subproject_id: UUID, job_id: UUID
) -> CalibrationJob | None:
    job = get_job(session, job_id)
    if job is None or job.subproject_id != subproject_id:
        return None
    return job


def list_jobs_for_subproject(session: Session, subproject_id: UUID) -> list[CalibrationJob]:
    stmt = (
        select(CalibrationJob)
        .where(CalibrationJob.subproject_id == subproject_id)
        .order_by(CalibrationJob.created_at.desc())
    )
    return list(session.scalars(stmt))


# --- Arms --------------------------------------------------------------------------------


def add_arm(
    session: Session,
    *,
    job: CalibrationJob,
    model_id: UUID,
    expected_edit_version: int,
    role_label: str | None = None,
    updated_by: str | None = None,
) -> CalibrationArm:
    _check_version(job, expected_edit_version)
    arm = CalibrationArm(
        calibration_job=job,
        model_id=model_id,
        role_label=role_label,
        sequence_index=len(job.arms),
    )
    session.add(arm)
    job.updated_by = updated_by
    _bump(job)
    session.flush()
    return arm


def remove_arm(
    session: Session,
    *,
    job: CalibrationJob,
    arm_id: UUID,
    expected_edit_version: int,
    updated_by: str | None = None,
) -> CalibrationJob:
    _check_version(job, expected_edit_version)
    arm = next((a for a in job.arms if a.id == arm_id), None)
    if arm is None:
        raise ValueError(f"no CalibrationArm with id {arm_id} in job {job.id}")
    referencing = [r for r in job.parameter_roles if r.reference_arm_id == arm_id]
    if referencing:
        raise ReferencedArmNotRemovable(
            f"arm {arm_id} is referenced by parameter role(s) "
            f"{[str(r.id) for r in referencing]} -- remove or repoint those first"
        )
    session.delete(arm)
    job.updated_by = updated_by
    _bump(job)
    session.flush()
    return job


# --- Experiments ---------------------------------------------------------------------------


def add_experiment(
    session: Session,
    *,
    job: CalibrationJob,
    arm: CalibrationArm,
    time_series_dataset_id: UUID,
    expected_edit_version: int,
    role: CalibrationExperimentRole = CalibrationExperimentRole.CALIBRATION,
    updated_by: str | None = None,
) -> CalibrationExperiment:
    _check_version(job, expected_edit_version)
    revision = get_current_mapping_revision(
        session, time_series_dataset_id=time_series_dataset_id, model_id=arm.model_id
    )
    experiment = CalibrationExperiment(
        arm=arm,
        time_series_dataset_id=time_series_dataset_id,
        alias_mapping_revision_id=revision.id if revision is not None else None,
        role=role,
        sequence_index=len(arm.experiments),
    )
    session.add(experiment)
    job.updated_by = updated_by
    _bump(job)
    session.flush()
    return experiment


def remove_experiment(
    session: Session,
    *,
    job: CalibrationJob,
    experiment_id: UUID,
    expected_edit_version: int,
    updated_by: str | None = None,
) -> CalibrationJob:
    _check_version(job, expected_edit_version)
    experiment = _find_experiment(job, experiment_id)
    session.delete(experiment)
    job.updated_by = updated_by
    _bump(job)
    session.flush()
    return job


def _find_experiment(job: CalibrationJob, experiment_id: UUID) -> CalibrationExperiment:
    for arm in job.arms:
        for experiment in arm.experiments:
            if experiment.id == experiment_id:
                return experiment
    raise ValueError(f"no CalibrationExperiment with id {experiment_id} in job {job.id}")


def set_experiment_mapping(
    session: Session,
    *,
    job: CalibrationJob,
    experiment_id: UUID,
    alias_mapping_revision_number: int | None,
    expected_edit_version: int,
    updated_by: str | None = None,
) -> CalibrationExperiment:
    """Re-pin (or clear, with ``None``) one experiment's own alias-mapping revision -- always
    an explicit scientist action (docs/29 §7's "re-pin" choice), never automatic. Identified by
    ``revision_number`` (the one identifier the alias-mapping API itself already exposes,
    docs/27 -- its underlying row id is never surfaced there), resolved here to the real,
    immutable ``DatasetModelAliasMappingRevision`` row for this experiment's own (dataset,
    arm's model) pair.

    Raises ``ValueError`` if no such revision exists."""
    _check_version(job, expected_edit_version)
    experiment = _find_experiment(job, experiment_id)
    if alias_mapping_revision_number is None:
        experiment.alias_mapping_revision_id = None
    else:
        revision = get_mapping_revision(
            session,
            time_series_dataset_id=experiment.time_series_dataset_id,
            model_id=experiment.arm.model_id,
            revision_number=alias_mapping_revision_number,
        )
        if revision is None:
            raise ValueError(
                f"no alias-mapping revision {alias_mapping_revision_number} for "
                f"(dataset={experiment.time_series_dataset_id}, model={experiment.arm.model_id})"
            )
        experiment.alias_mapping_revision_id = revision.id
    job.updated_by = updated_by
    _bump(job)
    session.flush()
    # `expire_on_commit=False` sessions (this project's own test fixture) would otherwise keep
    # serving the relationship's pre-update cached value -- force a fresh lazy load reflecting
    # the FK assignment just made.
    session.expire(experiment, ["alias_mapping_revision"])
    return experiment


def set_experiment_role(
    session: Session,
    *,
    job: CalibrationJob,
    experiment_id: UUID,
    role: CalibrationExperimentRole,
    expected_edit_version: int,
    updated_by: str | None = None,
) -> CalibrationExperiment:
    _check_version(job, expected_edit_version)
    experiment = _find_experiment(job, experiment_id)
    experiment.role = role
    job.updated_by = updated_by
    _bump(job)
    session.flush()
    return experiment


def set_experiment_objective_weighting(
    session: Session,
    *,
    job: CalibrationJob,
    experiment_id: UUID,
    objective_weighting: CalibrationObjectiveWeighting,
    expected_edit_version: int,
    weighting_notes: str | None = None,
    updated_by: str | None = None,
) -> CalibrationExperiment:
    _check_version(job, expected_edit_version)
    experiment = _find_experiment(job, experiment_id)
    experiment.objective_weighting = objective_weighting
    experiment.weighting_notes = weighting_notes
    job.updated_by = updated_by
    _bump(job)
    session.flush()
    return experiment


# --- Output-level uncertainty/weighting (docs/29 §5, docs/32) ----------------------------


def _require_finite_positive(value: Decimal, *, label: str) -> None:
    """Raise ``ValueError`` unless ``value`` is a real, strictly positive, finite number --
    never zero (an inverse-variance weight of ``1/value**2`` would be infinite), never
    negative, and never ``Infinity``/``NaN`` (both of which ``Decimal`` parses from those exact
    literal strings without error, and for which an ordinary ``<= 0`` comparison is either
    silently wrong (``Infinity > 0``) or itself raises ``decimal.InvalidOperation`` (comparing
    ``NaN``) -- so finiteness is checked first, before any ordering comparison, every time
    (task instructions: "requires strictly positive, finite uncertainty values; zero must not
    produce infinite weight")."""
    if not value.is_finite():
        raise ValueError(f"{label} must be a finite number (not Infinity/NaN)")
    if value <= 0:
        raise ValueError(f"{label} must be > 0")


def set_experiment_output_weighting(
    session: Session,
    *,
    job: CalibrationJob,
    experiment_id: UUID,
    output_column_name: str,
    uncertainty_source: CalibrationUncertaintySource,
    expected_edit_version: int,
    assumed_sigma_value: Decimal | None = None,
    assumed_sigma_unit: str | None = None,
    assumed_sigma_statistic_kind: UncertaintyStatisticKind | None = None,
    relative_output_weight: Decimal = Decimal("1"),
    provenance_note: str | None = None,
    updated_by: str | None = None,
) -> CalibrationExperimentOutputWeighting:
    """Declare (or replace -- upsert on ``(experiment_id, output_column_name)``) one output's
    own uncertainty source and relative weight (``docs/32``'s minimal error/weighting contract
    -- see ``app.models.calibration.CalibrationExperimentOutputWeighting`` for the objective
    this configures).

    Raises ``ValueError`` for: an empty ``output_column_name``, or one not actually a
    ``TimeSeriesMeasurementColumn`` of this experiment's own pinned dataset (never fabricated,
    never validated against any other dataset); ``uncertainty_source=MEASURED`` when the
    dataset declares no matching ``TimeSeriesMeasurementUncertaintyColumn`` for this output
    (never assumed); ``uncertainty_source=USER_ASSUMED`` with no strictly positive, finite
    ``assumed_sigma_value``, no declared ``assumed_sigma_statistic_kind`` (standard deviation /
    variance / standard error -- never left implicit, never guessed), or a value whose
    ``assumed_sigma_unit`` is dimensionally incompatible with the output's own declared
    measurement unit; a non-``USER_ASSUMED`` source supplied together with a sigma value/unit/
    statistic kind (conflicting sources -- exactly one must be named); or a non-finite or
    non-positive ``relative_output_weight`` (down-weighting an output to zero/negative is never
    expressed this way -- remove the row, or change the experiment's own role, instead).
    """
    _check_version(job, expected_edit_version)
    experiment = _find_experiment(job, experiment_id)

    output_column_name = output_column_name.strip()
    if not output_column_name:
        raise ValueError("output_column_name must not be empty")
    known_measurement_columns = {
        c.column_name: c.unit for c in experiment.time_series_dataset.measurement_columns
    }
    if output_column_name not in known_measurement_columns:
        raise ValueError(
            f"{output_column_name!r} is not a measurement column of dataset "
            f"{experiment.time_series_dataset_id}"
        )

    if relative_output_weight is None:
        raise ValueError("relative_output_weight must be > 0")
    _require_finite_positive(relative_output_weight, label="relative_output_weight")

    if uncertainty_source is CalibrationUncertaintySource.MEASURED:
        if (
            assumed_sigma_value is not None
            or assumed_sigma_unit is not None
            or assumed_sigma_statistic_kind is not None
        ):
            raise ValueError(
                "uncertainty_source=MEASURED must not also carry an assumed sigma value/unit/"
                "statistic kind -- exactly one uncertainty source may be named"
            )
        declared_uncertainty_targets = {
            c.measurement_column_name
            for c in experiment.time_series_dataset.measurement_uncertainty_columns
        }
        if output_column_name not in declared_uncertainty_targets:
            raise ValueError(
                f"dataset {experiment.time_series_dataset_id} declares no "
                f"measurement-uncertainty column for {output_column_name!r} -- MEASURED is "
                "not available for this output"
            )
    elif uncertainty_source is CalibrationUncertaintySource.USER_ASSUMED:
        if assumed_sigma_value is None:
            raise ValueError("uncertainty_source=USER_ASSUMED requires a sigma value")
        _require_finite_positive(assumed_sigma_value, label="assumed_sigma_value")
        if assumed_sigma_statistic_kind is None:
            raise ValueError(
                "uncertainty_source=USER_ASSUMED requires assumed_sigma_statistic_kind "
                "(standard deviation / variance / standard error -- never left implicit)"
            )
        declared_unit = known_measurement_columns.get(output_column_name)
        if assumed_sigma_unit and declared_unit:
            comparison = compare_units(assumed_sigma_unit, declared_unit)
            if comparison["status"] == UnitComparisonStatus.INCOMPATIBLE.value:
                raise ValueError(
                    f"assumed sigma unit {assumed_sigma_unit!r} is dimensionally incompatible "
                    f"with {output_column_name!r}'s own declared unit {declared_unit!r}"
                )
    else:  # UNKNOWN
        if (
            assumed_sigma_value is not None
            or assumed_sigma_unit is not None
            or assumed_sigma_statistic_kind is not None
        ):
            raise ValueError(
                "uncertainty_source=UNKNOWN must not also carry an assumed sigma value/unit/"
                "statistic kind"
            )

    existing = next(
        (w for w in experiment.output_weightings if w.output_column_name == output_column_name),
        None,
    )
    if existing is not None:
        existing.uncertainty_source = uncertainty_source
        existing.assumed_sigma_value = assumed_sigma_value
        existing.assumed_sigma_unit = assumed_sigma_unit
        existing.assumed_sigma_statistic_kind = assumed_sigma_statistic_kind
        existing.relative_output_weight = relative_output_weight
        existing.provenance_note = provenance_note
        weighting = existing
    else:
        weighting = CalibrationExperimentOutputWeighting(
            experiment=experiment,
            output_column_name=output_column_name,
            uncertainty_source=uncertainty_source,
            assumed_sigma_value=assumed_sigma_value,
            assumed_sigma_unit=assumed_sigma_unit,
            assumed_sigma_statistic_kind=assumed_sigma_statistic_kind,
            relative_output_weight=relative_output_weight,
            provenance_note=provenance_note,
        )
        session.add(weighting)
    job.updated_by = updated_by
    _bump(job)
    session.flush()
    return weighting


def remove_experiment_output_weighting(
    session: Session,
    *,
    job: CalibrationJob,
    weighting_id: UUID,
    expected_edit_version: int,
    updated_by: str | None = None,
) -> CalibrationJob:
    """Remove one declared output weighting -- reverts that output to the identical "no
    explicit declaration" default (``UNKNOWN`` uncertainty, ``relative_output_weight=1``)."""
    _check_version(job, expected_edit_version)
    for arm in job.arms:
        for experiment in arm.experiments:
            weighting = next(
                (w for w in experiment.output_weightings if w.id == weighting_id), None
            )
            if weighting is not None:
                session.delete(weighting)
                job.updated_by = updated_by
                _bump(job)
                session.flush()
                # `expire_on_commit=False` sessions (this project's own test fixture) would
                # otherwise keep serving the collection's pre-delete cached value.
                session.expire(experiment, ["output_weightings"])
                return job
    raise ValueError(f"no output weighting with id {weighting_id} in job {job.id}")


# --- Independent-variable bindings --------------------------------------------------------

_SPECIES_TARGETED_MEANINGS = {
    CalibrationBindingModelMeaning.INITIAL_VALUE,
    CalibrationBindingModelMeaning.INTERVENTION,
}
_PARAMETER_TARGETED_MEANINGS = {
    CalibrationBindingModelMeaning.PARAMETER_OVERRIDE,
    CalibrationBindingModelMeaning.INTERVENTION,
}


def add_variable_binding(
    session: Session,
    *,
    job: CalibrationJob,
    experiment_id: UUID,
    model_meaning: CalibrationBindingModelMeaning,
    target_component_id: str,
    value_source: CalibrationBindingValueSource,
    expected_edit_version: int,
    constant_value: Decimal | None = None,
    constant_unit: str | None = None,
    source_column_name: str | None = None,
    source: str | None = None,
    intervention_time: Decimal | None = None,
    updated_by: str | None = None,
) -> CalibrationExperimentVariableBinding:
    """Add one independent-variable binding, with its own explicit model meaning (docs/31).

    ``target_component_id`` is validated server-side against whichever of
    ``ModelSpeciesCatalog``/``ModelParameterCatalog`` is relevant to ``model_meaning`` and
    actually ``AVAILABLE`` for this experiment's own arm's model (``INITIAL_VALUE`` -> species
    only; ``PARAMETER_OVERRIDE`` -> parameters only; ``INTERVENTION`` -> either) -- curator-
    declared, disclosed as unvalidated, only when no relevant catalog exists yet. Raises
    ``ValueError`` if the name is confirmed a real ``DERIVED`` parameter (never an independent
    target) or confirmed absent from an actually-available catalog.

    ``value_source=CONSTANT`` requires ``constant_value``. ``value_source=DATASET_COLUMN``
    requires ``source_column_name`` naming a real, declared
    ``TimeSeriesIndependentVariableColumn`` of this experiment's own pinned dataset -- the real
    per-row values themselves stay in that dataset's own rows, never copied here (module
    docstring's "preserve original data ... do not silently convert values").

    ``intervention_time`` (Whole-Model Experimental-Scenario Evaluation increment, docs/33) is
    **required when ``model_meaning=INTERVENTION``, forbidden otherwise** -- without it,
    ``INTERVENTION`` would be behaviorally indistinguishable from ``INITIAL_VALUE``/
    ``PARAMETER_OVERRIDE`` (both of which always take effect at the trajectory's own start).
    Also enforced by a database ``CHECK`` constraint (defense in depth); this is the first,
    actionable check a caller actually sees.
    """
    _check_version(job, expected_edit_version)
    experiment = _find_experiment(job, experiment_id)

    _validate_target_against_catalogs(
        session,
        model_id=experiment.arm.model_id,
        target_component_id=target_component_id,
        allow_species=model_meaning in _SPECIES_TARGETED_MEANINGS,
        allow_parameters=model_meaning in _PARAMETER_TARGETED_MEANINGS,
    )

    if value_source is CalibrationBindingValueSource.CONSTANT:
        if constant_value is None:
            raise ValueError("value_source=CONSTANT requires constant_value")
    elif value_source is CalibrationBindingValueSource.DATASET_COLUMN:
        if not source_column_name:
            raise ValueError("value_source=DATASET_COLUMN requires source_column_name")
        known_columns = {
            c.column_name for c in experiment.time_series_dataset.independent_variable_columns
        }
        if source_column_name not in known_columns:
            raise ValueError(
                f"{source_column_name!r} is not a declared independent-variable column of "
                f"dataset {experiment.time_series_dataset_id}"
            )

    if model_meaning is CalibrationBindingModelMeaning.INTERVENTION:
        if intervention_time is None:
            raise ValueError("model_meaning=INTERVENTION requires intervention_time")
    elif intervention_time is not None:
        raise ValueError(
            f"intervention_time is only valid for model_meaning=INTERVENTION, got "
            f"{model_meaning.value!r}"
        )

    binding = CalibrationExperimentVariableBinding(
        experiment=experiment,
        model_meaning=model_meaning,
        target_component_id=target_component_id,
        value_source=value_source,
        constant_value=constant_value,
        constant_unit=constant_unit,
        source_column_name=source_column_name,
        source=source,
        intervention_time=intervention_time,
    )
    session.add(binding)
    job.updated_by = updated_by
    _bump(job)
    session.flush()
    return binding


def remove_variable_binding(
    session: Session,
    *,
    job: CalibrationJob,
    binding_id: UUID,
    expected_edit_version: int,
    updated_by: str | None = None,
) -> CalibrationJob:
    _check_version(job, expected_edit_version)
    for arm in job.arms:
        for experiment in arm.experiments:
            binding = next(
                (b for b in experiment.variable_bindings if b.id == binding_id), None
            )
            if binding is not None:
                session.delete(binding)
                job.updated_by = updated_by
                _bump(job)
                session.flush()
                return job
    raise ValueError(f"no variable binding with id {binding_id} in job {job.id}")


# --- Parameter roles ---------------------------------------------------------------------


def add_parameter_role(
    session: Session,
    *,
    job: CalibrationJob,
    parameter_name: str,
    role: CalibrationParameterRoleKind,
    arm_ids: list[UUID],
    expected_edit_version: int,
    fixed_value: Decimal | None = None,
    lower_bound: Decimal | None = None,
    upper_bound: Decimal | None = None,
    unit: str | None = None,
    reference_arm_id: UUID | None = None,
    reference_parameter_name: str | None = None,
    coefficient_a: Decimal | None = None,
    coefficient_a_is_fixed: bool = True,
    coefficient_b: Decimal | None = None,
    coefficient_b_is_fixed: bool = True,
    updated_by: str | None = None,
) -> CalibrationParameterRole:
    """Declare one parameter's role, covering ``arm_ids``.

    Raises ``ValueError`` for: an empty ``parameter_name``/``arm_ids``; an ``arm_id`` not
    belonging to this job; ``role=FIXED`` with no ``fixed_value``; a link role
    (``EXACT_EQUALITY``/``EXACT_AFFINE_LINK``/``SOFT_PRIOR_LINK``) missing
    ``reference_arm_id``/``reference_parameter_name``, or naming a ``reference_arm_id`` not in
    this job; ``EXACT_AFFINE_LINK`` missing a non-fixed-or-valued coefficient.
    """
    _check_version(job, expected_edit_version)
    if not parameter_name.strip():
        raise ValueError("parameter_name must not be empty")
    if not arm_ids:
        raise ValueError("a parameter role must cover at least one arm")
    job_arm_ids = {a.id for a in job.arms}
    unknown_arms = set(arm_ids) - job_arm_ids
    if unknown_arms:
        raise ValueError(f"arm id(s) {sorted(str(a) for a in unknown_arms)} are not in this job")

    if role is CalibrationParameterRoleKind.FIXED and fixed_value is None:
        raise ValueError("role=FIXED requires fixed_value")
    if role in _LINK_ROLES:
        if reference_arm_id is None or not (reference_parameter_name or "").strip():
            raise ValueError(
                f"role={role.value} requires reference_arm_id and reference_parameter_name"
            )
        if reference_arm_id not in job_arm_ids:
            raise ValueError(f"reference_arm_id {reference_arm_id} is not an arm in this job")
    if role is CalibrationParameterRoleKind.EXACT_AFFINE_LINK:
        if coefficient_a_is_fixed and coefficient_a is None:
            raise ValueError("a fixed coefficient_a requires a value")
        if coefficient_b_is_fixed and coefficient_b is None:
            raise ValueError("a fixed coefficient_b requires a value")

    # Validate against each covered arm's own model parameter catalog (docs/31) -- never
    # against species, and never inferred from a name. `catalog_validated` is True only when
    # every covered arm's own catalog was actually available and confirmed the name; a
    # genuine rejection (a real DERIVED parameter, or a real catalog that confirms the name is
    # absent) always raises, never silently downgrades to "unvalidated."
    covering_arms = [a for a in job.arms if a.id in set(arm_ids)]
    catalog_validated = bool(covering_arms) and all(
        _validate_target_against_catalogs(
            session,
            model_id=arm.model_id,
            target_component_id=parameter_name.strip(),
            allow_species=False,
            allow_parameters=True,
        )
        for arm in covering_arms
    )
    if role in _LINK_ROLES and reference_arm_id is not None:
        reference_arm = next(a for a in job.arms if a.id == reference_arm_id)
        _validate_target_against_catalogs(
            session,
            model_id=reference_arm.model_id,
            target_component_id=(reference_parameter_name or "").strip(),
            allow_species=False,
            allow_parameters=True,
        )

    parameter_role = CalibrationParameterRole(
        calibration_job=job,
        parameter_name=parameter_name.strip(),
        role=role,
        catalog_validated=catalog_validated,
        fixed_value=fixed_value,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        unit=unit,
        reference_arm_id=reference_arm_id,
        reference_parameter_name=(
            reference_parameter_name.strip() if reference_parameter_name else None
        ),
        coefficient_a=coefficient_a,
        coefficient_a_is_fixed=coefficient_a_is_fixed,
        coefficient_b=coefficient_b,
        coefficient_b_is_fixed=coefficient_b_is_fixed,
    )
    session.add(parameter_role)
    session.flush()
    for arm_id in arm_ids:
        session.add(
            CalibrationParameterRoleArm(parameter_role=parameter_role, calibration_arm_id=arm_id)
        )
    job.updated_by = updated_by
    _bump(job)
    session.flush()
    return parameter_role


def remove_parameter_role(
    session: Session,
    *,
    job: CalibrationJob,
    parameter_role_id: UUID,
    expected_edit_version: int,
    updated_by: str | None = None,
) -> CalibrationJob:
    _check_version(job, expected_edit_version)
    role = next((r for r in job.parameter_roles if r.id == parameter_role_id), None)
    if role is None:
        raise ValueError(f"no CalibrationParameterRole with id {parameter_role_id} in job {job.id}")
    session.delete(role)
    job.updated_by = updated_by
    _bump(job)
    session.flush()
    return job


# --- Findings, computed fresh on every review (docs/29 §13 -- never persisted) -----------


@dataclass(frozen=True, slots=True)
class CalibrationFinding:
    severity: CalibrationFindingSeverity
    category: CalibrationFindingCategory
    message: str
    involved_arm_ids: list[UUID] = field(default_factory=list)
    involved_experiment_ids: list[UUID] = field(default_factory=list)
    involved_parameter_role_ids: list[UUID] = field(default_factory=list)


def _effective_condition_ids(dataset) -> set[str | None]:
    return {row.condition_id for row in dataset.rows}


def _binding_signature(experiment: CalibrationExperiment) -> frozenset:
    return frozenset(
        (
            b.model_meaning.value,
            b.target_component_id,
            b.value_source.value,
            str(b.constant_value),
            b.constant_unit,
            b.source_column_name,
        )
        for b in experiment.variable_bindings
    )


def _assigned_targets_by_column(experiment: CalibrationExperiment) -> dict[str, str] | None:
    if experiment.alias_mapping_revision is None:
        return None
    return {
        a.column_name: a.target_antimony_species_id
        for a in experiment.alias_mapping_revision.assignments
        if a.target_antimony_species_id is not None
    }


def _compatibility_findings_for_arm(arm: CalibrationArm) -> list[CalibrationFinding]:
    findings: list[CalibrationFinding] = []
    calibration_experiments = [
        e for e in arm.experiments if e.role is CalibrationExperimentRole.CALIBRATION
    ]
    for i, a in enumerate(calibration_experiments):
        for b in calibration_experiments[i + 1 :]:
            reasons: list[str] = []
            conditions_a = _effective_condition_ids(a.time_series_dataset)
            conditions_b = _effective_condition_ids(b.time_series_dataset)
            if len(conditions_a) > 1 or len(conditions_b) > 1:
                findings.append(
                    CalibrationFinding(
                        severity=CalibrationFindingSeverity.INFO,
                        category=CalibrationFindingCategory.INCOMPATIBLE_EXPERIMENTS_MERGED,
                        message=(
                            "At least one of these two experiments' own datasets records more "
                            "than one condition -- trajectory-sharing compatibility could only "
                            "be approximated, not conclusively checked."
                        ),
                        involved_experiment_ids=[a.id, b.id],
                    )
                )
            elif conditions_a != conditions_b:
                reasons.append(f"declared condition {conditions_a} vs. {conditions_b}")

            if _binding_signature(a) != _binding_signature(b):
                reasons.append("independent-variable bindings differ")

            targets_a = _assigned_targets_by_column(a)
            targets_b = _assigned_targets_by_column(b)
            if targets_a is not None and targets_b is not None:
                shared_columns = set(targets_a) & set(targets_b)
                disagreeing = {c for c in shared_columns if targets_a[c] != targets_b[c]}
                if disagreeing:
                    reasons.append(
                        "observation-mapping target species disagree for column(s) "
                        f"{sorted(disagreeing)}"
                    )

            if reasons:
                # WARNING, never ERROR (docs/31 audit fix): differing conditions, bindings, or
                # observation-mapping targets between two experiments on the same arm are a
                # real, normal, *saveable* configuration -- the real execution contract
                # (docs/29 §5 step 2) gives each experiment its own simulated trajectory using
                # its own inputs regardless. This finding only discloses that the narrow,
                # today-available "merge into one trajectory" shortcut (§5's own vacuous-case
                # special case) does not apply to this pair -- it has never been, and must
                # never become, a reason "Complete review" refuses to save the configuration.
                # Unsupported *execution* is what stays blocked (§5 rule 5), never
                # configuration saving.
                findings.append(
                    CalibrationFinding(
                        severity=CalibrationFindingSeverity.WARNING,
                        category=CalibrationFindingCategory.INCOMPATIBLE_EXPERIMENTS_MERGED,
                        message=(
                            "These two experiments cannot share one simulated trajectory via "
                            "today's narrow shortcut -- each will need its own evaluation once "
                            "the general joint-evaluation primitive exists: "
                            + "; ".join(reasons)
                            + "."
                        ),
                        involved_experiment_ids=[a.id, b.id],
                    )
                )
    return findings


def _dataset_reuse_findings(job: CalibrationJob) -> list[CalibrationFinding]:
    findings: list[CalibrationFinding] = []
    for arm in job.arms:
        by_dataset: dict[UUID, list[CalibrationExperiment]] = {}
        for experiment in arm.experiments:
            by_dataset.setdefault(experiment.time_series_dataset_id, []).append(experiment)
        for dataset_id, experiments in by_dataset.items():
            roles = {e.role for e in experiments}
            if (
                CalibrationExperimentRole.CALIBRATION in roles
                and CalibrationExperimentRole.HELD_OUT_VALIDATION in roles
            ):
                findings.append(
                    CalibrationFinding(
                        severity=CalibrationFindingSeverity.ERROR,
                        category=CalibrationFindingCategory.CALIBRATION_VALIDATION_DATASET_REUSE,
                        message=(
                            f"Dataset {dataset_id} is assigned as both calibration and "
                            "held-out-validation evidence on the same arm."
                        ),
                        involved_arm_ids=[arm.id],
                        involved_experiment_ids=[e.id for e in experiments],
                    )
                )

    dataset_models: dict[UUID, set[UUID]] = {}
    for arm in job.arms:
        for experiment in arm.experiments:
            dataset_models.setdefault(experiment.time_series_dataset_id, set()).add(arm.model_id)
    for dataset_id, model_ids in dataset_models.items():
        if len(model_ids) > 1:
            findings.append(
                CalibrationFinding(
                    severity=CalibrationFindingSeverity.WARNING,
                    category=CalibrationFindingCategory.DATASET_REUSED_ACROSS_DIFFERENT_MODELS,
                    message=f"Dataset {dataset_id} is assigned to arms with different models.",
                )
            )
    return findings


def _parameter_role_findings(job: CalibrationJob) -> list[CalibrationFinding]:
    findings: list[CalibrationFinding] = []

    # AMBIGUOUS_SAME_NAME_PARAMETER: the identical name declared independently (no link tying
    # them) in >=2 arms.
    single_arm_roles: dict[str, set[UUID]] = {}
    linked_names: set[str] = set()
    for role in job.parameter_roles:
        covering_arm_ids = {link.calibration_arm_id for link in role.arm_links}
        if role.role in _LINK_ROLES:
            linked_names.add(role.parameter_name)
            if role.reference_parameter_name:
                linked_names.add(role.reference_parameter_name)
        else:
            single_arm_roles.setdefault(role.parameter_name, set()).update(covering_arm_ids)
    for name, arm_ids in single_arm_roles.items():
        if len(arm_ids) > 1 and name not in linked_names:
            findings.append(
                CalibrationFinding(
                    severity=CalibrationFindingSeverity.WARNING,
                    category=CalibrationFindingCategory.AMBIGUOUS_SAME_NAME_PARAMETER,
                    message=(
                        f"Parameter {name!r} is independently declared on {len(arm_ids)} arms "
                        "with no explicit sharing/linking role tying them together -- matching "
                        "names never establish identity. Declare EXACT_EQUALITY/"
                        "EXACT_AFFINE_LINK/SOFT_PRIOR_LINK if these are meant to be related."
                    ),
                    involved_arm_ids=sorted(arm_ids, key=str),
                )
            )

    # PARAMETER_ROLE_CYCLE: graph over (arm_id, parameter_name) -> (reference_arm_id,
    # reference_parameter_name) edges from hard-link roles, covering every arm the role names.
    edges: dict[tuple[UUID, str], set[tuple[UUID, str]]] = {}
    for role in job.parameter_roles:
        if role.role not in _HARD_LINK_ROLES or role.reference_arm_id is None:
            continue
        target = (role.reference_arm_id, role.reference_parameter_name or "")
        for link in role.arm_links:
            edges.setdefault((link.calibration_arm_id, role.parameter_name), set()).add(target)

    def _has_cycle() -> list[tuple[UUID, str]] | None:
        visiting: set[tuple[UUID, str]] = set()
        visited: set[tuple[UUID, str]] = set()

        def dfs(
            node: tuple[UUID, str], path: list[tuple[UUID, str]]
        ) -> list[tuple[UUID, str]] | None:
            if node in visiting:
                return [*path, node]
            if node in visited:
                return None
            visiting.add(node)
            for neighbor in edges.get(node, ()):
                result = dfs(neighbor, [*path, node])
                if result is not None:
                    return result
            visiting.discard(node)
            visited.add(node)
            return None

        for start in list(edges):
            result = dfs(start, [])
            if result is not None:
                return result
        return None

    cycle = _has_cycle()
    if cycle is not None:
        findings.append(
            CalibrationFinding(
                severity=CalibrationFindingSeverity.ERROR,
                category=CalibrationFindingCategory.PARAMETER_ROLE_CYCLE,
                message=(
                    "A cycle exists in the parameter-link reference graph: "
                    + " -> ".join(f"{arm_id}:{name}" for arm_id, name in cycle)
                    + "."
                ),
                involved_arm_ids=sorted({arm_id for arm_id, _ in cycle}, key=str),
            )
        )

    # UNIT_INCOMPATIBLE_LINK: for EXACT_AFFINE_LINK roles with a declared unit on both sides.
    roles_by_arm_and_name: dict[tuple[UUID, str], CalibrationParameterRole] = {}
    for role in job.parameter_roles:
        for link in role.arm_links:
            roles_by_arm_and_name[(link.calibration_arm_id, role.parameter_name)] = role
    for role in job.parameter_roles:
        if role.role is not CalibrationParameterRoleKind.EXACT_AFFINE_LINK or role.unit is None:
            continue
        reference_role = roles_by_arm_and_name.get(
            (role.reference_arm_id, role.reference_parameter_name or "")
        )
        if reference_role is None or reference_role.unit is None:
            findings.append(
                CalibrationFinding(
                    severity=CalibrationFindingSeverity.INFO,
                    category=CalibrationFindingCategory.UNIT_INCOMPATIBLE_LINK,
                    message=(
                        f"Unit compatibility for the EXACT_AFFINE_LINK on {role.parameter_name!r} "
                        "could not be checked -- the reference parameter's own unit is not "
                        "declared."
                    ),
                    involved_parameter_role_ids=[role.id],
                )
            )
            continue
        comparison = compare_units(role.unit, reference_role.unit)
        if comparison["status"] == UnitComparisonStatus.INCOMPATIBLE.value:
            findings.append(
                CalibrationFinding(
                    severity=CalibrationFindingSeverity.ERROR,
                    category=CalibrationFindingCategory.UNIT_INCOMPATIBLE_LINK,
                    message=(
                        f"EXACT_AFFINE_LINK on {role.parameter_name!r} declares unit "
                        f"{role.unit!r}, dimensionally incompatible with its reference's own "
                        f"{reference_role.unit!r}."
                    ),
                    involved_parameter_role_ids=[role.id],
                )
            )

    return findings


def _completeness_findings(job: CalibrationJob) -> list[CalibrationFinding]:
    findings: list[CalibrationFinding] = []
    for arm in job.arms:
        has_mapped_experiment = any(
            e.alias_mapping_revision_id is not None
            and any(
                a.target_antimony_species_id is not None
                for a in e.alias_mapping_revision.assignments
            )
            for e in arm.experiments
        )
        if not has_mapped_experiment:
            findings.append(
                CalibrationFinding(
                    severity=CalibrationFindingSeverity.ERROR,
                    category=CalibrationFindingCategory.ARM_WITHOUT_MAPPED_EXPERIMENT,
                    message=(
                        "This arm has no experiment with at least one assigned measurement "
                        "mapping."
                    ),
                    involved_arm_ids=[arm.id],
                )
            )

    has_free_parameter = False
    for role in job.parameter_roles:
        if role.role in (
            CalibrationParameterRoleKind.MODEL_SPECIFIC,
            CalibrationParameterRoleKind.EXACT_EQUALITY,
            CalibrationParameterRoleKind.SOFT_PRIOR_LINK,
        ) or (
            role.role is CalibrationParameterRoleKind.EXACT_AFFINE_LINK
            and not (role.coefficient_a_is_fixed and role.coefficient_b_is_fixed)
        ):
            has_free_parameter = True
    if not has_free_parameter:
        findings.append(
            CalibrationFinding(
                severity=CalibrationFindingSeverity.ERROR,
                category=CalibrationFindingCategory.NO_FREE_PARAMETER_TO_FIT,
                message="No parameter anywhere in this job is actually free to fit.",
            )
        )
    return findings


def _measured_uncertainty_nonpositive_row_count(dataset, column_name: str) -> int:
    """How many of ``dataset``'s own rows have a real observation (``MEASURED``-status) for
    ``column_name`` but no strictly-positive, ``MEASURED``-status uncertainty value to pair
    with it -- the exact condition that would make inverse-variance weighting either undefined
    (division by zero) or meaningless (a negative spread) for that one observation. A row whose
    own *measurement* is not ``MEASURED`` (missing/unknown/not-applicable/unrecognized) is
    never counted here: with no real residual to weight, its own uncertainty is moot."""
    count = 0
    for row in dataset.rows:
        measurement = json.loads(row.measurements).get(column_name)
        if (
            measurement is None
            or measurement.get("status") != MeasurementValueStatus.MEASURED.value
        ):
            continue
        uncertainty = json.loads(row.measurement_uncertainty or "{}").get(column_name)
        if (
            uncertainty is None
            or uncertainty.get("status") != MeasurementValueStatus.MEASURED.value
            or uncertainty.get("value") is None
            or uncertainty["value"] <= 0
        ):
            count += 1
    return count


def _uncertainty_weighting_findings(job: CalibrationJob) -> list[CalibrationFinding]:
    """The minimal error/weighting contract's own review findings (``docs/29`` §5, ``docs/32``)
    -- never conflated with execution capability (``app.persistence.calibration
    .execution_capability``), which stays unavailable regardless of how any of this resolves.
    """
    findings: list[CalibrationFinding] = []
    for arm in job.arms:
        for experiment in arm.experiments:
            if experiment.role is not CalibrationExperimentRole.CALIBRATION:
                # Held-out-validation evidence never enters the fit's own objective (module
                # docstring) -- its own weighting declarations are moot, never reviewed here.
                continue
            weighting_by_output = {
                w.output_column_name: w for w in experiment.output_weightings
            }
            for column in experiment.time_series_dataset.measurement_columns:
                output_weighting = weighting_by_output.get(column.column_name)
                source = (
                    output_weighting.uncertainty_source
                    if output_weighting is not None
                    else CalibrationUncertaintySource.UNKNOWN
                )
                known = source is not CalibrationUncertaintySource.UNKNOWN
                if (
                    experiment.objective_weighting is CalibrationObjectiveWeighting.INVERSE_VARIANCE
                    and not known
                ):
                    findings.append(
                        CalibrationFinding(
                            severity=CalibrationFindingSeverity.ERROR,
                            category=(
                                CalibrationFindingCategory
                                .INVERSE_VARIANCE_WEIGHTING_REQUIRES_KNOWN_UNCERTAINTY
                            ),
                            message=(
                                f"Experiment {experiment.id} declares INVERSE_VARIANCE "
                                f"objective weighting, but output {column.column_name!r} has "
                                "no known (MEASURED/USER_ASSUMED) uncertainty source."
                            ),
                            involved_arm_ids=[arm.id],
                            involved_experiment_ids=[experiment.id],
                        )
                    )
                if (
                    experiment.objective_weighting is CalibrationObjectiveWeighting.INVERSE_VARIANCE
                    and source is CalibrationUncertaintySource.MEASURED
                ):
                    problem_rows = _measured_uncertainty_nonpositive_row_count(
                        experiment.time_series_dataset, column.column_name
                    )
                    if problem_rows:
                        findings.append(
                            CalibrationFinding(
                                severity=CalibrationFindingSeverity.ERROR,
                                category=(
                                    CalibrationFindingCategory
                                    .MEASURED_UNCERTAINTY_NOT_STRICTLY_POSITIVE
                                ),
                                message=(
                                    f"Output {column.column_name!r} on experiment "
                                    f"{experiment.id} declares MEASURED uncertainty under "
                                    "INVERSE_VARIANCE weighting, but "
                                    f"{problem_rows} observation(s) have a zero, negative, or "
                                    "missing uncertainty value -- inverse-variance weighting "
                                    "is undefined or meaningless for those observations."
                                ),
                                involved_arm_ids=[arm.id],
                                involved_experiment_ids=[experiment.id],
                            )
                        )
                if (
                    experiment.objective_weighting is CalibrationObjectiveWeighting.UNWEIGHTED
                    and known
                ):
                    findings.append(
                        CalibrationFinding(
                            severity=CalibrationFindingSeverity.WARNING,
                            category=(
                                CalibrationFindingCategory
                                .UNWEIGHTED_POLICY_IGNORES_DECLARED_UNCERTAINTY
                            ),
                            message=(
                                f"Output {column.column_name!r} on experiment "
                                f"{experiment.id} has a declared {source.value} uncertainty, "
                                "but this experiment's objective weighting is UNWEIGHTED, so "
                                "it is not used in the fit."
                            ),
                            involved_arm_ids=[arm.id],
                            involved_experiment_ids=[experiment.id],
                        )
                    )
                if (
                    output_weighting is not None
                    and output_weighting.relative_output_weight != 1
                    and experiment.objective_weighting
                    is CalibrationObjectiveWeighting.INVERSE_VARIANCE
                    and known
                ):
                    findings.append(
                        CalibrationFinding(
                            severity=CalibrationFindingSeverity.INFO,
                            category=(
                                CalibrationFindingCategory
                                .OUTPUT_WEIGHT_AND_UNCERTAINTY_SCALING_BOTH_APPLY
                            ),
                            message=(
                                f"Output {column.column_name!r} on experiment "
                                f"{experiment.id} combines an explicit relative weight "
                                f"({output_weighting.relative_output_weight}) with "
                                "inverse-variance uncertainty scaling from its own declared "
                                "sigma -- these multiply together."
                            ),
                            involved_arm_ids=[arm.id],
                            involved_experiment_ids=[experiment.id],
                        )
                    )
    return findings


def compute_findings(job: CalibrationJob) -> list[CalibrationFinding]:
    """Every finding for this job's own current, in-memory state -- a pure read over
    already-loaded rows, computed fresh every time, never cached or stored (docs/29 §13)."""
    findings: list[CalibrationFinding] = []
    findings.extend(_completeness_findings(job))
    findings.extend(_dataset_reuse_findings(job))
    findings.extend(_parameter_role_findings(job))
    findings.extend(_uncertainty_weighting_findings(job))
    for arm in job.arms:
        findings.extend(_compatibility_findings_for_arm(arm))
    return findings


@dataclass(frozen=True, slots=True)
class ExecutionCapability:
    available: bool
    reason: str | None
    missing_capability: Literal["WHOLE_MODEL_EXECUTION"] | None


def execution_capability(job: CalibrationJob) -> ExecutionCapability:
    """Whether this job could actually be run, as a wholly separate check from configuration
    completeness (docs/29 §5 rule 5). Always unavailable in this increment: whole-model
    execution (`request_model_calibration`) does not exist yet at any arm count, so a
    single-arm job is blocked by exactly the same, named reason as a multi-arm one -- never a
    silent fallback to module-scoped execution."""
    del job  # every job in this increment is blocked identically; kept for signature clarity
    return ExecutionCapability(
        available=False,
        reason="Whole-model execution is not yet available for calibration.",
        missing_capability="WHOLE_MODEL_EXECUTION",
    )


def _build_snapshot_payload(job: CalibrationJob, findings: list[CalibrationFinding]) -> dict:
    """The complete, plain-dict content of one immutable ``CalibrationJobRevision`` -- every
    arm/experiment/variable-binding/parameter-role exactly as it stands right now, plus every
    finding computed at this exact moment (for provenance; never re-trusted as still current
    once read back). Built directly from the live ORM objects, deliberately independent of
    ``app.schemas.calibration`` (which itself imports this module) -- never a circular import,
    and this snapshot's own shape is allowed to drift from the live API response shape over
    time without either one needing to change the other."""
    return {
        "calibration_job_id": str(job.id),
        "arms": [
            {
                "id": str(arm.id),
                "model_id": str(arm.model_id),
                "model_name": arm.model.name,
                "role_label": arm.role_label,
                "experiments": [
                    {
                        "id": str(experiment.id),
                        "time_series_dataset_id": str(experiment.time_series_dataset_id),
                        "role": experiment.role.value,
                        "objective_weighting": experiment.objective_weighting.value,
                        "weighting_notes": experiment.weighting_notes,
                        "alias_mapping_revision_number": (
                            experiment.alias_mapping_revision.revision_number
                            if experiment.alias_mapping_revision is not None
                            else None
                        ),
                        "variable_bindings": [
                            {
                                "model_meaning": b.model_meaning.value,
                                "target_component_id": b.target_component_id,
                                "value_source": b.value_source.value,
                                "constant_value": (
                                    str(b.constant_value) if b.constant_value is not None else None
                                ),
                                "constant_unit": b.constant_unit,
                                "source_column_name": b.source_column_name,
                                "intervention_time": (
                                    str(b.intervention_time)
                                    if b.intervention_time is not None
                                    else None
                                ),
                            }
                            for b in experiment.variable_bindings
                        ],
                        "output_weightings": [
                            {
                                "output_column_name": w.output_column_name,
                                "uncertainty_source": w.uncertainty_source.value,
                                "assumed_sigma_value": (
                                    str(w.assumed_sigma_value)
                                    if w.assumed_sigma_value is not None
                                    else None
                                ),
                                "assumed_sigma_unit": w.assumed_sigma_unit,
                                "assumed_sigma_statistic_kind": (
                                    w.assumed_sigma_statistic_kind.value
                                    if w.assumed_sigma_statistic_kind is not None
                                    else None
                                ),
                                "relative_output_weight": str(w.relative_output_weight),
                                "provenance_note": w.provenance_note,
                            }
                            for w in experiment.output_weightings
                        ],
                    }
                    for experiment in arm.experiments
                ],
            }
            for arm in job.arms
        ],
        "parameter_roles": [
            {
                "parameter_name": role.parameter_name,
                "role": role.role.value,
                "catalog_validated": role.catalog_validated,
                "fixed_value": str(role.fixed_value) if role.fixed_value is not None else None,
                "lower_bound": str(role.lower_bound) if role.lower_bound is not None else None,
                "upper_bound": str(role.upper_bound) if role.upper_bound is not None else None,
                "unit": role.unit,
                "reference_arm_id": (
                    str(role.reference_arm_id) if role.reference_arm_id is not None else None
                ),
                "reference_parameter_name": role.reference_parameter_name,
                "coefficient_a": (
                    str(role.coefficient_a) if role.coefficient_a is not None else None
                ),
                "coefficient_a_is_fixed": role.coefficient_a_is_fixed,
                "coefficient_b": (
                    str(role.coefficient_b) if role.coefficient_b is not None else None
                ),
                "coefficient_b_is_fixed": role.coefficient_b_is_fixed,
                "arm_ids": [str(link.calibration_arm_id) for link in role.arm_links],
            }
            for role in job.parameter_roles
        ],
        "findings_at_capture_time": [
            {
                "severity": f.severity.value,
                "category": f.category.value,
                "message": f.message,
                "involved_arm_ids": [str(i) for i in f.involved_arm_ids],
                "involved_experiment_ids": [str(i) for i in f.involved_experiment_ids],
                "involved_parameter_role_ids": [str(i) for i in f.involved_parameter_role_ids],
            }
            for f in findings
        ],
    }


def complete_review(
    session: Session,
    *,
    job: CalibrationJob,
    expected_edit_version: int,
    updated_by: str | None = None,
) -> tuple[CalibrationJob, list[CalibrationFinding], CalibrationJobRevision]:
    """Mark review complete if and only if zero ``ERROR``-severity findings exist -- the
    configuration-completeness bar, wholly separate from (and insufficient for) execution
    (docs/29 §5 rule 5, §13). Raises ``CalibrationReviewBlocked`` otherwise, carrying every
    finding so the caller can report all of them, not just the first.

    **Captures a new, immutable ``CalibrationJobRevision``** (docs/31) -- the job's own
    complete configuration, frozen at this exact moment. A later draft edit (which drops
    ``status`` back to ``DRAFT``, per ``_bump``) never alters this row; completing review
    again later captures another, separate revision with the next ``revision_number``.
    """
    _check_version(job, expected_edit_version)
    findings = compute_findings(job)
    if any(f.severity is CalibrationFindingSeverity.ERROR for f in findings):
        raise CalibrationReviewBlocked(findings)
    # Deliberately not `_bump`: that helper always drops status back to DRAFT, which would
    # immediately undo the REVIEWED transition this function exists to make.
    job.edit_version += 1
    job.status = CalibrationJobStatus.REVIEWED
    job.reviewed_at = datetime.now(UTC)
    job.updated_by = updated_by

    next_revision_number = (
        session.execute(
            select(CalibrationJobRevision.revision_number)
            .where(CalibrationJobRevision.calibration_job_id == job.id)
            .order_by(CalibrationJobRevision.revision_number.desc())
            .limit(1)
        ).scalar_one_or_none()
        or 0
    ) + 1
    revision = CalibrationJobRevision(
        calibration_job_id=job.id,
        revision_number=next_revision_number,
        snapshot_payload=json.dumps(_build_snapshot_payload(job, findings)),
        created_by=updated_by,
    )
    session.add(revision)
    session.flush()
    return job, findings, revision


def list_job_revisions(session: Session, job_id: UUID) -> list[CalibrationJobRevision]:
    """Every immutable revision ever captured for one job, newest first. Read-only -- reopening
    never creates or mutates anything."""
    stmt = (
        select(CalibrationJobRevision)
        .where(CalibrationJobRevision.calibration_job_id == job_id)
        .order_by(CalibrationJobRevision.revision_number.desc())
    )
    return list(session.scalars(stmt))


def get_job_revision(
    session: Session, job_id: UUID, revision_number: int
) -> CalibrationJobRevision | None:
    """One specific, historical revision -- exactly as captured, never re-derived. Read-only."""
    return session.execute(
        select(CalibrationJobRevision).where(
            CalibrationJobRevision.calibration_job_id == job_id,
            CalibrationJobRevision.revision_number == revision_number,
        )
    ).scalar_one_or_none()


__all__ = [
    "CalibrationFinding",
    "CalibrationJobStaleEdit",
    "CalibrationReviewBlocked",
    "ExecutionCapability",
    "ReferencedArmNotRemovable",
    "add_arm",
    "add_experiment",
    "add_parameter_role",
    "add_variable_binding",
    "complete_review",
    "compute_findings",
    "create_job",
    "execution_capability",
    "get_job",
    "get_job_for_subproject",
    "get_job_revision",
    "list_job_revisions",
    "list_jobs_for_subproject",
    "remove_arm",
    "remove_experiment",
    "remove_experiment_output_weighting",
    "remove_parameter_role",
    "remove_variable_binding",
    "set_experiment_mapping",
    "set_experiment_objective_weighting",
    "set_experiment_output_weighting",
    "set_experiment_role",
]
