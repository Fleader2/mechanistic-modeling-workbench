"""Tests wiring the Initial-Conditions Dataset Import increment's own new dataset type into
calibration configuration/execution -- real, end-to-end: a real harness subprocess round
against real Agent 3 Antimony/RoadRunner execution, mirroring
``tests.persistence.test_calibration_scenario_evaluation``'s own identical convention.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest

from app.models.enums import (
    AliasMappingAssignmentStatus,
    CalibrationBindingModelMeaning,
    CalibrationBindingValueSource,
    CalibrationParameterRoleKind,
    InitialConditionsAliasMappingTargetKind,
    ModelParameterCatalogStatus,
    ModelParameterKind,
    ModelSpeciesCatalogStatus,
    RunStage,
    RunStatus,
)
from app.orchestration.calibration_scenario_evaluation_orchestrator import process_one_pending_run
from app.persistence.calibration import (
    add_arm,
    add_experiment,
    add_parameter_role,
    add_variable_binding,
    complete_review,
    create_job,
    set_experiment_initial_conditions_dataset,
    set_experiment_initial_conditions_mapping,
    set_experiment_mapping,
)
from app.persistence.calibration_scenario_evaluation import (
    ScenarioResolutionError,
    claim_next_pending_scenario_evaluation_run,
    resolve_scenario,
    submit_scenario_evaluation,
)
from app.persistence.dataset_model_alias_mapping import (
    AssignmentInput as TimeSeriesAssignmentInput,
)
from app.persistence.dataset_model_alias_mapping import (
    save_mapping_revision as save_time_series_mapping_revision,
)
from app.persistence.initial_conditions_alias_mapping import (
    AssignmentInput as InitialConditionsAssignmentInput,
)
from app.persistence.initial_conditions_alias_mapping import (
    save_mapping_revision as save_initial_conditions_mapping_revision,
)
from app.persistence.initial_conditions_dataset import (
    get_initial_conditions_dataset,
    persist_initial_conditions_dataset,
)
from app.persistence.model_parameter_catalog import (
    CapturedParameter,
    persist_model_parameter_catalog,
)
from app.persistence.model_species_catalog import (
    CapturedSpecies,
    get_model_species_catalog,
    persist_model_species_catalog,
)
from app.persistence.run_record import create_run_record, get_run_record
from app.persistence.time_series_dataset import get_time_series_dataset, persist_time_series_dataset
from app.storage import save_model_antimony_text
from tests.initial_conditions_helpers import blank_template_bytes as ic_blank_template_bytes
from tests.initial_conditions_helpers import declare_measurement_columns as ic_declare_units
from tests.initial_conditions_helpers import populate_data_tab as ic_populate_data_tab
from tests.persistence.conftest import make_model_id, make_project_id, make_subproject_id
from tests.time_series_helpers import blank_template_bytes, populate_data_tab

pytestmark = pytest.mark.database

_DECAY_ANTIMONY_TEXT = """
model decay_model
  compartment C1
  C1 = 1.0
  species S1 in C1
  S1 = 10
  J1: S1 ->; k1 * S1
  k1 = 0.5
