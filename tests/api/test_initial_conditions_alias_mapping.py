"""Tests for the Initial-Conditions Dataset Import increment's own alias-mapping API surface.
Mirrors ``tests.api.test_dataset_model_alias_mapping``'s own identical convention."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.models.enums import (
    ModelParameterCatalogStatus,
    ModelParameterKind,
    ModelSpeciesCatalogStatus,
    RunStage,
)
from app.persistence.initial_conditions_dataset import persist_initial_conditions_dataset
from app.persistence.model_parameter_catalog import (
    CapturedParameter,
    persist_model_parameter_catalog,
)
from app.persistence.model_species_catalog import CapturedSpecies, persist_model_species_catalog
from app.persistence.run_record import create_run_record
from tests.initial_conditions_helpers import fixture_workbook_bytes
from tests.persistence.conftest import make_model_id, make_project_id, make_subproject_id

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def _mapping_url(project_id, subproject_id, dataset_id, model_id) -> str:
    return (
        f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/datasets/initial-conditions/"
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
    """A saved initial-conditions dataset (EGFR/Grb2/SOS1/RAS) plus (optionally) a real
    species catalog (EGFR) and a real parameter catalog (SOS1_rate) for the same model."""
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=subproject_id)

    dataset_id = persist_initial_conditions_dataset(
        session=db_session,
        project_id=project_id,
        subproject_id=subproject_id,
        original_filename="abundance.xlsx",
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
                    antimony_species_id="s_EGFR",
                    canonical_species_id="canonical-s_EGFR",
                    display_name="EGFR",
                    compartment_id="c1",
                    compartment_name="cyto",
                    kind="FLOATING",
                )
            ],
        )
        persist_model_parameter_catalog(
            session=db_session,
            model_id=model_id,
            source_run_record_id=_run_record_id(db_session, model_id=model_id),
            status=ModelParameterCatalogStatus.AVAILABLE,
            parameters=[
                CapturedParameter(
                    antimony_parameter_id="SOS1_rate",
                    canonical_parameter_id="canonical-SOS1_rate",
                    display_name="SOS1 rate",
                    kind=ModelParameterKind.INDEPENDENT.value,
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
        assert body["model_parameter_catalog_status"] == "AVAILABLE"
        assert {s["antimony_species_id"] for s in body["available_species"]} == {"s_EGFR"}
        assert {p["antimony_parameter_id"] for p in body["available_parameters"]} == {
            "SOS1_rate"
        }
        assert {t["target_name"] for t in body["targets"]} == {"EGFR", "Grb2", "SOS1", "RAS"}

    def test_neither_catalog_available_is_disclosed_with_empty_pickers(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session, available=False)
        response = client.get(_mapping_url(project_id, subproject_id, dataset_id, model_id))
        assert response.status_code == 200
        body = response.json()
        assert body["model_species_catalog_status"] is None
        assert body["model_parameter_catalog_status"] is None
        assert body["available_species"] == []
        assert body["available_parameters"] == []

    def test_unknown_dataset_is_404(self, client: TestClient, db_session):
        project_id, subproject_id, _dataset_id, model_id = _seed(db_session)
        response = client.get(
            _mapping_url(project_id, subproject_id, uuid.uuid4(), model_id)
        )
        assert response.status_code == 404


class TestSaveAliasMapping:
    def test_a_valid_mixed_species_and_parameter_save_creates_revision_one(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        response = client.post(
            _mapping_url(project_id, subproject_id, dataset_id, model_id),
            json={
                "expected_revision_number": 0,
                "assignments": [
                    {
                        "target_name": "EGFR",
                        "status": "ASSIGNED",
                        "target_kind": "SPECIES",
                        "target_id": "s_EGFR",
                    },
                    {
                        "target_name": "SOS1",
                        "status": "ASSIGNED",
                        "target_kind": "PARAMETER",
                        "target_id": "SOS1_rate",
                    },
                    {"target_name": "RAS", "status": "SKIPPED"},
                ],
                "saved_by": "dr-test",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["revision_number"] == 1
        assert body["saved_by"] == "dr-test"
        by_name = {a["target_name"]: a for a in body["assignments"]}
        assert by_name["EGFR"]["target_id"] == "s_EGFR"
        assert by_name["SOS1"]["target_id"] == "SOS1_rate"
        assert by_name["RAS"]["status"] == "SKIPPED"
        assert by_name["Grb2"]["status"] == "UNRESOLVED"

        reopened = client.get(_mapping_url(project_id, subproject_id, dataset_id, model_id))
        assert reopened.json() == body

    def test_a_stale_revision_number_is_409(self, client: TestClient, db_session):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        base_url = _mapping_url(project_id, subproject_id, dataset_id, model_id)
        client.post(base_url, json={"expected_revision_number": 0, "assignments": []})

        response = client.post(base_url, json={"expected_revision_number": 0, "assignments": []})
        assert response.status_code == 409
        assert response.json()["detail"]["context"]["current_revision_number"] == 1

    def test_an_unknown_target_name_is_422(self, client: TestClient, db_session):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        response = client.post(
            _mapping_url(project_id, subproject_id, dataset_id, model_id),
            json={
                "expected_revision_number": 0,
                "assignments": [{"target_name": "not_real", "status": "SKIPPED"}],
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"]["context"]["unknown_target_names"] == ["not_real"]

    def test_an_invalid_target_id_is_422(self, client: TestClient, db_session):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        response = client.post(
            _mapping_url(project_id, subproject_id, dataset_id, model_id),
            json={
                "expected_revision_number": 0,
                "assignments": [
                    {
                        "target_name": "EGFR",
                        "status": "ASSIGNED",
                        "target_kind": "SPECIES",
                        "target_id": "not_a_real_species",
                    }
                ],
            },
        )
        assert response.status_code == 422
        assert "EGFR=" in response.json()["detail"]["context"]["invalid"][0]

    def test_two_targets_to_the_same_id_is_422_never_combined(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id, dataset_id, model_id = _seed(db_session)
        response = client.post(
            _mapping_url(project_id, subproject_id, dataset_id, model_id),
            json={
                "expected_revision_number": 0,
                "assignments": [
                    {
                        "target_name": "EGFR",
                        "status": "ASSIGNED",
                        "target_kind": "SPECIES",
                        "target_id": "s_EGFR",
                    },
                    {
                        "target_name": "Grb2",
                        "status": "ASSIGNED",
                        "target_kind": "SPECIES",
                        "target_id": "s_EGFR",
                    },
                ],
            },
        )
        assert response.status_code == 422
        assert "SPECIES:s_EGFR" in response.json()["detail"]["context"]["conflicts"]

    def test_saving_against_no_captured_catalog_at_all_is_409(
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
                        "target_name": "EGFR",
                        "status": "ASSIGNED",
                        "target_kind": "SPECIES",
                        "target_id": "s_EGFR",
                    }
                ],
            },
        )
        client.post(
            base_url,
            json={
                "expected_revision_number": 1,
                "assignments": [{"target_name": "EGFR", "status": "SKIPPED"}],
            },
        )

        first_revision = client.get(f"{base_url}/revisions/1")
        assert first_revision.status_code == 200
        by_name = {a["target_name"]: a for a in first_revision.json()["assignments"]}
        assert by_name["EGFR"]["status"] == "ASSIGNED"  # unchanged by revision 2

        unknown_revision = client.get(f"{base_url}/revisions/999")
        assert unknown_revision.status_code == 404
