"""Tests for the Model-Specific Alias Mapping increment's own API surface."""

from __future__ import annotations

import uuid

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
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _mapping_url(project_id, subproject_id, dataset_id, model_id) -> str:
    return (
        f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/datasets/time-series/"
        f"{dataset_id}/alias-mapping/{model_id}"
    )


def _run_record_id(db_session, *, model_id):
    run = create_run_record(
        subproject_id=make_subproject_id(db_session),
        stage=RunStage.HARNESS,
        session=db_session,
        model_id=model_id,
    )
    db_session.flush()
    return run.id


def _seed(db_session, *, available: bool = True):
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

    if available:
        persist_model_species_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=_run_record_id(db_session, model_id=model_id),
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


class TestGetCurrentAliasMapping:
    def test_never_saved_returns_an_all_unresolved_zero_revision(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        response = client.get(_mapping_url(project_id, subproject_id, dataset_id, model_id))
        assert response.status_code == 200
        body = response.json()
        assert body["revision_number"] == 0
        assert body["assignments"] == []
        assert body["model_species_catalog_status"] == "AVAILABLE"
        assert {s["antimony_species_id"] for s in body["available_species"]} == {"s_aRAStot"}
        assert len(body["columns"]) == 5
        assert all(c["unit"] is None for c in body["columns"])  # the fixture declares no units

    def test_an_unavailable_catalog_is_disclosed_with_an_empty_picker(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session, available=False)
        response = client.get(_mapping_url(project_id, subproject_id, dataset_id, model_id))
        assert response.status_code == 200
        body = response.json()
        assert body["model_species_catalog_status"] is None  # never captured at all
        assert body["available_species"] == []

    def test_unknown_dataset_is_404(self, client: TestClient, db_session):
        project_id, subproject_id, _dataset_id, model_id = _seed(db_session)
        response = client.get(
            _mapping_url(project_id, subproject_id, uuid.uuid4(), model_id)
        )
        assert response.status_code == 404


class TestSaveAliasMapping:
    def test_a_valid_save_creates_revision_one(self, client: TestClient, db_session):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        response = client.post(
            _mapping_url(project_id, subproject_id, dataset_id, model_id),
            json={
                "expected_revision_number": 0,
                "assignments": [
                    {
                        "column_name": "[aRAStot]",
                        "status": "ASSIGNED",
                        "target_antimony_species_id": "s_aRAStot",
                    },
                    {"column_name": "[pMEKtot]", "status": "SKIPPED"},
                ],
                "saved_by": "dr-test",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["revision_number"] == 1
        assert body["saved_by"] == "dr-test"
        by_column = {a["column_name"]: a for a in body["assignments"]}
        assert by_column["[aRAStot]"]["target_antimony_species_id"] == "s_aRAStot"
        assert by_column["[aRAStot]"]["unit_finding"] == "UNKNOWN"
        assert by_column["[pMEKtot]"]["status"] == "SKIPPED"
        assert by_column["[pYERKtot]"]["status"] == "UNRESOLVED"

        reopened = client.get(_mapping_url(project_id, subproject_id, dataset_id, model_id))
        assert reopened.json() == body

    def test_a_stale_revision_number_is_409(self, client: TestClient, db_session):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        base_url = _mapping_url(project_id, subproject_id, dataset_id, model_id)
        client.post(base_url, json={"expected_revision_number": 0, "assignments": []})

        response = client.post(base_url, json={"expected_revision_number": 0, "assignments": []})
        assert response.status_code == 409
        assert response.json()["detail"]["context"]["current_revision_number"] == 1

    def test_an_unknown_column_name_is_422(self, client: TestClient, db_session):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        response = client.post(
            _mapping_url(project_id, subproject_id, dataset_id, model_id),
            json={
                "expected_revision_number": 0,
                "assignments": [{"column_name": "sample_id", "status": "SKIPPED"}],
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"]["context"]["unknown_column_names"] == ["sample_id"]

    def test_an_invalid_target_species_is_422(self, client: TestClient, db_session):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        response = client.post(
            _mapping_url(project_id, subproject_id, dataset_id, model_id),
            json={
                "expected_revision_number": 0,
                "assignments": [
                    {
                        "column_name": "[aRAStot]",
                        "status": "ASSIGNED",
                        "target_antimony_species_id": "not_a_real_species",
                    }
                ],
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"]["context"]["invalid_target_ids"] == [
            "not_a_real_species"
        ]

    def test_two_columns_to_the_same_target_is_422_never_combined(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        response = client.post(
            _mapping_url(project_id, subproject_id, dataset_id, model_id),
            json={
                "expected_revision_number": 0,
                "assignments": [
                    {
                        "column_name": "[aRAStot]",
                        "status": "ASSIGNED",
                        "target_antimony_species_id": "s_aRAStot",
                    },
                    {
                        "column_name": "[pMEKtot]",
                        "status": "ASSIGNED",
                        "target_antimony_species_id": "s_aRAStot",
                    },
                ],
            },
        )
        assert response.status_code == 422
        assert "s_aRAStot" in response.json()["detail"]["context"]["conflicts"]

    def test_saving_against_a_never_captured_catalog_is_409(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session, available=False)
        response = client.post(
            _mapping_url(project_id, subproject_id, dataset_id, model_id),
            json={"expected_revision_number": 0, "assignments": []},
        )
        assert response.status_code == 409


class TestAliasMappingRevisionHistory:
    def test_history_lists_every_revision_newest_first(self, client: TestClient, db_session):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        base_url = _mapping_url(project_id, subproject_id, dataset_id, model_id)
        client.post(base_url, json={"expected_revision_number": 0, "assignments": []})
        client.post(base_url, json={"expected_revision_number": 1, "assignments": []})

        history = client.get(f"{base_url}/revisions")
        assert history.status_code == 200
        assert [r["revision_number"] for r in history.json()] == [2, 1]

    def test_reopening_a_specific_past_revision_shows_it_exactly_as_saved(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        base_url = _mapping_url(project_id, subproject_id, dataset_id, model_id)
        client.post(
            base_url,
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
        client.post(
            base_url,
            json={
                "expected_revision_number": 1,
                "assignments": [{"column_name": "[aRAStot]", "status": "SKIPPED"}],
            },
        )

        first_revision = client.get(f"{base_url}/revisions/1")
        assert first_revision.status_code == 200
        by_column = {a["column_name"]: a for a in first_revision.json()["assignments"]}
        assert by_column["[aRAStot]"]["status"] == "ASSIGNED"  # unchanged by revision 2

        unknown_revision = client.get(f"{base_url}/revisions/999")
        assert unknown_revision.status_code == 404
