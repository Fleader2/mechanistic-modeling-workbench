"""Tests for ``app.persistence.calibration`` -- the Joint Calibration Workflow
configuration-only increment, and the docs/31 configuration-prerequisites revision on top of
it (independent-variable bindings, parameter-catalog validation, immutable job revisions, and
the differing-conditions-never-blocks-saving audit fix). See
``docs/29_joint_calibration_workflow_design.md``, ``docs/30
_joint_calibration_configuration_increment.md``, ``docs/31
_joint_calibration_configuration_prerequisites_increment.md``.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.models.enums import (
    CalibrationBindingModelMeaning,
    CalibrationBindingValueSource,
    CalibrationExperimentRole,
    CalibrationFindingCategory,
    CalibrationFindingSeverity,
    CalibrationObjectiveWeighting,
    CalibrationParameterRoleKind,
    CalibrationUncertaintySource,
    ModelParameterCatalogStatus,
    ModelParameterKind,
    ModelSpeciesCatalogStatus,
    RunStage,
    UncertaintyStatisticKind,
)
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
    get_job,
    get_job_revision,
    list_job_revisions,
    remove_arm,
    remove_experiment_output_weighting,
    set_experiment_mapping,
    set_experiment_objective_weighting,
    set_experiment_output_weighting,
)
from app.persistence.dataset_model_alias_mapping import AssignmentInput, save_mapping_revision
from app.persistence.model_parameter_catalog import (
    CapturedParameter,
    persist_model_parameter_catalog,
)
from app.persistence.model_species_catalog import (
    CapturedSpecies,
    get_model_species_catalog,
    persist_model_species_catalog,
)
from app.persistence.run_record import create_run_record
from app.persistence.time_series_dataset import get_time_series_dataset, persist_time_series_dataset
from tests.persistence.conftest import make_model_id, make_project_id, make_subproject_id
from tests.time_series_helpers import (
    blank_template_bytes,
    declare_independent_variables,
    declare_measurement_columns,
    declare_measurement_uncertainty,
    fixture_workbook_bytes,
    populate_data_tab,
)

pytestmark = pytest.mark.database


def _run_record_id(db_session, *, subproject_id, model_id):
    run = create_run_record(
        subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session, model_id=model_id
    )
    db_session.flush()
    return run.id


def _seed_dataset(
    db_session, *, project_id, subproject_id, filename="ras_mapk.xlsx", workbook_bytes=None
):
    result = persist_time_series_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename=filename,
        workbook_bytes=workbook_bytes if workbook_bytes is not None else fixture_workbook_bytes(),
    )
    return get_time_series_dataset(db_session, result.entity_id)


def _seed_available_species_catalog(
    db_session, *, subproject_id, model_id, species_ids=("s_aRAStot", "s_pMEKtot")
):
    persist_model_species_catalog(
        session=db_session,
        model_id=model_id,
        source_run_record_id=_run_record_id(
            db_session, subproject_id=subproject_id, model_id=model_id
        ),
        status=ModelSpeciesCatalogStatus.AVAILABLE,
        species=[
            CapturedSpecies(
                antimony_species_id=species_id,
                canonical_species_id=f"canonical-{species_id}",
                display_name=species_id,
                compartment_id="c1",
                compartment_name="cyto",
                kind="FLOATING",
            )
            for species_id in species_ids
        ],
    )
    return get_model_species_catalog(db_session, model_id)


def _seed_available_parameter_catalog(
    db_session, *, subproject_id, model_id, independent=("k1",), derived=()
):
    persist_model_parameter_catalog(
        session=db_session,
        model_id=model_id,
        source_run_record_id=_run_record_id(
            db_session, subproject_id=subproject_id, model_id=model_id
        ),
        status=ModelParameterCatalogStatus.AVAILABLE,
        parameters=[
            CapturedParameter(
                antimony_parameter_id=name,
                canonical_parameter_id=f"canonical-{name}",
                display_name=name,
                kind=ModelParameterKind.INDEPENDENT.value,
                unit="1/s",
            )
            for name in independent
        ]
        + [
            CapturedParameter(
                antimony_parameter_id=name,
                canonical_parameter_id=f"canonical-{name}",
                display_name=name,
                kind=ModelParameterKind.DERIVED.value,
            )
            for name in derived
        ],
    )


def _fully_assigned_mapping(db_session, *, dataset, catalog):
    return save_mapping_revision(
        session=db_session,
        dataset=dataset,
        model_species_catalog=catalog,
        assignments=[
            AssignmentInput(
                column_name="[aRAStot]",
                status="ASSIGNED",
                target_antimony_species_id="s_aRAStot",
            )
        ],
        expected_revision_number=0,
    )


class TestArmsAndExperiments:
    def test_adding_an_experiment_auto_pins_an_existing_current_mapping(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        catalog = _seed_available_species_catalog(
            db_session, subproject_id=subproject_id, model_id=model_id
        )
        dataset = _seed_dataset(db_session, project_id=project_id, subproject_id=subproject_id)
        _fully_assigned_mapping(db_session, dataset=dataset, catalog=catalog)

        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        experiment = add_experiment(
            db_session, job=job, arm=arm, time_series_dataset_id=dataset.id, expected_edit_version=1
        )

        assert experiment.alias_mapping_revision_id is not None
        assert experiment.alias_mapping_revision.revision_number == 1
        assert job.edit_version == 2

    def test_adding_an_experiment_with_no_mapping_yet_leaves_it_unpinned(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        dataset = _seed_dataset(db_session, project_id=project_id, subproject_id=subproject_id)

        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        experiment = add_experiment(
            db_session, job=job, arm=arm, time_series_dataset_id=dataset.id, expected_edit_version=1
        )
        assert experiment.alias_mapping_revision_id is None

        catalog = _seed_available_species_catalog(
            db_session, subproject_id=subproject_id, model_id=model_id
        )
        revision = _fully_assigned_mapping(db_session, dataset=dataset, catalog=catalog)
        set_experiment_mapping(
            db_session,
            job=job,
            experiment_id=experiment.id,
            alias_mapping_revision_number=revision.revision_number,
            expected_edit_version=2,
        )
        assert experiment.alias_mapping_revision_id == revision.id

    def test_a_stale_expected_edit_version_is_rejected(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job = create_job(db_session, subproject_id=subproject_id)
        add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)

        with pytest.raises(CalibrationJobStaleEdit):
            add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)

    def test_removing_an_arm_referenced_by_a_parameter_link_is_rejected(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id_a = make_model_id(db_session, subproject_id=subproject_id)
        model_id_b = make_model_id(db_session, subproject_id=subproject_id)
        job = create_job(db_session, subproject_id=subproject_id)
        arm_a = add_arm(db_session, job=job, model_id=model_id_a, expected_edit_version=0)
        arm_b = add_arm(db_session, job=job, model_id=model_id_b, expected_edit_version=1)
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="kcat",
            role=CalibrationParameterRoleKind.EXACT_EQUALITY,
            arm_ids=[arm_b.id],
            reference_arm_id=arm_a.id,
            reference_parameter_name="kcat",
            expected_edit_version=2,
        )

        with pytest.raises(ReferencedArmNotRemovable):
            remove_arm(db_session, job=job, arm_id=arm_a.id, expected_edit_version=3)


class TestVariableBindings:
    def test_an_initial_value_binding_is_validated_against_the_real_species_catalog(
        self, db_session
    ):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        _seed_available_species_catalog(db_session, subproject_id=subproject_id, model_id=model_id)
        dataset = _seed_dataset(db_session, project_id=project_id, subproject_id=subproject_id)

        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        experiment = add_experiment(
            db_session, job=job, arm=arm, time_series_dataset_id=dataset.id, expected_edit_version=1
        )

        binding = add_variable_binding(
            db_session,
            job=job,
            experiment_id=experiment.id,
            model_meaning=CalibrationBindingModelMeaning.INITIAL_VALUE,
            target_component_id="s_aRAStot",
            value_source=CalibrationBindingValueSource.CONSTANT,
            constant_value=Decimal("1.5"),
            expected_edit_version=2,
        )
        assert binding.target_component_id == "s_aRAStot"

        with pytest.raises(ValueError, match="not a real"):
            add_variable_binding(
                db_session,
                job=job,
                experiment_id=experiment.id,
                model_meaning=CalibrationBindingModelMeaning.INITIAL_VALUE,
                target_component_id="s_not_real",
                value_source=CalibrationBindingValueSource.CONSTANT,
                constant_value=Decimal("1.0"),
                expected_edit_version=3,
            )

    def test_a_parameter_override_binding_is_validated_against_the_real_parameter_catalog(
        self, db_session
    ):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        _seed_available_parameter_catalog(
            db_session, subproject_id=subproject_id, model_id=model_id, independent=("k1",),
            derived=("Vmax",),
        )
        dataset = _seed_dataset(db_session, project_id=project_id, subproject_id=subproject_id)

        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        experiment = add_experiment(
            db_session, job=job, arm=arm, time_series_dataset_id=dataset.id, expected_edit_version=1
        )

        binding = add_variable_binding(
            db_session,
            job=job,
            experiment_id=experiment.id,
            model_meaning=CalibrationBindingModelMeaning.PARAMETER_OVERRIDE,
            target_component_id="k1",
            value_source=CalibrationBindingValueSource.CONSTANT,
            constant_value=Decimal("0.2"),
            expected_edit_version=2,
        )
        assert binding.target_component_id == "k1"

        with pytest.raises(ValueError, match="derived"):
            add_variable_binding(
                db_session,
                job=job,
                experiment_id=experiment.id,
                model_meaning=CalibrationBindingModelMeaning.PARAMETER_OVERRIDE,
                target_component_id="Vmax",
                value_source=CalibrationBindingValueSource.CONSTANT,
                constant_value=Decimal("0.2"),
                expected_edit_version=3,
            )

    def test_a_binding_with_no_relevant_catalog_available_is_curator_declared(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        dataset = _seed_dataset(db_session, project_id=project_id, subproject_id=subproject_id)

        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        experiment = add_experiment(
            db_session, job=job, arm=arm, time_series_dataset_id=dataset.id, expected_edit_version=1
        )
        # No parameter catalog at all exists for this model -- a PARAMETER_OVERRIDE binding
        # must still be accepted as curator-declared free text, never blocked by a missing
        # catalog.
        binding = add_variable_binding(
            db_session,
            job=job,
            experiment_id=experiment.id,
            model_meaning=CalibrationBindingModelMeaning.PARAMETER_OVERRIDE,
            target_component_id="k_made_up_by_curator",
            value_source=CalibrationBindingValueSource.CONSTANT,
            constant_value=Decimal("0.5"),
            expected_edit_version=2,
        )
        assert binding.target_component_id == "k_made_up_by_curator"

    def test_a_dataset_column_binding_requires_a_real_declared_independent_variable_column(
        self, db_session
    ):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        _seed_available_species_catalog(db_session, subproject_id=subproject_id, model_id=model_id)
        data = populate_data_tab(
            blank_template_bytes(),
            headers=("time", "dose_uM", "glucose_mM"),
            rows=((0, 10.0, 1.0),),
        )
        data = declare_independent_variables(data, {"dose_uM": ("uM", None)})
        dataset = _seed_dataset(
            db_session, project_id=project_id, subproject_id=subproject_id, workbook_bytes=data
        )

        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        experiment = add_experiment(
            db_session, job=job, arm=arm, time_series_dataset_id=dataset.id, expected_edit_version=1
        )

        binding = add_variable_binding(
            db_session,
            job=job,
            experiment_id=experiment.id,
            model_meaning=CalibrationBindingModelMeaning.INTERVENTION,
            target_component_id="s_aRAStot",
            value_source=CalibrationBindingValueSource.DATASET_COLUMN,
            source_column_name="dose_uM",
            expected_edit_version=2,
        )
        assert binding.source_column_name == "dose_uM"

        with pytest.raises(ValueError, match="not a declared independent-variable column"):
            add_variable_binding(
                db_session,
                job=job,
                experiment_id=experiment.id,
                model_meaning=CalibrationBindingModelMeaning.INTERVENTION,
                target_component_id="s_aRAStot",
                value_source=CalibrationBindingValueSource.DATASET_COLUMN,
                source_column_name="not_a_real_column",
                expected_edit_version=3,
            )


def _seed_single_output_experiment(
    db_session, *, declare_uncertainty=False, declare_unit=None, mapped=False
):
    """One job with one arm and one experiment, pinned to a dataset with exactly one
    measurement column (``glucose_mM``) -- the minimal fixture the output-weighting tests
    need, so declaring INVERSE_VARIANCE never also requires declaring every other output of a
    richer fixture dataset. ``mapped=True`` additionally seeds a real, AVAILABLE species
    catalog and a fully-assigned alias mapping, for tests that need ``complete_review`` to
    actually succeed (configuration-completeness is otherwise orthogonal to this module's own
    uncertainty/weighting findings, and is deliberately left unmet by default here)."""
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=subproject_id)
    headers = ["time", "glucose_mM"]
    rows = [(0, 1.0), (60, 2.0)]
    if declare_uncertainty:
        headers.append("glucose_mM__sigma")
        rows = [(0, 1.0, 0.1), (60, 2.0, 0.2)]
    data = populate_data_tab(
        blank_template_bytes(), headers=tuple(headers), rows=tuple(rows)
    )
    if declare_unit is not None:
        data = declare_measurement_columns(data, {"glucose_mM": (declare_unit, None)})
    if declare_uncertainty:
        data = declare_measurement_uncertainty(
            data, {"glucose_mM__sigma": ("glucose_mM", "SD", declare_unit, None)}
        )
    dataset = _seed_dataset(
        db_session, project_id=project_id, subproject_id=subproject_id, workbook_bytes=data
    )
    job = create_job(db_session, subproject_id=subproject_id)
    arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
    if mapped:
        catalog = _seed_available_species_catalog(
            db_session, subproject_id=subproject_id, model_id=model_id, species_ids=("s_glucose",)
        )
        save_mapping_revision(
            session=db_session,
            dataset=dataset,
            model_species_catalog=catalog,
            assignments=[
                AssignmentInput(
                    column_name="glucose_mM",
                    status="ASSIGNED",
                    target_antimony_species_id="s_glucose",
                )
            ],
            expected_revision_number=0,
        )
    experiment = add_experiment(
        db_session, job=job, arm=arm, time_series_dataset_id=dataset.id, expected_edit_version=1
    )
    return job, arm, experiment


class TestOutputWeighting:
    """``docs/32``'s minimal error/weighting contract -- ``set_experiment_output_weighting``/
    ``remove_experiment_output_weighting``."""

    def test_rejects_an_output_column_name_not_on_the_pinned_dataset(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        with pytest.raises(ValueError, match="not a measurement column"):
            set_experiment_output_weighting(
                db_session,
                job=job,
                experiment_id=experiment.id,
                output_column_name="not_a_real_output",
                uncertainty_source=CalibrationUncertaintySource.UNKNOWN,
                expected_edit_version=job.edit_version,
            )

    def test_measured_requires_the_dataset_to_declare_an_uncertainty_column(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session, declare_uncertainty=False)
        with pytest.raises(ValueError, match="declares no measurement-uncertainty column"):
            set_experiment_output_weighting(
                db_session,
                job=job,
                experiment_id=experiment.id,
                output_column_name="glucose_mM",
                uncertainty_source=CalibrationUncertaintySource.MEASURED,
                expected_edit_version=job.edit_version,
            )

    def test_measured_succeeds_when_the_dataset_declares_a_matching_uncertainty_column(
        self, db_session
    ):
        job, _, experiment = _seed_single_output_experiment(db_session, declare_uncertainty=True)
        weighting = set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.MEASURED,
            expected_edit_version=job.edit_version,
        )
        assert weighting.uncertainty_source is CalibrationUncertaintySource.MEASURED
        assert weighting.assumed_sigma_value is None
        assert weighting.relative_output_weight == 1

    def test_measured_rejects_a_sigma_value_supplied_alongside_it(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session, declare_uncertainty=True)
        with pytest.raises(ValueError, match="exactly one uncertainty source"):
            set_experiment_output_weighting(
                db_session,
                job=job,
                experiment_id=experiment.id,
                output_column_name="glucose_mM",
                uncertainty_source=CalibrationUncertaintySource.MEASURED,
                assumed_sigma_value=Decimal("0.1"),
                expected_edit_version=job.edit_version,
            )

    def test_user_assumed_requires_a_positive_sigma_value(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        with pytest.raises(ValueError, match="assumed_sigma_value must be > 0"):
            set_experiment_output_weighting(
                db_session,
                job=job,
                experiment_id=experiment.id,
                output_column_name="glucose_mM",
                uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
                assumed_sigma_value=Decimal("0"),
                assumed_sigma_statistic_kind=UncertaintyStatisticKind.STANDARD_DEVIATION,
                expected_edit_version=job.edit_version,
            )

    def test_user_assumed_rejects_a_non_finite_sigma_value(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        with pytest.raises(ValueError, match="finite"):
            set_experiment_output_weighting(
                db_session,
                job=job,
                experiment_id=experiment.id,
                output_column_name="glucose_mM",
                uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
                assumed_sigma_value=Decimal("Infinity"),
                assumed_sigma_statistic_kind=UncertaintyStatisticKind.STANDARD_DEVIATION,
                expected_edit_version=job.edit_version,
            )

    def test_user_assumed_requires_a_declared_statistic_kind(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        with pytest.raises(ValueError, match="assumed_sigma_statistic_kind"):
            set_experiment_output_weighting(
                db_session,
                job=job,
                experiment_id=experiment.id,
                output_column_name="glucose_mM",
                uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
                assumed_sigma_value=Decimal("0.1"),
                expected_edit_version=job.edit_version,
            )

    def test_non_finite_relative_output_weight_is_rejected(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        with pytest.raises(ValueError, match="finite"):
            set_experiment_output_weighting(
                db_session,
                job=job,
                experiment_id=experiment.id,
                output_column_name="glucose_mM",
                uncertainty_source=CalibrationUncertaintySource.UNKNOWN,
                relative_output_weight=Decimal("NaN"),
                expected_edit_version=job.edit_version,
            )

    def test_user_assumed_sigma_unit_incompatible_with_output_unit_is_rejected(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session, declare_unit="mM")
        with pytest.raises(ValueError, match="dimensionally incompatible"):
            set_experiment_output_weighting(
                db_session,
                job=job,
                experiment_id=experiment.id,
                output_column_name="glucose_mM",
                uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
                assumed_sigma_value=Decimal("0.1"),
                assumed_sigma_unit="seconds",
                assumed_sigma_statistic_kind=UncertaintyStatisticKind.STANDARD_DEVIATION,
                expected_edit_version=job.edit_version,
            )

    def test_user_assumed_with_a_compatible_unit_succeeds(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session, declare_unit="mM")
        weighting = set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
            assumed_sigma_value=Decimal("0.1"),
            assumed_sigma_unit="mM",
            assumed_sigma_statistic_kind=UncertaintyStatisticKind.STANDARD_DEVIATION,
            provenance_note="assumed 10% from literature",
            expected_edit_version=job.edit_version,
        )
        assert weighting.assumed_sigma_value == Decimal("0.1")
        assert weighting.assumed_sigma_statistic_kind == UncertaintyStatisticKind.STANDARD_DEVIATION
        assert weighting.provenance_note == "assumed 10% from literature"

    def test_unknown_rejects_a_sigma_value_supplied_alongside_it(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        with pytest.raises(ValueError, match="must not also carry"):
            set_experiment_output_weighting(
                db_session,
                job=job,
                experiment_id=experiment.id,
                output_column_name="glucose_mM",
                uncertainty_source=CalibrationUncertaintySource.UNKNOWN,
                assumed_sigma_value=Decimal("0.1"),
                expected_edit_version=job.edit_version,
            )

    def test_non_positive_relative_output_weight_is_rejected(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        with pytest.raises(ValueError, match="relative_output_weight"):
            set_experiment_output_weighting(
                db_session,
                job=job,
                experiment_id=experiment.id,
                output_column_name="glucose_mM",
                uncertainty_source=CalibrationUncertaintySource.UNKNOWN,
                relative_output_weight=Decimal("0"),
                expected_edit_version=job.edit_version,
            )

    def test_setting_it_twice_upserts_rather_than_duplicating(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
            assumed_sigma_value=Decimal("0.1"),
            assumed_sigma_statistic_kind=UncertaintyStatisticKind.STANDARD_DEVIATION,
            expected_edit_version=job.edit_version,
        )
        set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
            assumed_sigma_value=Decimal("0.2"),
            assumed_sigma_statistic_kind=UncertaintyStatisticKind.STANDARD_DEVIATION,
            relative_output_weight=Decimal("2"),
            expected_edit_version=job.edit_version,
        )
        assert len(experiment.output_weightings) == 1
        assert experiment.output_weightings[0].assumed_sigma_value == Decimal("0.2")
        assert experiment.output_weightings[0].relative_output_weight == 2

    def test_removing_it_reverts_to_the_no_declaration_default(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        weighting = set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
            assumed_sigma_value=Decimal("0.1"),
            assumed_sigma_statistic_kind=UncertaintyStatisticKind.STANDARD_DEVIATION,
            expected_edit_version=job.edit_version,
        )
        remove_experiment_output_weighting(
            db_session,
            job=job,
            weighting_id=weighting.id,
            expected_edit_version=job.edit_version,
        )
        assert experiment.output_weightings == []


class TestUncertaintyWeightingFindings:
    """``docs/32``'s minimal error/weighting contract -- the review findings
    ``_uncertainty_weighting_findings`` computes."""

    def test_inverse_variance_without_a_known_uncertainty_is_blocking(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        set_experiment_objective_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            objective_weighting=CalibrationObjectiveWeighting.INVERSE_VARIANCE,
            expected_edit_version=job.edit_version,
        )
        findings = compute_findings(get_job(db_session, job.id))
        matching = [
            f
            for f in findings
            if f.category
            is CalibrationFindingCategory.INVERSE_VARIANCE_WEIGHTING_REQUIRES_KNOWN_UNCERTAINTY
        ]
        assert len(matching) == 1
        assert matching[0].severity is CalibrationFindingSeverity.ERROR

    def test_measured_uncertainty_with_a_zero_value_is_blocking_under_inverse_variance(
        self, db_session
    ):
        """task instructions: "zero must not produce infinite weight" -- a real, reported
        zero uncertainty for an observation that does have a real measurement must block
        INVERSE_VARIANCE, never silently produce (or ignore) an infinite weight."""
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        data = populate_data_tab(
            blank_template_bytes(),
            headers=("time", "glucose_mM", "glucose_mM__sigma"),
            rows=((0, 1.0, 0.0), (60, 2.0, 0.2)),
        )
        data = declare_measurement_uncertainty(
            data, {"glucose_mM__sigma": ("glucose_mM", "SD", None, None)}
        )
        dataset = _seed_dataset(
            db_session, project_id=project_id, subproject_id=subproject_id, workbook_bytes=data
        )
        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        experiment = add_experiment(
            db_session, job=job, arm=arm, time_series_dataset_id=dataset.id, expected_edit_version=1
        )
        set_experiment_objective_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            objective_weighting=CalibrationObjectiveWeighting.INVERSE_VARIANCE,
            expected_edit_version=job.edit_version,
        )
        set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.MEASURED,
            expected_edit_version=job.edit_version,
        )
        findings = compute_findings(get_job(db_session, job.id))
        matching = [
            f
            for f in findings
            if f.category is CalibrationFindingCategory.MEASURED_UNCERTAINTY_NOT_STRICTLY_POSITIVE
        ]
        assert len(matching) == 1
        assert matching[0].severity is CalibrationFindingSeverity.ERROR
        assert "1 observation" in matching[0].message

    def test_measured_uncertainty_all_positive_has_no_such_finding(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session, declare_uncertainty=True)
        set_experiment_objective_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            objective_weighting=CalibrationObjectiveWeighting.INVERSE_VARIANCE,
            expected_edit_version=job.edit_version,
        )
        set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.MEASURED,
            expected_edit_version=job.edit_version,
        )
        findings = compute_findings(get_job(db_session, job.id))
        assert not any(
            f.category is CalibrationFindingCategory.MEASURED_UNCERTAINTY_NOT_STRICTLY_POSITIVE
            for f in findings
        )

    def test_inverse_variance_with_a_known_uncertainty_for_every_output_has_no_such_finding(
        self, db_session
    ):
        job, _, experiment = _seed_single_output_experiment(db_session)
        set_experiment_objective_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            objective_weighting=CalibrationObjectiveWeighting.INVERSE_VARIANCE,
            expected_edit_version=job.edit_version,
        )
        set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
            assumed_sigma_value=Decimal("0.1"),
            assumed_sigma_statistic_kind=UncertaintyStatisticKind.STANDARD_DEVIATION,
            expected_edit_version=job.edit_version,
        )
        findings = compute_findings(get_job(db_session, job.id))
        assert not any(
            f.category
            is CalibrationFindingCategory.INVERSE_VARIANCE_WEIGHTING_REQUIRES_KNOWN_UNCERTAINTY
            for f in findings
        )

    def test_unweighted_with_a_declared_uncertainty_is_a_warning_never_blocking(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
            assumed_sigma_value=Decimal("0.1"),
            assumed_sigma_statistic_kind=UncertaintyStatisticKind.STANDARD_DEVIATION,
            expected_edit_version=job.edit_version,
        )
        findings = compute_findings(get_job(db_session, job.id))
        matching = [
            f
            for f in findings
            if f.category
            is CalibrationFindingCategory.UNWEIGHTED_POLICY_IGNORES_DECLARED_UNCERTAINTY
        ]
        assert len(matching) == 1
        assert matching[0].severity is CalibrationFindingSeverity.WARNING

    def test_output_weight_and_uncertainty_scaling_both_apply_is_disclosed(self, db_session):
        job, _, experiment = _seed_single_output_experiment(db_session)
        set_experiment_objective_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            objective_weighting=CalibrationObjectiveWeighting.INVERSE_VARIANCE,
            expected_edit_version=job.edit_version,
        )
        set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
            assumed_sigma_value=Decimal("0.1"),
            assumed_sigma_statistic_kind=UncertaintyStatisticKind.STANDARD_DEVIATION,
            relative_output_weight=Decimal("2.5"),
            expected_edit_version=job.edit_version,
        )
        findings = compute_findings(get_job(db_session, job.id))
        matching = [
            f
            for f in findings
            if f.category
            is CalibrationFindingCategory.OUTPUT_WEIGHT_AND_UNCERTAINTY_SCALING_BOTH_APPLY
        ]
        assert len(matching) == 1
        assert matching[0].severity is CalibrationFindingSeverity.INFO

    def test_held_out_validation_experiments_are_excluded_from_these_findings(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        data = populate_data_tab(
            blank_template_bytes(), headers=("time", "glucose_mM"), rows=((0, 1.0),)
        )
        dataset = _seed_dataset(
            db_session, project_id=project_id, subproject_id=subproject_id, workbook_bytes=data
        )
        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        experiment = add_experiment(
            db_session,
            job=job,
            arm=arm,
            time_series_dataset_id=dataset.id,
            role=CalibrationExperimentRole.HELD_OUT_VALIDATION,
            expected_edit_version=1,
        )
        set_experiment_objective_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            objective_weighting=CalibrationObjectiveWeighting.INVERSE_VARIANCE,
            expected_edit_version=job.edit_version,
        )
        findings = compute_findings(get_job(db_session, job.id))
        assert not any(
            f.category
            is CalibrationFindingCategory.INVERSE_VARIANCE_WEIGHTING_REQUIRES_KNOWN_UNCERTAINTY
            for f in findings
        )


class TestParameterRoles:
    def test_fixed_requires_a_fixed_value(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)

        with pytest.raises(ValueError, match="fixed_value"):
            add_parameter_role(
                db_session,
                job=job,
                parameter_name="k1",
                role=CalibrationParameterRoleKind.FIXED,
                arm_ids=[arm.id],
                expected_edit_version=1,
            )

    def test_a_link_role_requires_a_reference_in_this_job(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)

        with pytest.raises(ValueError, match="reference_arm_id"):
            add_parameter_role(
                db_session,
                job=job,
                parameter_name="k1",
                role=CalibrationParameterRoleKind.EXACT_EQUALITY,
                arm_ids=[arm.id],
                expected_edit_version=1,
            )

    def test_model_specific_with_bounds_works_even_for_one_arm(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)

        role = add_parameter_role(
            db_session,
            job=job,
            parameter_name="k1",
            role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
            arm_ids=[arm.id],
            lower_bound=Decimal("0"),
            upper_bound=Decimal("10"),
            unit="1/s",
            expected_edit_version=1,
        )
        assert role.lower_bound == Decimal("0")
        assert role.catalog_validated is False
        assert [link.calibration_arm_id for link in role.arm_links] == [arm.id]

    def test_a_parameter_role_is_catalog_validated_when_a_real_catalog_exists(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        _seed_available_parameter_catalog(
            db_session, subproject_id=subproject_id, model_id=model_id, independent=("k1",)
        )
        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)

        role = add_parameter_role(
            db_session,
            job=job,
            parameter_name="k1",
            role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
            arm_ids=[arm.id],
            expected_edit_version=1,
        )
        assert role.catalog_validated is True

    def test_a_derived_parameter_is_rejected_as_a_role_target(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        _seed_available_parameter_catalog(
            db_session,
            subproject_id=subproject_id,
            model_id=model_id,
            independent=(),
            derived=("Vmax",),
        )
        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)

        with pytest.raises(ValueError, match="derived"):
            add_parameter_role(
                db_session,
                job=job,
                parameter_name="Vmax",
                role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
                arm_ids=[arm.id],
                expected_edit_version=1,
            )

    def test_a_name_absent_from_an_available_catalog_is_rejected(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        _seed_available_parameter_catalog(
            db_session, subproject_id=subproject_id, model_id=model_id, independent=("k1",)
        )
        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)

        with pytest.raises(ValueError, match="not a real"):
            add_parameter_role(
                db_session,
                job=job,
                parameter_name="k_nonexistent",
                role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
                arm_ids=[arm.id],
                expected_edit_version=1,
            )


class TestFindings:
    def _job_with_one_unmapped_arm(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job = create_job(db_session, subproject_id=subproject_id)
        add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        return get_job(db_session, job.id)

    def test_an_arm_with_no_mapped_experiment_is_flagged(self, db_session):
        job = self._job_with_one_unmapped_arm(db_session)
        findings = compute_findings(job)
        categories = {f.category for f in findings}
        assert CalibrationFindingCategory.ARM_WITHOUT_MAPPED_EXPERIMENT in categories
        assert CalibrationFindingCategory.NO_FREE_PARAMETER_TO_FIT in categories
        assert all(f.severity is CalibrationFindingSeverity.ERROR for f in findings)

    def test_complete_review_is_blocked_while_error_findings_exist(self, db_session):
        job = self._job_with_one_unmapped_arm(db_session)
        with pytest.raises(CalibrationReviewBlocked) as excinfo:
            complete_review(db_session, job=job, expected_edit_version=job.edit_version)
        assert len(excinfo.value.findings) >= 1

    def test_complete_review_succeeds_once_configuration_is_internally_consistent(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        catalog = _seed_available_species_catalog(
            db_session, subproject_id=subproject_id, model_id=model_id
        )
        dataset = _seed_dataset(db_session, project_id=project_id, subproject_id=subproject_id)
        _fully_assigned_mapping(db_session, dataset=dataset, catalog=catalog)

        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        add_experiment(
            db_session, job=job, arm=arm, time_series_dataset_id=dataset.id, expected_edit_version=1
        )
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="k1",
            role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
            arm_ids=[arm.id],
            expected_edit_version=2,
        )

        job, findings, revision = complete_review(db_session, job=job, expected_edit_version=3)
        assert findings == [] or all(
            f.severity is not CalibrationFindingSeverity.ERROR for f in findings
        )
        assert job.status.value == "REVIEWED"
        assert job.reviewed_at is not None
        assert revision.revision_number == 1

        capability = execution_capability(job)
        assert capability.available is False
        assert capability.missing_capability == "WHOLE_MODEL_EXECUTION"

    def test_any_further_edit_drops_review_back_to_draft(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        catalog = _seed_available_species_catalog(
            db_session, subproject_id=subproject_id, model_id=model_id
        )
        dataset = _seed_dataset(db_session, project_id=project_id, subproject_id=subproject_id)
        _fully_assigned_mapping(db_session, dataset=dataset, catalog=catalog)

        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        add_experiment(
            db_session, job=job, arm=arm, time_series_dataset_id=dataset.id, expected_edit_version=1
        )
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="k1",
            role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
            arm_ids=[arm.id],
            expected_edit_version=2,
        )
        job, _, _ = complete_review(db_session, job=job, expected_edit_version=3)
        assert job.status.value == "REVIEWED"

        add_arm(db_session, job=job, model_id=model_id, expected_edit_version=job.edit_version)
        assert job.status.value == "DRAFT"

    def test_calibration_and_validation_dataset_reuse_is_flagged(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        dataset = _seed_dataset(db_session, project_id=project_id, subproject_id=subproject_id)

        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        add_experiment(
            db_session,
            job=job,
            arm=arm,
            time_series_dataset_id=dataset.id,
            role=CalibrationExperimentRole.CALIBRATION,
            expected_edit_version=1,
        )
        add_experiment(
            db_session,
            job=job,
            arm=arm,
            time_series_dataset_id=dataset.id,
            role=CalibrationExperimentRole.HELD_OUT_VALIDATION,
            expected_edit_version=2,
        )
        findings = compute_findings(get_job(db_session, job.id))
        assert any(
            f.category is CalibrationFindingCategory.CALIBRATION_VALIDATION_DATASET_REUSE
            for f in findings
        )

    def test_ambiguous_same_name_parameter_across_arms_is_flagged(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id_a = make_model_id(db_session, subproject_id=subproject_id)
        model_id_b = make_model_id(db_session, subproject_id=subproject_id)
        job = create_job(db_session, subproject_id=subproject_id)
        arm_a = add_arm(db_session, job=job, model_id=model_id_a, expected_edit_version=0)
        arm_b = add_arm(db_session, job=job, model_id=model_id_b, expected_edit_version=1)
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="kcat",
            role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
            arm_ids=[arm_a.id],
            expected_edit_version=2,
        )
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="kcat",
            role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
            arm_ids=[arm_b.id],
            expected_edit_version=3,
        )
        findings = compute_findings(get_job(db_session, job.id))
        assert any(
            f.category is CalibrationFindingCategory.AMBIGUOUS_SAME_NAME_PARAMETER for f in findings
        )

    def test_a_parameter_role_cycle_is_detected(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id_a = make_model_id(db_session, subproject_id=subproject_id)
        model_id_b = make_model_id(db_session, subproject_id=subproject_id)
        job = create_job(db_session, subproject_id=subproject_id)
        arm_a = add_arm(db_session, job=job, model_id=model_id_a, expected_edit_version=0)
        arm_b = add_arm(db_session, job=job, model_id=model_id_b, expected_edit_version=1)
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="k1",
            role=CalibrationParameterRoleKind.EXACT_EQUALITY,
            arm_ids=[arm_a.id],
            reference_arm_id=arm_b.id,
            reference_parameter_name="k1",
            expected_edit_version=2,
        )
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="k1",
            role=CalibrationParameterRoleKind.EXACT_EQUALITY,
            arm_ids=[arm_b.id],
            reference_arm_id=arm_a.id,
            reference_parameter_name="k1",
            expected_edit_version=3,
        )
        findings = compute_findings(get_job(db_session, job.id))
        assert any(f.category is CalibrationFindingCategory.PARAMETER_ROLE_CYCLE for f in findings)

    def test_an_affine_link_with_incompatible_units_is_flagged(self, db_session):
        subproject_id = make_subproject_id(db_session)
        model_id_a = make_model_id(db_session, subproject_id=subproject_id)
        model_id_b = make_model_id(db_session, subproject_id=subproject_id)
        job = create_job(db_session, subproject_id=subproject_id)
        arm_a = add_arm(db_session, job=job, model_id=model_id_a, expected_edit_version=0)
        arm_b = add_arm(db_session, job=job, model_id=model_id_b, expected_edit_version=1)
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="k1",
            role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
            arm_ids=[arm_a.id],
            unit="1/s",
            expected_edit_version=2,
        )
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="k1_drug",
            role=CalibrationParameterRoleKind.EXACT_AFFINE_LINK,
            arm_ids=[arm_b.id],
            reference_arm_id=arm_a.id,
            reference_parameter_name="k1",
            coefficient_a=Decimal("1.0"),
            coefficient_a_is_fixed=True,
            coefficient_b=Decimal("0"),
            coefficient_b_is_fixed=True,
            unit="mM",
            expected_edit_version=3,
        )
        findings = compute_findings(get_job(db_session, job.id))
        assert any(
            f.category is CalibrationFindingCategory.UNIT_INCOMPATIBLE_LINK for f in findings
        )

    def test_differing_conditions_are_a_warning_never_a_blocking_error(self, db_session):
        """docs/31 audit fix: differing conditions/bindings/observation-mapping targets
        between two experiments on the same arm must never block configuration saving --
        only unsupported *execution* stays blocked (§5 rule 5)."""
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        catalog = _seed_available_species_catalog(
            db_session, subproject_id=subproject_id, model_id=model_id
        )
        dataset_1 = _seed_dataset(
            db_session, project_id=project_id, subproject_id=subproject_id, filename="a.xlsx"
        )
        dataset_2 = _seed_dataset(
            db_session, project_id=project_id, subproject_id=subproject_id, filename="b.xlsx"
        )
        _fully_assigned_mapping(db_session, dataset=dataset_1, catalog=catalog)

        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        experiment_1 = add_experiment(
            db_session,
            job=job,
            arm=arm,
            time_series_dataset_id=dataset_1.id,
            expected_edit_version=1,
        )
        experiment_2 = add_experiment(
            db_session,
            job=job,
            arm=arm,
            time_series_dataset_id=dataset_2.id,
            expected_edit_version=2,
        )
        add_variable_binding(
            db_session,
            job=job,
            experiment_id=experiment_1.id,
            model_meaning=CalibrationBindingModelMeaning.INITIAL_VALUE,
            target_component_id="s_aRAStot",
            value_source=CalibrationBindingValueSource.CONSTANT,
            constant_value=Decimal("1.0"),
            expected_edit_version=3,
        )
        del experiment_2
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="k1",
            role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
            arm_ids=[arm.id],
            expected_edit_version=4,
        )

        job = get_job(db_session, job.id)
        findings = compute_findings(job)
        incompatible = [
            f
            for f in findings
            if f.category is CalibrationFindingCategory.INCOMPATIBLE_EXPERIMENTS_MERGED
        ]
        assert incompatible
        assert all(f.severity is CalibrationFindingSeverity.WARNING for f in incompatible)

        # Never blocks "Complete review" -- the whole point of this audit fix.
        job, review_findings, _revision = complete_review(
            db_session, job=job, expected_edit_version=job.edit_version
        )
        assert job.status.value == "REVIEWED"
        assert any(
            f.category is CalibrationFindingCategory.INCOMPATIBLE_EXPERIMENTS_MERGED
            for f in review_findings
        )


class TestJobRevisions:
    def test_a_later_edit_never_changes_an_earlier_captured_revision(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        catalog = _seed_available_species_catalog(
            db_session, subproject_id=subproject_id, model_id=model_id
        )
        dataset = _seed_dataset(db_session, project_id=project_id, subproject_id=subproject_id)
        _fully_assigned_mapping(db_session, dataset=dataset, catalog=catalog)

        job = create_job(db_session, subproject_id=subproject_id)
        arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=0)
        add_experiment(
            db_session, job=job, arm=arm, time_series_dataset_id=dataset.id, expected_edit_version=1
        )
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="k1",
            role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
            arm_ids=[arm.id],
            expected_edit_version=2,
        )

        job, _, revision_1 = complete_review(db_session, job=job, expected_edit_version=3)
        assert revision_1.revision_number == 1
        first_payload = json.loads(revision_1.snapshot_payload)
        assert len(first_payload["parameter_roles"]) == 1

        # A later edit (a second parameter role) must never retroactively change revision 1.
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="k2",
            role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
            arm_ids=[arm.id],
            expected_edit_version=job.edit_version,
        )
        assert job.status.value == "DRAFT"

        revision_1_reread = get_job_revision(db_session, job.id, 1)
        assert json.loads(revision_1_reread.snapshot_payload) == first_payload

        job, _, revision_2 = complete_review(
            db_session, job=job, expected_edit_version=job.edit_version
        )
        assert revision_2.revision_number == 2
        second_payload = json.loads(revision_2.snapshot_payload)
        assert len(second_payload["parameter_roles"]) == 2
        # Revision 1 is still exactly as it was -- never overwritten by revision 2's own save.
        assert json.loads(get_job_revision(db_session, job.id, 1).snapshot_payload) == first_payload

        revisions = list_job_revisions(db_session, job.id)
        assert [r.revision_number for r in revisions] == [2, 1]

    def test_output_weighting_is_captured_in_the_revision_and_stays_immutable(self, db_session):
        job, arm, experiment = _seed_single_output_experiment(
            db_session, declare_uncertainty=True, mapped=True
        )
        add_parameter_role(
            db_session,
            job=job,
            parameter_name="k1",
            role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
            arm_ids=[arm.id],
            expected_edit_version=job.edit_version,
        )
        set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.MEASURED,
            relative_output_weight=Decimal("1.5"),
            provenance_note="from the core facility's own assay validation",
            expected_edit_version=job.edit_version,
        )

        job, _, revision_1 = complete_review(
            db_session, job=job, expected_edit_version=job.edit_version
        )
        payload = json.loads(revision_1.snapshot_payload)
        captured = payload["arms"][0]["experiments"][0]["output_weightings"]
        assert len(captured) == 1
        assert captured[0]["output_column_name"] == "glucose_mM"
        assert captured[0]["uncertainty_source"] == "MEASURED"
        assert captured[0]["relative_output_weight"] == "1.5"
        assert captured[0]["provenance_note"] == "from the core facility's own assay validation"

        # A later edit must never retroactively change this already-captured revision.
        set_experiment_output_weighting(
            db_session,
            job=job,
            experiment_id=experiment.id,
            output_column_name="glucose_mM",
            uncertainty_source=CalibrationUncertaintySource.USER_ASSUMED,
            assumed_sigma_value=Decimal("0.9"),
            assumed_sigma_statistic_kind=UncertaintyStatisticKind.STANDARD_DEVIATION,
            expected_edit_version=job.edit_version,
        )
        reread = json.loads(get_job_revision(db_session, job.id, 1).snapshot_payload)
        assert (
            reread["arms"][0]["experiments"][0]["output_weightings"][0]["uncertainty_source"]
            == "MEASURED"
        )
