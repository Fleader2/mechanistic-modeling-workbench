"""Tests for the Whole-Model Experimental-Scenario Evaluation increment's own API surface
(``docs/33``) -- submit/list/get, including ownership isolation and duplicate-submission
rejection. Real harness/Agent 3 execution (the background worker's own unit of work is invoked
directly, in-process, exactly once per submission -- never mocked).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.models.enums import (
    AliasMappingAssignmentStatus,
    CalibrationParameterRoleKind,
    ModelParameterCatalogStatus,
    ModelSpeciesCatalogStatus,
    RunStage,
)
from app.orchestration.calibration_scenario_evaluation_orchestrator import process_one_pending_run
from app.persistence.calibration import (
    add_arm,
    add_experiment,
    add_parameter_role,
    complete_review,
    create_job,
    set_experiment_mapping,
)
from app.persistence.calibration_scenario_evaluation import (
    claim_next_pending_scenario_evaluation_run,
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
from app.persistence.time_series_dataset import persist_time_series_dataset
from app.storage import save_model_antimony_text
from tests.persistence.conftest import make_model_id, make_project_id, make_subproject_id
from tests.time_series_helpers import (
    blank_template_bytes,
    declare_independent_variables,
    populate_data_tab,
)

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"

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


def _jobs_url(project_id, subproject_id) -> str:
    return f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/calibration-jobs"


def _seed_job_with_revision(db_session):
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=subproject_id)

    run = create_run_record(
        subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session, model_id=model_id
    )
    db_session.flush()
    artifact_reference, checksum = save_model_antimony_text(_DECAY_ANTIMONY_TEXT)
    persist_model_species_catalog(
        session=db_session,
        model_id=model_id,
        source_run_record_id=run.id,
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
    species_catalog = get_model_species_catalog(db_session, model_id)
    persist_model_parameter_catalog(
        session=db_session,
        model_id=model_id,
        source_run_record_id=run.id,
        status=ModelParameterCatalogStatus.AVAILABLE,
        parameters=[
            CapturedParameter(
                antimony_parameter_id="k1",
                canonical_parameter_id="canonical-k1",
                display_name="k1",
                kind="INDEPENDENT",
                unit="1/s",
            )
        ],
    )

    workbook_bytes = populate_data_tab(
        blank_template_bytes(),
        headers=("time", "condition_id", "dose_uM", "obs_S1"),
        rows=((0, "ctrl", 10, 10.0), (1, "ctrl", 10, 6.065)),
    )
    workbook_bytes = declare_independent_variables(workbook_bytes, {"dose_uM": ("uM", None)})
    dataset_result = persist_time_series_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename="api_scenario_eval.xlsx",
        workbook_bytes=workbook_bytes,
    )
    dataset_id = dataset_result.entity_id
    from app.persistence.time_series_dataset import get_time_series_dataset

    dataset = get_time_series_dataset(db_session, dataset_id)

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
        time_series_dataset_id=dataset_id,
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
    _, _, revision = complete_review(db_session, job=job, expected_edit_version=job.edit_version)
    db_session.commit()
    return project_id, subproject_id, job.id, revision.revision_number, experiment.id


def _submit_and_complete(client, url, *, body, db_session) -> dict:
    submitted = client.post(url, json=body)
    assert submitted.status_code == 201, submitted.text
    run_id = submitted.json()["id"]
    claimed = claim_next_pending_scenario_evaluation_run(db_session)
    assert claimed is not None and str(claimed.id) == run_id
    process_one_pending_run(claimed, db_session)
    db_session.commit()
    return client.get(f"{url}/{run_id}").json()


class TestSubmitListGet:
    def test_submit_returns_a_pending_run_then_the_list_route_shows_it(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, job_id, revision_number, experiment_id = _seed_job_with_revision(
            db_session
        )
        url = (
            f"{_jobs_url(project_id, subproject_id)}/{job_id}/revisions/{revision_number}"
            f"/experiments/{experiment_id}/scenario-evaluations"
        )

        submitted = client.post(url, json={"condition_id": "ctrl"})
        assert submitted.status_code == 201
        assert submitted.json()["status"] == "PENDING"

        listing = client.get(url)
        assert listing.status_code == 200
        assert len(listing.json()) == 1
        assert listing.json()[0]["id"] == submitted.json()["id"]

    def test_an_unresolvable_condition_is_a_422_with_no_run_ever_created(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, job_id, revision_number, experiment_id = _seed_job_with_revision(
            db_session
        )
        url = (
            f"{_jobs_url(project_id, subproject_id)}/{job_id}/revisions/{revision_number}"
            f"/experiments/{experiment_id}/scenario-evaluations"
        )

        response = client.post(url, json={"condition_id": "not_a_real_condition"})
        assert response.status_code == 422
        assert client.get(url).json() == []

    def test_submit_poll_and_reopen_a_successful_evaluation(self, client: TestClient, db_session):
        project_id, subproject_id, job_id, revision_number, experiment_id = _seed_job_with_revision(
            db_session
        )
        url = (
            f"{_jobs_url(project_id, subproject_id)}/{job_id}/revisions/{revision_number}"
            f"/experiments/{experiment_id}/scenario-evaluations"
        )
        reopened = _submit_and_complete(
            client, url, body={"condition_id": "ctrl"}, db_session=db_session
        )
        assert reopened["status"] == "SUCCEEDED"
        assert reopened["evaluation_status"] == "SUCCESS"
        rows = reopened["observed_vs_predicted"]
        assert len(rows) == 2
        assert rows[0]["predicted"] == pytest.approx(10.0, rel=1e-6)
        assert rows[0]["observed"] == pytest.approx(10.0, rel=1e-6)

    def test_an_unknown_job_is_a_404(self, client: TestClient, db_session):
        project_id, subproject_id, _job_id, revision_number, experiment_id = (
            _seed_job_with_revision(db_session)
        )
        import uuid

        url = (
            f"{_jobs_url(project_id, subproject_id)}/{uuid.uuid4()}/revisions/{revision_number}"
            f"/experiments/{experiment_id}/scenario-evaluations"
        )
        assert client.post(url, json={}).status_code == 404

    def test_a_job_is_not_reachable_through_an_unrelated_subproject(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, job_id, revision_number, experiment_id = (
            _seed_job_with_revision(db_session)
        )
        other_project_id = make_project_id(db_session)
        other_subproject_id = make_subproject_id(db_session, project_id=other_project_id)
        db_session.commit()

        url = (
            f"{_jobs_url(project_id, other_subproject_id)}/{job_id}/revisions/{revision_number}"
            f"/experiments/{experiment_id}/scenario-evaluations"
        )
        assert client.post(url, json={"condition_id": "ctrl"}).status_code == 404

        # The real subproject still works -- isolation, never a broken route.
        real_url = (
            f"{_jobs_url(project_id, subproject_id)}/{job_id}/revisions/{revision_number}"
            f"/experiments/{experiment_id}/scenario-evaluations"
        )
        assert client.post(real_url, json={"condition_id": "ctrl"}).status_code == 201

    def test_a_second_active_submission_for_the_identical_scenario_is_a_409(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, job_id, revision_number, experiment_id = _seed_job_with_revision(
            db_session
        )
        url = (
            f"{_jobs_url(project_id, subproject_id)}/{job_id}/revisions/{revision_number}"
            f"/experiments/{experiment_id}/scenario-evaluations"
        )
        first = client.post(url, json={"condition_id": "ctrl"})
        assert first.status_code == 201
        second = client.post(url, json={"condition_id": "ctrl"})
        assert second.status_code == 409

    def test_candidate_parameter_values_are_rejected_as_malformed_when_not_numeric(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, job_id, revision_number, experiment_id = _seed_job_with_revision(
            db_session
        )
        url = (
            f"{_jobs_url(project_id, subproject_id)}/{job_id}/revisions/{revision_number}"
            f"/experiments/{experiment_id}/scenario-evaluations"
        )
        response = client.post(
            url,
            json={"condition_id": "ctrl", "candidate_parameter_values": {"k1": "not-a-number"}},
        )
        assert response.status_code == 422
