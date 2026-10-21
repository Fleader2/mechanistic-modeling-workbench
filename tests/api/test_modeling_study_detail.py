"""Tests for ``GET /api/v1/projects/{project_id}/subprojects/{subproject_id}``
(the "03 — Modeling Study" screen's own metadata).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.models.enums import SubprojectTaskType
from app.persistence.subproject import persist_subproject
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def test_get_one_modeling_study(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    result = persist_subproject(
        project_id=project_id,
        title="ACC1 perturbation",
        objective="How does reduced ACC1 activity alter flux?",
        task_type=SubprojectTaskType.BUILD_MODEL,
        session=db_session,
    )

    response = client.get(f"{PROJECTS_URL}/{project_id}/subprojects/{result.entity_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(result.entity_id)
    assert body["project_id"] == str(project_id)
    assert body["title"] == "ACC1 perturbation"
    assert body["objective"] == "How does reduced ACC1 activity alter flux?"
    assert body["task_type"] == "BUILD_MODEL"
    assert body["status"] == "ACTIVE"
    assert body["created_at"]


def test_get_modeling_study_for_unknown_project_returns_404(client: TestClient, db_session) -> None:
    subproject_id = make_subproject_id(db_session)

    response = client.get(f"{PROJECTS_URL}/{uuid.uuid4()}/subprojects/{subproject_id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_get_unknown_modeling_study_returns_404(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)

    response = client.get(f"{PROJECTS_URL}/{project_id}/subprojects/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_get_modeling_study_belonging_to_a_different_project_returns_404_not_the_study(
    client: TestClient, db_session
) -> None:
    owning_project_id = make_project_id(db_session)
    other_project_id = make_project_id(db_session)
    study_id = make_subproject_id(db_session, project_id=owning_project_id)

    response = client.get(f"{PROJECTS_URL}/{other_project_id}/subprojects/{study_id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_get_modeling_study_rejects_malformed_project_id_with_422(client: TestClient) -> None:
    response = client.get(f"{PROJECTS_URL}/not-a-uuid/subprojects/{uuid.uuid4()}")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_get_modeling_study_rejects_malformed_study_id_with_422(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)

    response = client.get(f"{PROJECTS_URL}/{project_id}/subprojects/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"
