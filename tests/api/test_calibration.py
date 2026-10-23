"""Tests for the Joint Calibration Workflow configuration-only increment's own API surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.models.enums import ModelSpeciesCatalogStatus, RunStage
from app.persistence.model_species_catalog import CapturedSpecies, persist_model_species_catalog
from app.persistence.run_record import create_run_record
from app.persistence.time_series_dataset import persist_time_series_dataset
from tests.persistence.conftest import make_model_id, make_project_id, make_subproject_id
from tests.time_series_helpers import fixture_workbook_bytes

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def _jobs_url(project_id, subproject_id) -> str:
    return f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/calibration-jobs"


def _seed(db_session, *, available_catalog: bool = True):
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=subproject_id)
    dataset_id = persist_time_series_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename="ras_mapk.xlsx",
        workbook_bytes=fixture_workbook_bytes(),
    ).entity_id
    if available_catalog:
        run = create_run_record(
            subproject_id=subproject_id,
            stage=RunStage.HARNESS,
            session=db_session,
            model_id=model_id,
        )
        db_session.flush()
        persist_model_species_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=run.id,
            status=ModelSpeciesCatalogStatus.AVAILABLE,
            species=[
                CapturedSpecies(
                    antimony_species_id="s_aRAStot",
                    canonical_species_id="canonical-s_aRAStot",
                    display_name="aRAStot",
                    compartment_id="c1",
                    compartment_name="cyto",
                    kind="FLOATING",
                )
            ],
        )
    db_session.commit()
    return project_id, subproject_id, dataset_id, model_id


class TestCreateAndConfigureHappyPath:
    def test_one_model_one_dataset_reaches_reviewed_but_not_executable(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        jobs_url = _jobs_url(project_id, subproject_id)

        job = client.post(jobs_url, json={"created_by": "dr-test"}).json()
        assert job["status"] == "DRAFT"
        assert job["edit_version"] == 0

        job = client.post(
            f"{jobs_url}/{job['id']}/arms",
            json={"model_id": str(model_id), "expected_edit_version": 0},
        ).json()
        assert len(job["arms"]) == 1
        arm_id = job["arms"][0]["id"]
        assert job["edit_version"] == 1

        job = client.post(
            f"{jobs_url}/{job['id']}/arms/{arm_id}/experiments",
            json={"time_series_dataset_id": str(dataset_id), "expected_edit_version": 1},
        ).json()
        experiment_id = job["arms"][0]["experiments"][0]["id"]
        assert job["arms"][0]["experiments"][0]["role"] == "CALIBRATION"

        # Map the measurement column so this experiment actually has an assigned mapping --
        # reuse the existing alias-mapping save route directly.
        mapping_response = client.post(
            f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/datasets/time-series/"
            f"{dataset_id}/alias-mapping/{model_id}",
            json={
                "expected_revision_number": 0,
                "assignments": [
                    {
                        "column_name": "[aRAStot]",
                        "status": "ASSIGNED",
                        "target_antimony_species_id": "s_aRAStot",
                    }
                ],
            },
        )
        assert mapping_response.status_code == 201

        job = client.patch(
            f"{jobs_url}/{job['id']}/experiments/{experiment_id}/mapping",
            json={
                "alias_mapping_revision_number": mapping_response.json()["revision_number"],
                "expected_edit_version": job["edit_version"],
            },
        ).json()
        assert job["arms"][0]["experiments"][0]["alias_mapping_revision_id"] is not None
        assert job["arms"][0]["experiments"][0]["mapping_is_stale"] is False

        job = client.post(
            f"{jobs_url}/{job['id']}/parameter-roles",
            json={
                "parameter_name": "k1",
                "role": "MODEL_SPECIFIC",
                "arm_ids": [arm_id],
                "expected_edit_version": job["edit_version"],
            },
        ).json()
        role = job["parameter_roles"][0]
        assert role["catalog_validated"] is False

        review = client.get(f"{jobs_url}/{job['id']}/review").json()
        assert review["findings"] == [] or all(f["severity"] != "ERROR" for f in review["findings"])
        assert review["execution_capability"]["available"] is False
        assert review["execution_capability"]["missing_capability"] == "WHOLE_MODEL_EXECUTION"

        completed = client.post(
            f"{jobs_url}/{job['id']}/complete-review",
            json={"expected_edit_version": job["edit_version"]},
        )
        assert completed.status_code == 200
        assert completed.json()["job"]["status"] == "REVIEWED"
        assert completed.json()["execution_capability"]["available"] is False

    def test_a_model_relationship_can_be_declared_and_is_visible_from_the_job(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, _dataset_id, model_id_a = _seed(db_session)
        model_id_b = make_model_id(db_session, subproject_id=subproject_id)
        db_session.commit()

        declare = client.post(
            f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/model-relationships",
            json={
                "model_id_a": str(model_id_a),
                "model_id_b": str(model_id_b),
                "relationship_kind": "VARIANT_OF",
                "role_label_a": "no_drug",
                "role_label_b": "drug_treated",
            },
        )
        assert declare.status_code == 201

        jobs_url = _jobs_url(project_id, subproject_id)
        job = client.post(jobs_url, json={}).json()
        job = client.post(
            f"{jobs_url}/{job['id']}/arms",
            json={"model_id": str(model_id_a), "expected_edit_version": 0},
        ).json()
        job = client.post(
            f"{jobs_url}/{job['id']}/arms",
            json={"model_id": str(model_id_b), "expected_edit_version": job["edit_version"]},
        ).json()

        relationships = client.get(f"{jobs_url}/{job['id']}/model-relationships").json()
        assert len(relationships) == 1
        assert relationships[0]["relationship_kind"] == "VARIANT_OF"


class TestConcurrencyAndValidation:
    def test_a_stale_edit_version_returns_409(self, client: TestClient, db_session):
        project_id, subproject_id, _dataset_id, model_id = _seed(db_session)
        jobs_url = _jobs_url(project_id, subproject_id)
        job = client.post(jobs_url, json={}).json()
        client.post(
            f"{jobs_url}/{job['id']}/arms",
            json={"model_id": str(model_id), "expected_edit_version": 0},
        )
        stale = client.post(
            f"{jobs_url}/{job['id']}/arms",
            json={"model_id": str(model_id), "expected_edit_version": 0},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["context"]["current_edit_version"] == 1

    def test_complete_review_is_blocked_with_findings_in_the_error_context(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, _dataset_id, model_id = _seed(db_session)
        jobs_url = _jobs_url(project_id, subproject_id)
        job = client.post(jobs_url, json={}).json()
        job = client.post(
            f"{jobs_url}/{job['id']}/arms",
            json={"model_id": str(model_id), "expected_edit_version": 0},
        ).json()

        blocked = client.post(
            f"{jobs_url}/{job['id']}/complete-review",
            json={"expected_edit_version": job["edit_version"]},
        )
        assert blocked.status_code == 422
        findings = blocked.json()["detail"]["context"]["findings"]
        assert any(f["category"] == "ARM_WITHOUT_MAPPED_EXPERIMENT" for f in findings)

    def test_an_unknown_job_is_a_404(self, client: TestClient, db_session):
        project_id, subproject_id, _dataset_id, _model_id = _seed(db_session)
        response = client.get(
            f"{_jobs_url(project_id, subproject_id)}/00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 404

    def test_an_initial_value_binding_for_an_unreal_species_is_422(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        jobs_url = _jobs_url(project_id, subproject_id)
        job = client.post(jobs_url, json={}).json()
        job = client.post(
            f"{jobs_url}/{job['id']}/arms",
            json={"model_id": str(model_id), "expected_edit_version": 0},
        ).json()
        arm_id = job["arms"][0]["id"]
        job = client.post(
            f"{jobs_url}/{job['id']}/arms/{arm_id}/experiments",
            json={
                "time_series_dataset_id": str(dataset_id),
                "expected_edit_version": job["edit_version"],
            },
        ).json()
        experiment_id = job["arms"][0]["experiments"][0]["id"]

        response = client.post(
            f"{jobs_url}/{job['id']}/experiments/{experiment_id}/variable-bindings",
            json={
                "model_meaning": "INITIAL_VALUE",
                "target_component_id": "s_not_real",
                "value_source": "CONSTANT",
                "constant_value": "1.0",
                "expected_edit_version": job["edit_version"],
            },
        )
        assert response.status_code == 422


class TestOutputWeightingEndpoint:
    """``docs/32``'s minimal error/weighting contract -- the output-weightings routes."""

    def _job_with_one_experiment(self, client: TestClient, db_session):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        jobs_url = _jobs_url(project_id, subproject_id)
        job = client.post(jobs_url, json={}).json()
        job = client.post(
            f"{jobs_url}/{job['id']}/arms",
            json={"model_id": str(model_id), "expected_edit_version": 0},
        ).json()
        arm_id = job["arms"][0]["id"]
        job = client.post(
            f"{jobs_url}/{job['id']}/arms/{arm_id}/experiments",
            json={
                "time_series_dataset_id": str(dataset_id),
                "expected_edit_version": job["edit_version"],
            },
        ).json()
        experiment_id = job["arms"][0]["experiments"][0]["id"]
        return jobs_url, job, experiment_id

    def test_declaring_a_user_assumed_output_weighting_round_trips(
        self, client: TestClient, db_session
    ):
        jobs_url, job, experiment_id = self._job_with_one_experiment(client, db_session)

        response = client.put(
            f"{jobs_url}/{job['id']}/experiments/{experiment_id}/output-weightings",
            json={
                "output_column_name": "[aRAStot]",
                "uncertainty_source": "USER_ASSUMED",
                "assumed_sigma_value": "0.5",
                "assumed_sigma_statistic_kind": "STANDARD_DEVIATION",
                "relative_output_weight": "1",
                "provenance_note": "assumed from literature",
                "expected_edit_version": job["edit_version"],
            },
        )
        assert response.status_code == 200
        job = response.json()
        experiment = job["arms"][0]["experiments"][0]
        assert experiment["available_output_columns"]
        assert "[aRAStot]" in experiment["available_output_columns"]
        output_weightings = experiment["output_weightings"]
        assert len(output_weightings) == 1
        assert output_weightings[0]["uncertainty_source"] == "USER_ASSUMED"
        assert output_weightings[0]["assumed_sigma_value"] == "0.5"
        assert output_weightings[0]["effective_statistic_kind"] == "STANDARD_DEVIATION"
        assert output_weightings[0]["provenance_note"] == "assumed from literature"

    def test_an_output_weighting_for_an_unreal_output_is_422(self, client: TestClient, db_session):
        jobs_url, job, experiment_id = self._job_with_one_experiment(client, db_session)

        response = client.put(
            f"{jobs_url}/{job['id']}/experiments/{experiment_id}/output-weightings",
            json={
                "output_column_name": "not_a_real_output",
                "uncertainty_source": "UNKNOWN",
                "expected_edit_version": job["edit_version"],
            },
        )
        assert response.status_code == 422

    def test_removing_an_output_weighting_clears_it(self, client: TestClient, db_session):
        jobs_url, job, experiment_id = self._job_with_one_experiment(client, db_session)
        put_response = client.put(
            f"{jobs_url}/{job['id']}/experiments/{experiment_id}/output-weightings",
            json={
                "output_column_name": "[aRAStot]",
                "uncertainty_source": "UNKNOWN",
                "expected_edit_version": job["edit_version"],
            },
        ).json()
        job = put_response
        weighting_id = job["arms"][0]["experiments"][0]["output_weightings"][0]["id"]

        response = client.delete(
            f"{jobs_url}/{job['id']}/output-weightings/{weighting_id}",
            params={"expected_edit_version": job["edit_version"]},
        )
        assert response.status_code == 200
        assert response.json()["arms"][0]["experiments"][0]["output_weightings"] == []
