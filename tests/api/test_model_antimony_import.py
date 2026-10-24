"""Tests for the Whole-Model Antimony Import increment's own API surface (``docs/34``) --
upload/preview/save, read-only Antimony source, import provenance, and ownership isolation.
Real harness/Agent 2/Agent 3 execution every time a file is actually processed, never mocked.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"

_VALID_ANTIMONY_TEXT = b"""
model decay_model
  compartment C1
  C1 = 1.0
  species S1 in C1
  species S2 in C1
  S1 = 10
  S2 = 0
  R1: S1 -> S2; k1*S1
  k1 = 0.1
end
"""


def _models_url(project_id, subproject_id) -> str:
    return f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/models"


def _seed(db_session):
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    db_session.commit()
    return project_id, subproject_id


class TestPreview:
    def test_preview_returns_findings_without_persisting(self, client: TestClient, db_session):
        project_id, subproject_id = _seed(db_session)
        url = f"{_models_url(project_id, subproject_id)}/antimony-import/preview"

        response = client.post(
            url, files={"file": ("decay.antimony", _VALID_ANTIMONY_TEXT, "text/plain")}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["load_succeeded"] is True
        assert sorted(body["floating_species_ids"]) == ["S1", "S2"]
        assert body["import_succeeded"] is True

        listing = client.get(_models_url(project_id, subproject_id))
        assert listing.json() == []

    def test_malformed_upload_previews_honestly_as_a_200(self, client: TestClient, db_session):
        project_id, subproject_id = _seed(db_session)
        url = f"{_models_url(project_id, subproject_id)}/antimony-import/preview"
        response = client.post(
            url, files={"file": ("garbage.antimony", b"not valid antimony !!!", "text/plain")}
        )
        assert response.status_code == 200
        assert response.json()["load_succeeded"] is False

    def test_non_utf8_upload_is_a_422(self, client: TestClient, db_session):
        project_id, subproject_id = _seed(db_session)
        url = f"{_models_url(project_id, subproject_id)}/antimony-import/preview"
        response = client.post(
            url, files={"file": ("binary.antimony", b"\xff\xfe\x00\x01", "text/plain")}
        )
        assert response.status_code == 422


class TestSave:
    def test_save_creates_a_model_and_returns_detail(self, client: TestClient, db_session):
        project_id, subproject_id = _seed(db_session)
        url = _models_url(project_id, subproject_id) + "/antimony-import"

        response = client.post(
            url,
            files={"file": ("decay.antimony", _VALID_ANTIMONY_TEXT, "text/plain")},
            data={"name": "Decay model", "source_reference": "unit test"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "Decay model"
        assert body["source_type"] == "IMPORTED"
        assert body["status"] == "ACTIVE"

        listing = client.get(_models_url(project_id, subproject_id))
        assert len(listing.json()) == 1

    def test_save_requires_a_name(self, client: TestClient, db_session):
        project_id, subproject_id = _seed(db_session)
        url = _models_url(project_id, subproject_id) + "/antimony-import"
        response = client.post(
            url,
            files={"file": ("decay.antimony", _VALID_ANTIMONY_TEXT, "text/plain")},
            data={"name": "   "},
        )
        assert response.status_code == 422

    def test_malformed_antimony_is_a_422_with_no_model_created(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id = _seed(db_session)
        url = _models_url(project_id, subproject_id) + "/antimony-import"
        response = client.post(
            url,
            files={"file": ("garbage.antimony", b"not valid antimony !!!", "text/plain")},
            data={"name": "Should never exist"},
        )
        assert response.status_code == 422
        assert client.get(_models_url(project_id, subproject_id)).json() == []

    def test_an_unknown_subproject_is_a_404(self, client: TestClient, db_session):
        project_id, _subproject_id = _seed(db_session)
        import uuid

        url = f"{PROJECTS_URL}/{project_id}/subprojects/{uuid.uuid4()}/models/antimony-import"
        response = client.post(
            url,
            files={"file": ("decay.antimony", _VALID_ANTIMONY_TEXT, "text/plain")},
            data={"name": "Should never exist"},
        )
        assert response.status_code == 404


class TestAntimonySourceAndProvenance:
    def test_antimony_source_and_provenance_are_readable_after_save(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id = _seed(db_session)
        save_response = client.post(
            _models_url(project_id, subproject_id) + "/antimony-import",
            files={"file": ("decay.antimony", _VALID_ANTIMONY_TEXT, "text/plain")},
            data={"name": "Decay model", "verification_notes": "looks right"},
        )
        model_id = save_response.json()["id"]
        models_url = _models_url(project_id, subproject_id)

        source_response = client.get(f"{models_url}/{model_id}/antimony-source")
        assert source_response.status_code == 200
        assert "model decay_model" in source_response.json()["antimony_text"]

        provenance_response = client.get(f"{models_url}/{model_id}/import-provenance")
        assert provenance_response.status_code == 200
        provenance = provenance_response.json()
        assert provenance is not None
        assert provenance["original_filename"] == "decay.antimony"
        assert provenance["verification_notes"] == "looks right"
        assert provenance["import_succeeded"] is True

    def test_antimony_source_is_a_404_for_a_model_with_no_captured_catalog(
        self, client: TestClient, db_session
    ):
        from app.models.enums import ModelSourceType
        from app.persistence.model import persist_model

        project_id, subproject_id = _seed(db_session)
        result = persist_model(
            subproject_id=subproject_id,
            stable_identifier="no-catalog-model",
            name="No catalog",
            source_type=ModelSourceType.GENERATED,
            session=db_session,
        )
        db_session.commit()
        models_url = _models_url(project_id, subproject_id)
        response = client.get(f"{models_url}/{result.entity_id}/antimony-source")
        assert response.status_code == 404

    def test_import_provenance_is_null_for_a_non_imported_model(
        self, client: TestClient, db_session
    ):
        from app.models.enums import ModelSourceType
        from app.persistence.model import persist_model

        project_id, subproject_id = _seed(db_session)
        result = persist_model(
            subproject_id=subproject_id,
            stable_identifier="generated-model",
            name="Generated",
            source_type=ModelSourceType.GENERATED,
            session=db_session,
        )
        db_session.commit()
        models_url = _models_url(project_id, subproject_id)
        response = client.get(f"{models_url}/{result.entity_id}/import-provenance")
        assert response.status_code == 200
        assert response.json() is None


class TestOwnershipIsolation:
    def test_a_model_is_not_reachable_through_an_unrelated_subproject(
        self, client: TestClient, db_session
    ):
        project_id, subproject_id = _seed(db_session)
        save_response = client.post(
            _models_url(project_id, subproject_id) + "/antimony-import",
            files={"file": ("decay.antimony", _VALID_ANTIMONY_TEXT, "text/plain")},
            data={"name": "Decay model"},
        )
        model_id = save_response.json()["id"]

        other_project_id = make_project_id(db_session)
        other_subproject_id = make_subproject_id(db_session, project_id=other_project_id)
        db_session.commit()

        other_url = _models_url(project_id, other_subproject_id)
        assert client.get(f"{other_url}/{model_id}/antimony-source").status_code == 404
        assert client.get(f"{other_url}/{model_id}/import-provenance").status_code == 404
