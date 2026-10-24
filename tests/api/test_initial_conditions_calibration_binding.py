"""API tests wiring the Initial-Conditions Dataset Import increment into calibration
configuration: pinning an experiment's own initial-conditions dataset/mapping, and adding a
value_source=INITIAL_CONDITIONS_DATASET variable binding through the real HTTP surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.models.enums import ModelSpeciesCatalogStatus, RunStage
from app.persistence.initial_conditions_dataset import persist_initial_conditions_dataset
from app.persistence.model_species_catalog import CapturedSpecies, persist_model_species_catalog
from app.persistence.run_record import create_run_record
from app.persistence.time_series_dataset import persist_time_series_dataset
from tests.initial_conditions_helpers import fixture_workbook_bytes as ic_fixture_workbook_bytes
from tests.persistence.conftest import make_model_id, make_project_id, make_subproject_id
from tests.time_series_helpers import fixture_workbook_bytes

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def _jobs_url(project_id, subproject_id) -> str:
    return f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/calibration-jobs"


def _seed(db_session):
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=subproject_id)

    ts_dataset_id = persist_time_series_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename="ras_mapk.xlsx",
        workbook_bytes=fixture_workbook_bytes(),
    ).entity_id
    ic_dataset_id = persist_initial_conditions_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename="abundance.xlsx",
        workbook_bytes=ic_fixture_workbook_bytes(),
    ).entity_id

    run = create_run_record(
        subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session, model_id=model_id
    )
    db_session.flush()
    persist_model_species_catalog(
        session=db_session,
        model_id=model_id,
        source_run_record_id=run.id,
        status=ModelSpeciesCatalogStatus.AVAILABLE,
        species=[
            CapturedSpecies(
                antimony_species_id="s_EGFR",
                canonical_species_id="canonical-s_EGFR",
                display_name="EGFR",
                compartment_id="c1",
                compartment_name="cyto",
                kind="FLOATING",
            )
        ],
    )
    db_session.commit()
    return project_id, subproject_id, ts_dataset_id, ic_dataset_id, model_id


class TestPinInitialConditionsDataset:
    def test_pin_dataset_then_mapping_then_add_a_binding_that_reads_it(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, ts_dataset_id, ic_dataset_id, model_id = _seed(db_session)
        jobs_url = _jobs_url(project_id, subproject_id)

        job = client.post(jobs_url, json={"created_by": "dr-test"}).json()
        job = client.post(
            f"{jobs_url}/{job['id']}/arms",
            json={"model_id": str(model_id), "expected_edit_version": 0},
        ).json()
        arm_id = job["arms"][0]["id"]
        job = client.post(
            f"{jobs_url}/{job['id']}/arms/{arm_id}/experiments",
            json={"time_series_dataset_id": str(ts_dataset_id), "expected_edit_version": 1},
        ).json()
        experiment_id = job["arms"][0]["experiments"][0]["id"]
        assert job["arms"][0]["experiments"][0]["initial_conditions_dataset_id"] is None
        assert job["arms"][0]["experiments"][0]["available_initial_conditions_columns"] == []

        job = client.patch(
            f"{jobs_url}/{job['id']}/experiments/{experiment_id}/initial-conditions-dataset",
            json={
                "initial_conditions_dataset_id": str(ic_dataset_id),
                "expected_edit_version": job["edit_version"],
            },
        ).json()
        experiment = job["arms"][0]["experiments"][0]
        assert experiment["initial_conditions_dataset_id"] == str(ic_dataset_id)
        assert experiment["available_initial_conditions_columns"] == ["Abundance"]
        assert experiment["initial_conditions_alias_mapping_revision_id"] is None

        ic_mapping_response = client.post(
            f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/datasets/"
            f"initial-conditions/{ic_dataset_id}/alias-mapping/{model_id}",
            json={
                "expected_revision_number": 0,
                "assignments": [
                    {
                        "target_name": "EGFR",
                        "status": "ASSIGNED",
                        "target_kind": "SPECIES",
                        "target_id": "s_EGFR",
                    }
                ],
            },
        )
        assert ic_mapping_response.status_code == 201

        job = client.patch(
            f"{jobs_url}/{job['id']}/experiments/{experiment_id}/initial-conditions-mapping",
            json={
                "alias_mapping_revision_number": ic_mapping_response.json()["revision_number"],
                "expected_edit_version": job["edit_version"],
            },
        ).json()
        experiment = job["arms"][0]["experiments"][0]
        assert experiment["initial_conditions_alias_mapping_revision_id"] is not None
        assert experiment["initial_conditions_mapping_is_stale"] is False

        job = client.post(
            f"{jobs_url}/{job['id']}/experiments/{experiment_id}/variable-bindings",
            json={
                "model_meaning": "INITIAL_VALUE",
                "target_component_id": "s_EGFR",
                "value_source": "INITIAL_CONDITIONS_DATASET",
                "source_column_name": "Abundance",
                "expected_edit_version": job["edit_version"],
            },
        ).json()
        binding = job["arms"][0]["experiments"][0]["variable_bindings"][0]
        assert binding["model_meaning"] == "INITIAL_VALUE"
        assert binding["value_source"] == "INITIAL_CONDITIONS_DATASET"
        assert binding["source_column_name"] == "Abundance"

    def test_a_binding_naming_an_unpinned_dataset_column_is_422(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, ts_dataset_id, _ic_dataset_id, model_id = _seed(db_session)
        jobs_url = _jobs_url(project_id, subproject_id)

        job = client.post(jobs_url, json={"created_by": "dr-test"}).json()
        job = client.post(
            f"{jobs_url}/{job['id']}/arms",
            json={"model_id": str(model_id), "expected_edit_version": 0},
        ).json()
        arm_id = job["arms"][0]["id"]
        job = client.post(
            f"{jobs_url}/{job['id']}/arms/{arm_id}/experiments",
            json={"time_series_dataset_id": str(ts_dataset_id), "expected_edit_version": 1},
        ).json()
        experiment_id = job["arms"][0]["experiments"][0]["id"]

        response = client.post(
            f"{jobs_url}/{job['id']}/experiments/{experiment_id}/variable-bindings",
            json={
                "model_meaning": "INITIAL_VALUE",
                "target_component_id": "s_EGFR",
                "value_source": "INITIAL_CONDITIONS_DATASET",
                "source_column_name": "Abundance",
                "expected_edit_version": job["edit_version"],
            },
        )
        assert response.status_code == 422
