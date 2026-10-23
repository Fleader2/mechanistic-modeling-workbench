"""Tests for ``app.persistence.calibration_scenario_evaluation`` (Whole-Model Experimental-
Scenario Evaluation increment, ``docs/33``) -- real, end-to-end: a real harness subprocess
round against real Agent 3 Antimony/RoadRunner execution, never a mocked harness client. See
``tests/harness/test_workbench_model_scenario_evaluation_contract.py`` (agent-integration-
harness repository) for the identical real-execution convention one layer down.
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
    set_experiment_mapping,
)
from app.persistence.calibration_scenario_evaluation import (
    ScenarioEvaluationAlreadyActiveError,
    ScenarioResolutionError,
    claim_next_pending_scenario_evaluation_run,
    get_scenario_evaluation_snapshot_for_run,
    list_scenario_evaluation_runs_for_experiment,
    submit_scenario_evaluation,
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
from app.persistence.run_record import create_run_record, get_run_record
from app.persistence.time_series_dataset import get_time_series_dataset, persist_time_series_dataset
from app.storage import save_model_antimony_text
from tests.persistence.conftest import make_model_id, make_project_id, make_subproject_id
from tests.time_series_helpers import (
    blank_template_bytes,
    declare_independent_variables,
    populate_data_tab,
)

#: Exact exponential decay (ds/dt = -k*s) -- every prediction below is checked against this
#: closed-form value, never just "the solver returned something."
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


def _seed_species_catalog(
    db_session, *, subproject_id, model_id, antimony_text=_DECAY_ANTIMONY_TEXT
):
    artifact_reference, checksum = save_model_antimony_text(antimony_text)
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
            )
        ],
    )
    return get_model_species_catalog(db_session, model_id)


def _seed_parameter_catalog(db_session, *, subproject_id, model_id):
    source_run_record_id = _run_record_id(
        db_session, subproject_id=subproject_id, model_id=model_id
    )
    persist_model_parameter_catalog(
        session=db_session,
        model_id=model_id,
        source_run_record_id=source_run_record_id,
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


def _seed_dataset(
    db_session, *, project_id, subproject_id, headers, rows, filename="scenario_eval.xlsx"
):
    workbook_bytes = populate_data_tab(blank_template_bytes(), headers=headers, rows=rows)
    workbook_bytes = declare_independent_variables(workbook_bytes, {"dose_uM": ("uM", None)})
    result = persist_time_series_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename=filename,
        workbook_bytes=workbook_bytes,
    )
    return get_time_series_dataset(db_session, result.entity_id)


def _build_experiment(
    db_session,
    *,
    project_id,
    subproject_id,
    model_id,
    headers,
    rows,
    binding_kwargs=None,
):
    """A full job/arm/experiment, with a species+parameter catalog, an S1<->obs_S1 alias
    mapping, and (optionally) one variable binding -- returns ``(job, experiment)`` before
    review is completed, so the caller can add more bindings first."""
    species_catalog = _seed_species_catalog(
        db_session, subproject_id=subproject_id, model_id=model_id
    )
    _seed_parameter_catalog(db_session, subproject_id=subproject_id, model_id=model_id)
    dataset = _seed_dataset(
        db_session, project_id=project_id, subproject_id=subproject_id, headers=headers, rows=rows
    )

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
        time_series_dataset_id=dataset.id,
        expected_edit_version=job.edit_version,
    )
    mapping = save_mapping_revision(
        session=db_session,
        dataset=dataset,
        model_species_catalog=species_catalog,
        assignments=[
            AssignmentInput(
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
        alias_mapping_revision_number=mapping.revision_number,
        expected_edit_version=job.edit_version,
    )
    if binding_kwargs is not None:
        add_variable_binding(
            db_session,
            job=job,
            experiment_id=experiment.id,
            expected_edit_version=job.edit_version,
            **binding_kwargs,
        )
    return job, experiment


def _complete_and_get_revision(db_session, job, *, expected_edit_version):
    _, _, revision = complete_review(
        db_session, job=job, expected_edit_version=expected_edit_version
    )
    return revision


def _submit_and_run(
    db_session, *, job, revision, experiment, condition_id="ctrl", candidate_parameter_values=None
):
    run = submit_scenario_evaluation(
        db_session,
        job=job,
        revision=revision,
        experiment=experiment,
        condition_id=condition_id,
        candidate_parameter_values=candidate_parameter_values or {},
    )
    db_session.commit()
    claimed = claim_next_pending_scenario_evaluation_run(db_session)
    assert claimed is not None and claimed.id == run.id
    process_one_pending_run(claimed, db_session)
    db_session.commit()
    return get_run_record(db_session, run.id)


class TestRealDecayEvaluation:
    def test_a_simple_scenario_evaluates_and_matches_the_analytic_decay_solution(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job, experiment = _build_experiment(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            model_id=model_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=((0, "ctrl", 10, 10.0), (1, "ctrl", 10, 6.065), (2, "ctrl", 10, 3.679)),
        )
        revision = _complete_and_get_revision(
            db_session, job, expected_edit_version=job.edit_version
        )

        run = _submit_and_run(db_session, job=job, revision=revision, experiment=experiment)
        assert run.status is RunStatus.SUCCEEDED

        predictions = json.loads(run.artifact_reference)["predictions"]["S1"]
        for t, predicted in zip((0.0, 1.0, 2.0), predictions, strict=True):
            assert predicted == pytest.approx(_decay(10.0, 0.5, t), rel=1e-6)

    def test_a_candidate_parameter_value_changes_the_predicted_trajectory(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job, experiment = _build_experiment(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            model_id=model_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=((0, "ctrl", 10, 10.0), (1, "ctrl", 10, None)),
        )
        revision = _complete_and_get_revision(
            db_session, job, expected_edit_version=job.edit_version
        )

        run = _submit_and_run(
            db_session,
            job=job,
            revision=revision,
            experiment=experiment,
            candidate_parameter_values={"k1": Decimal("2.0")},
        )

        predictions = json.loads(run.artifact_reference)["predictions"]["S1"]
        assert predictions[1] == pytest.approx(_decay(10.0, 2.0, 1.0), rel=1e-6)

    def test_different_conditions_produce_distinct_predictions_from_the_same_model(
        self, db_session
    ):
        """The exact task requirement: evaluating the same model under different fixed doses
        (here, a DATASET_COLUMN-sourced INITIAL_VALUE binding that differs by condition) must
        produce distinct predictions -- never silently collapsed to one dose."""
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job, experiment = _build_experiment(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            model_id=model_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=(
                (0, "ctrl", 10, 10.0),
                (1, "ctrl", 10, 6.065),
                (0, "dose", 50, 50.0),
                (1, "dose", 50, 30.33),
            ),
            binding_kwargs={
                "model_meaning": CalibrationBindingModelMeaning.INITIAL_VALUE,
                "target_component_id": "S1",
                "value_source": CalibrationBindingValueSource.DATASET_COLUMN,
                "source_column_name": "dose_uM",
            },
        )
        revision = _complete_and_get_revision(
            db_session, job, expected_edit_version=job.edit_version
        )


        run_ctrl = _submit_and_run(
            db_session, job=job, revision=revision, experiment=experiment, condition_id="ctrl"
        )
        run_dose = _submit_and_run(
            db_session, job=job, revision=revision, experiment=experiment, condition_id="dose"
        )
        predictions_ctrl = json.loads(run_ctrl.artifact_reference)["predictions"]["S1"]
        predictions_dose = json.loads(run_dose.artifact_reference)["predictions"]["S1"]
        assert predictions_ctrl[0] == pytest.approx(10.0, rel=1e-6)
        assert predictions_dose[0] == pytest.approx(50.0, rel=1e-6)
        assert predictions_ctrl != predictions_dose

    def test_repeated_submissions_never_leak_state_a_then_b_then_a(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job, experiment = _build_experiment(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            model_id=model_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=((0, "ctrl", 10, 10.0), (1, "ctrl", 10, None)),
        )
        revision = _complete_and_get_revision(
            db_session, job, expected_edit_version=job.edit_version
        )


        run_a1 = _submit_and_run(
            db_session,
            job=job,
            revision=revision,
            experiment=experiment,
            candidate_parameter_values={"k1": Decimal("0.5")},
        )
        run_b = _submit_and_run(
            db_session,
            job=job,
            revision=revision,
            experiment=experiment,
            candidate_parameter_values={"k1": Decimal("5.0")},
        )
        run_a2 = _submit_and_run(
            db_session,
            job=job,
            revision=revision,
            experiment=experiment,
            candidate_parameter_values={"k1": Decimal("0.5")},
        )
        predictions_a1 = json.loads(run_a1.artifact_reference)["predictions"]["S1"][1]
        predictions_b = json.loads(run_b.artifact_reference)["predictions"]["S1"][1]
        predictions_a2 = json.loads(run_a2.artifact_reference)["predictions"]["S1"][1]
        assert predictions_a1 == pytest.approx(_decay(10.0, 0.5, 1.0), rel=1e-6)
        assert predictions_b == pytest.approx(_decay(10.0, 5.0, 1.0), rel=1e-6)
        assert predictions_a2 == pytest.approx(predictions_a1, rel=1e-9)

    def test_irregular_and_repeated_dataset_times_are_aligned_exactly(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job, experiment = _build_experiment(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            model_id=model_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=(
                (3, "ctrl", 10, None),
                (0, "ctrl", 10, 10.0),
                (3, "ctrl", 10, None),
                (1.5, "ctrl", 10, None),
            ),
        )
        revision = _complete_and_get_revision(
            db_session, job, expected_edit_version=job.edit_version
        )


        run = _submit_and_run(db_session, job=job, revision=revision, experiment=experiment)
        predictions = json.loads(run.artifact_reference)["predictions"]["S1"]
        assert len(predictions) == 4
        for t, predicted in zip((3.0, 0.0, 3.0, 1.5), predictions, strict=True):
            assert predicted == pytest.approx(_decay(10.0, 0.5, t), rel=1e-6)
        assert predictions[0] == predictions[2]


class TestRejections:
    def test_a_candidate_value_conflicting_with_a_parameter_override_binding_is_rejected(
        self, db_session
    ):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job, experiment = _build_experiment(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            model_id=model_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=((0, "ctrl", 10, 10.0),),
            binding_kwargs={
                "model_meaning": CalibrationBindingModelMeaning.PARAMETER_OVERRIDE,
                "target_component_id": "k1",
                "value_source": CalibrationBindingValueSource.CONSTANT,
                "constant_value": Decimal("0.2"),
            },
        )
        revision = _complete_and_get_revision(
            db_session, job, expected_edit_version=job.edit_version
        )

        with pytest.raises(ScenarioResolutionError, match="conflicts"):
            submit_scenario_evaluation(
                db_session,
                job=job,
                revision=revision,
                experiment=experiment,
                condition_id="ctrl",
                candidate_parameter_values={"k1": Decimal("1.0")},
            )

    def test_a_dataset_column_varying_within_a_condition_is_rejected_as_a_dosing_schedule(
        self, db_session
    ):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job, experiment = _build_experiment(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            model_id=model_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=((0, "ctrl", 10, 10.0), (1, "ctrl", 20, None)),
            binding_kwargs={
                "model_meaning": CalibrationBindingModelMeaning.INITIAL_VALUE,
                "target_component_id": "S1",
                "value_source": CalibrationBindingValueSource.DATASET_COLUMN,
                "source_column_name": "dose_uM",
            },
        )
        revision = _complete_and_get_revision(
            db_session, job, expected_edit_version=job.edit_version
        )

        with pytest.raises(ScenarioResolutionError, match="dosing schedule"):
            submit_scenario_evaluation(
                db_session,
                job=job,
                revision=revision,
                experiment=experiment,
                condition_id="ctrl",
                candidate_parameter_values={},
            )

    def test_an_unmapped_experiment_has_no_output_species_and_is_rejected(self, db_session):
        """An arm needs at least one *mapped* experiment to pass review (``ARM_WITHOUT_MAPPED_
        EXPERIMENT``) -- so the only way a saved revision can contain an unmapped experiment at
        all is a second, sibling experiment on the same arm that satisfies that check on its
        own. The unmapped sibling is still rejected on its own terms when evaluated."""
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job, mapped_experiment = _build_experiment(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            model_id=model_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=((0, "ctrl", 10, 10.0),),
        )
        arm = job.arms[0]
        unmapped_dataset = _seed_dataset(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=((0, "ctrl", 10, 10.0),),
            filename="unmapped_scenario_eval.xlsx",
        )
        unmapped_experiment = add_experiment(
            db_session,
            job=job,
            arm=arm,
            time_series_dataset_id=unmapped_dataset.id,
            expected_edit_version=job.edit_version,
        )
        revision = _complete_and_get_revision(
            db_session, job, expected_edit_version=job.edit_version
        )

        with pytest.raises(ScenarioResolutionError, match="no saved dataset<->model alias mapping"):
            submit_scenario_evaluation(
                db_session,
                job=job,
                revision=revision,
                experiment=unmapped_experiment,
                condition_id="ctrl",
                candidate_parameter_values={},
            )

        # The mapped sibling, meanwhile, evaluates normally.
        run = submit_scenario_evaluation(
            db_session,
            job=job,
            revision=revision,
            experiment=mapped_experiment,
            condition_id="ctrl",
            candidate_parameter_values={},
        )
        assert run is not None

    def test_a_second_identical_active_submission_is_rejected(self, db_session):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job, experiment = _build_experiment(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            model_id=model_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=((0, "ctrl", 10, 10.0),),
        )
        revision = _complete_and_get_revision(
            db_session, job, expected_edit_version=job.edit_version
        )

        submit_scenario_evaluation(
            db_session,
            job=job,
            revision=revision,
            experiment=experiment,
            condition_id="ctrl",
            candidate_parameter_values={},
        )
        db_session.commit()

        with pytest.raises(ScenarioEvaluationAlreadyActiveError):
            submit_scenario_evaluation(
                db_session,
                job=job,
                revision=revision,
                experiment=experiment,
                condition_id="ctrl",
                candidate_parameter_values={},
            )


class TestDurableFailureAndPersistence:
    def test_a_malformed_antimony_artifact_is_a_durable_failed_run_not_an_exception(
        self, db_session
    ):
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job, experiment = _build_experiment(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            model_id=model_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=((0, "ctrl", 10, 10.0),),
        )
        revision = _complete_and_get_revision(
            db_session, job, expected_edit_version=job.edit_version
        )

        # Corrupt the catalog's own recorded Antimony artifact after review, so the
        # evaluation itself (never submission) is what discovers the failure.
        catalog = get_model_species_catalog(db_session, model_id)
        from app.storage import save_model_antimony_text as _save

        bad_reference, _ = _save("this is not valid antimony syntax at all !!!")
        catalog.source_antimony_artifact_reference = bad_reference
        db_session.flush()

        run = _submit_and_run(db_session, job=job, revision=revision, experiment=experiment)
        assert run.status is RunStatus.FAILED
        assert run.error_summary is not None

    def test_a_run_is_readable_after_expiring_the_identity_map_not_just_held_in_memory(
        self, db_session
    ):
        """``db_session`` wraps every test in one outer transaction that is always rolled back
        at the end (``tests/conftest.py``'s own documented isolation discipline) -- a genuinely
        separate connection can never see this test's own rows, by design, regardless of any
        ``session.commit()`` within it. The closest thing this fixture allows to "reopen
        independently of in-memory state" is expiring the ORM identity map and re-querying --
        proving the row was actually durably written and is read back correctly from the
        database, never merely held as a live Python object."""
        project_id = make_project_id(db_session)
        subproject_id = make_subproject_id(db_session, project_id=project_id)
        model_id = make_model_id(db_session, subproject_id=subproject_id)
        job, experiment = _build_experiment(
            db_session,
            project_id=project_id,
            subproject_id=subproject_id,
            model_id=model_id,
            headers=("time", "condition_id", "dose_uM", "obs_S1"),
            rows=((0, "ctrl", 10, 10.0),),
        )
        revision = _complete_and_get_revision(
            db_session, job, expected_edit_version=job.edit_version
        )
        run = _submit_and_run(db_session, job=job, revision=revision, experiment=experiment)
        run_id, experiment_id = run.id, experiment.id

        db_session.expire_all()

        reread = get_run_record(db_session, run_id)
        assert reread is not None
        assert reread.status is RunStatus.SUCCEEDED
        snapshot = get_scenario_evaluation_snapshot_for_run(db_session, run_id)
        assert snapshot is not None
        assert snapshot.calibration_experiment_id == experiment_id
        runs = list_scenario_evaluation_runs_for_experiment(db_session, experiment_id)
        assert run_id in {r.id for r in runs}
