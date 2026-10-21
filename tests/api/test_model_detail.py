"""Tests for
``GET /api/v1/projects/{project_id}/subprojects/{subproject_id}/models/{model_id}``
(the "05 — Model Overview" screen's own metadata).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.models.enums import ModelSourceType, ModelStatus
from app.persistence.model import persist_model
from tests.persistence.conftest import make_model_id, make_project_id, make_subproject_id

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def test_get_one_model(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    result = persist_model(
        subproject_id=subproject_id,
        stable_identifier="MOD-001",
        name="Curated fatty acid model",
        source_type=ModelSourceType.GENERATED,
        status=ModelStatus.ACTIVE,
        version_label="v1.3",
        artifact_reference="harness-run://runs/2026-10-13/model.json",
        notes="Shared reference model.",
        session=db_session,
    )

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/models/{result.entity_id}"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(result.entity_id)
    assert body["subproject_id"] == str(subproject_id)
    assert body["stable_identifier"] == "MOD-001"
    assert body["name"] == "Curated fatty acid model"
    assert body["source_type"] == "GENERATED"
    assert body["status"] == "ACTIVE"
    assert body["version_label"] == "v1.3"
    assert body["artifact_reference"] == "harness-run://runs/2026-10-13/model.json"
    assert body["notes"] == "Shared reference model."
    assert body["created_at"]
    # Never invented: Figma's "Scope" / "Structure" / "Parameters" counts and
    # "Construction/Calibration/Validation" sentence have no backing column.
    assert "scope" not in body
    assert "structure" not in body


def test_get_model_for_unknown_project_returns_404(client: TestClient, db_session) -> None:
    model_id = make_model_id(db_session)

    response = client.get(
        f"{PROJECTS_URL}/{uuid.uuid4()}/subprojects/{uuid.uuid4()}/models/{model_id}"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_get_model_for_unknown_study_returns_404(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    model_id = make_model_id(db_session)

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{uuid.uuid4()}/models/{model_id}"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_get_unknown_model_returns_404(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/models/{uuid.uuid4()}"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_get_model_belonging_to_a_different_study_returns_404_not_the_model(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    owning_study_id = make_subproject_id(db_session, project_id=project_id)
    other_study_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=owning_study_id)

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{other_study_id}/models/{model_id}"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_get_model_belonging_to_a_different_project_returns_404_not_the_model(
    client: TestClient, db_session
) -> None:
    owning_project_id = make_project_id(db_session)
    owning_study_id = make_subproject_id(db_session, project_id=owning_project_id)
    model_id = make_model_id(db_session, subproject_id=owning_study_id)
    other_project_id = make_project_id(db_session)
    other_study_id = make_subproject_id(db_session, project_id=other_project_id)

    response = client.get(
        f"{PROJECTS_URL}/{other_project_id}/subprojects/{other_study_id}/models/{model_id}"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_get_model_rejects_malformed_model_id_with_422(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/models/not-a-uuid"
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"