end
"""


def _decay(s0: float, k: float, t: float) -> float:
    return s0 * math.exp(-k * t)


def _run_record_id(db_session, *, subproject_id, model_id):
    run = create_run_record(
        subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session, model_id=model_id
    )
    db_session.flush()
    return run.id


def _seed(db_session, *, species_unit: str | None = None, ic_measurement_unit: str | None = None):
    """A real job/arm/experiment with: a real S1-decay model (species catalog + Antimony
    artifact), a mapped time-series calibration-target dataset, and a separately-pinned
    initial-conditions dataset giving S1 a real abundance of 7 (never the Antimony source's own
    baked-in 10) -- plus an INITIAL_VALUE/INITIAL_CONDITIONS_DATASET binding reading it.
    ``species_unit``/``ic_measurement_unit`` let a caller declare each side's own unit, to
    exercise the unit-compatibility check carried through to scenario resolution -- both
    default to undeclared, matching every test that predates that check. Returns ``(job,
    experiment)`` before review is completed."""
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=subproject_id)

    artifact_reference, checksum = save_model_antimony_text(_DECAY_ANTIMONY_TEXT)
    source_run_record_id = _run_record_id(
        db_session, subproject_id=subproject_id, model_id=model_id
    )
    persist_model_species_catalog(
        session=db_session,
        model_id=model_id,
        source_run_record_id=source_run_record_id,
        status=ModelSpeciesCatalogStatus.AVAILABLE,
        source_antimony_artifact_reference=artifact_reference,
        source_antimony_checksum=checksum,
        species=[
            CapturedSpecies(
                antimony_species_id="S1",
                canonical_species_id="canonical-S1",
                display_name="S1",
                compartment_id="C1",
                compartment_name="C1",
                kind="FLOATING",
                unit=species_unit,
            )
        ],
    )
    species_catalog = get_model_species_catalog(db_session, model_id)

    persist_model_parameter_catalog(
        session=db_session,
        model_id=model_id,
        source_run_record_id=_run_record_id(
            db_session, subproject_id=subproject_id, model_id=model_id
        ),
        status=ModelParameterCatalogStatus.AVAILABLE,
        parameters=[
            CapturedParameter(
                antimony_parameter_id="k1",
                canonical_parameter_id="canonical-k1",
                display_name="k1",
                kind=ModelParameterKind.INDEPENDENT.value,
                unit="1/s",
            )
        ],
    )

    ts_workbook = populate_data_tab(
        blank_template_bytes(),
        headers=("time", "condition_id", "obs_S1"),
        rows=((0, "ctrl", 10.0), (1, "ctrl", 6.065), (2, "ctrl", 3.679)),
    )
    ts_result = persist_time_series_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename="scenario_eval.xlsx",
        workbook_bytes=ts_workbook,
    )
    ts_dataset = get_time_series_dataset(db_session, ts_result.entity_id)

    ic_workbook = ic_populate_data_tab(
        ic_blank_template_bytes(),
        headers=("target_name", "Abundance"),
        rows=(("S1_abundance", 7),),
    )
    if ic_measurement_unit is not None:
        ic_workbook = ic_declare_units(ic_workbook, {"Abundance": (ic_measurement_unit, None)})
    ic_result = persist_initial_conditions_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename="abundance.xlsx",
        workbook_bytes=ic_workbook,
    )
    ic_dataset = get_initial_conditions_dataset(db_session, ic_result.entity_id)

    job = create_job(db_session, subproject_id=subproject_id)
    arm = add_arm(db_session, job=job, model_id=model_id, expected_edit_version=job.edit_version)
    add_parameter_role(
        db_session,
        job=job,
        parameter_name="k1",
        role=CalibrationParameterRoleKind.MODEL_SPECIFIC,
        arm_ids=[arm.id],
        expected_edit_version=job.edit_version,
    )
    experiment = add_experiment(
        db_session,
        job=job,
        arm=arm,
        time_series_dataset_id=ts_dataset.id,
        expected_edit_version=job.edit_version,
    )

    ts_mapping = save_time_series_mapping_revision(
        session=db_session,
        dataset=ts_dataset,
        model_species_catalog=species_catalog,
        assignments=[
            TimeSeriesAssignmentInput(
                column_name="obs_S1",
                status=AliasMappingAssignmentStatus.ASSIGNED,
                target_antimony_species_id="S1",
            )
        ],
        expected_revision_number=0,
    )
    set_experiment_mapping(
        db_session,
        job=job,
        experiment_id=experiment.id,
        alias_mapping_revision_number=ts_mapping.revision_number,
        expected_edit_version=job.edit_version,
    )

    set_experiment_initial_conditions_dataset(
        db_session,
        job=job,
        experiment_id=experiment.id,
        initial_conditions_dataset_id=ic_dataset.id,
        expected_edit_version=job.edit_version,
    )
    ic_mapping = save_initial_conditions_mapping_revision(
        session=db_session,
        dataset=ic_dataset,
        model_id=model_id,
        model_species_catalog=species_catalog,
        model_parameter_catalog=None,
        assignments=[
            InitialConditionsAssignmentInput(
                target_name="S1_abundance",
                status=AliasMappingAssignmentStatus.ASSIGNED,
                target_kind=InitialConditionsAliasMappingTargetKind.SPECIES,
                target_id="S1",
            )
        ],
        expected_revision_number=0,
    )
    set_experiment_initial_conditions_mapping(
        db_session,
        job=job,
        experiment_id=experiment.id,
        alias_mapping_revision_number=ic_mapping.revision_number,
        expected_edit_version=job.edit_version,
    )

    add_variable_binding(
        db_session,
        job=job,
        experiment_id=experiment.id,
        model_meaning=CalibrationBindingModelMeaning.INITIAL_VALUE,
        target_component_id="S1",
        value_source=CalibrationBindingValueSource.INITIAL_CONDITIONS_DATASET,
        source_column_name="Abundance",
        expected_edit_version=job.edit_version,
    )

    return job, experiment


class TestInitialConditionsDatasetBinding:
    def test_resolve_scenario_reads_the_real_pinned_abundance_value(self, db_session):
        job, experiment = _seed(db_session)
        _, _, revision = complete_review(
            db_session, job=job, expected_edit_version=job.edit_version
        )
        resolved = resolve_scenario(
            db_session,
            revision=revision,
            experiment_id=experiment.id,
            condition_id="ctrl",
            candidate_parameter_values={},
        )
        assert resolved.initial_value_overrides == {"S1": pytest.approx(7)}

    def test_the_real_harness_run_predicts_decay_from_the_abundance_value_not_the_antimony_default(
        self, db_session
    ):
        job, experiment = _seed(db_session)
        _, _, revision = complete_review(
            db_session, job=job, expected_edit_version=job.edit_version
        )
        run = submit_scenario_evaluation(
            db_session,
            job=job,
            revision=revision,
            experiment=experiment,
            condition_id="ctrl",
            candidate_parameter_values={},
        )
        db_session.commit()
        claimed = claim_next_pending_scenario_evaluation_run(db_session)
        assert claimed is not None and claimed.id == run.id
        process_one_pending_run(claimed, db_session)
        db_session.commit()
        run = get_run_record(db_session, run.id)
        assert run.status is RunStatus.SUCCEEDED

        predictions = json.loads(run.artifact_reference)["predictions"]["S1"]
        for t, predicted in zip((0.0, 1.0, 2.0), predictions, strict=True):
            # 7, never the Antimony source's own baked-in S1=10.
            assert predicted == pytest.approx(_decay(7.0, 0.5, t), rel=1e-6)

    def test_a_target_with_no_mapped_abundance_row_is_rejected(self, db_session):
        job, experiment = _seed(db_session)
        # Remove the one ASSIGNED row by re-saving an all-UNRESOLVED mapping revision.
        ic_dataset = experiment.initial_conditions_dataset
        save_initial_conditions_mapping_revision(
            session=db_session,
            dataset=ic_dataset,
            model_id=experiment.arm.model_id,
            model_species_catalog=get_model_species_catalog(db_session, experiment.arm.model_id),
            model_parameter_catalog=None,
            assignments=[],
            expected_revision_number=1,
        )
        set_experiment_initial_conditions_mapping(
            db_session,
            job=job,
            experiment_id=experiment.id,
            alias_mapping_revision_number=2,
            expected_edit_version=job.edit_version,
        )
        _, _, revision = complete_review(
            db_session, job=job, expected_edit_version=job.edit_version
        )
        with pytest.raises(ScenarioResolutionError, match="no row in this experiment"):
            resolve_scenario(
                db_session,
                revision=revision,
                experiment_id=experiment.id,
                condition_id="ctrl",
                candidate_parameter_values={},
            )

    def test_add_variable_binding_rejects_a_second_initial_value_binding_for_the_same_target(
        self, db_session
    ):
        """Closes the precedence gap: a conflicting override is now rejected the moment it is
        configured, not only once someone tries to evaluate a scenario."""
        job, experiment = _seed(db_session)
        with pytest.raises(ValueError, match="already has a INITIAL_VALUE binding"):
            add_variable_binding(
                db_session,
                job=job,
                experiment_id=experiment.id,
                model_meaning=CalibrationBindingModelMeaning.INITIAL_VALUE,
                target_component_id="S1",
                value_source=CalibrationBindingValueSource.CONSTANT,
                constant_value=Decimal("5"),
                expected_edit_version=job.edit_version,
            )
        # Never partially applied -- the original INITIAL_CONDITIONS_DATASET binding is the
        # only one still there.
        assert len(experiment.variable_bindings) == 1
        assert experiment.variable_bindings[0].value_source == (
            CalibrationBindingValueSource.INITIAL_CONDITIONS_DATASET
        )

    def test_add_variable_binding_allows_a_second_intervention_on_the_same_target(self, db_session):
        """A real dosing schedule is multiple interventions on the identical target at
        different times -- never a conflict, unlike INITIAL_VALUE/PARAMETER_OVERRIDE."""
        job, experiment = _seed(db_session)
        add_variable_binding(
            db_session,
            job=job,
            experiment_id=experiment.id,
            model_meaning=CalibrationBindingModelMeaning.INTERVENTION,
            target_component_id="S1",
            value_source=CalibrationBindingValueSource.CONSTANT,
            constant_value=Decimal("3"),
            intervention_time=Decimal("1"),
            expected_edit_version=job.edit_version,
        )
        add_variable_binding(
            db_session,
            job=job,
            experiment_id=experiment.id,
            model_meaning=CalibrationBindingModelMeaning.INTERVENTION,
            target_component_id="S1",
            value_source=CalibrationBindingValueSource.CONSTANT,
            constant_value=Decimal("1"),
            intervention_time=Decimal("2"),
            expected_edit_version=job.edit_version,
        )
        assert len(experiment.variable_bindings) == 3  # the IC one from _seed, plus these two

    def test_an_incompatible_unit_is_rejected_at_resolution_never_silently_used(self, db_session):
        """Closes the units gap: an abundance measurement is never automatically treated as a
        model concentration -- confirmed INCOMPATIBLE at mapping time is rejected outright at
        resolution, not merely disclosed on a screen nobody has to look at."""
        job, experiment = _seed(db_session, species_unit="s", ic_measurement_unit="mM")
        _, _, revision = complete_review(
            db_session, job=job, expected_edit_version=job.edit_version
        )
        with pytest.raises(ScenarioResolutionError, match="INCOMPATIBLE"):
            resolve_scenario(
                db_session,
                revision=revision,
                experiment_id=experiment.id,
                condition_id="ctrl",
                candidate_parameter_values={},
            )
