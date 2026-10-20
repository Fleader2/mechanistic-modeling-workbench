"""Tests for ``GET /api/v1/projects`` and ``GET /api/v1/projects/{id}``."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.models.enums import ProjectType, SubprojectTaskType
from app.persistence.project import persist_project
from app.persistence.subproject import persist_subproject
from tests.persistence.conftest import make_project_id

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def _stable_identifier() -> str:
    return f"PROJ_{uuid.uuid4().hex[:8]}"


def test_list_projects_empty(client: TestClient) -> None:
    response = client.get(PROJECTS_URL)

    assert response.status_code == 200
    assert response.json() == []


def test_list_projects_returns_every_project_with_study_count(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(
        db_session,
        stable_identifier=_stable_identifier(),
        title="Central Carbon Reconstruction",
        project_type=ProjectType.MICROBIAL_METABOLISM,
        biological_context_summary="E. coli · K-12",
    )
    persist_subproject(
        project_id=project_id,
        title="first study",
        task_type=SubprojectTaskType.BUILD_MODEL,
        session=db_session,
    )
    persist_subproject(
        project_id=project_id,
        title="second study",
        task_type=SubprojectTaskType.CALIBRATE_MODEL,
        session=db_session,
    )
    make_project_id(
        db_session,
        stable_identifier=_stable_identifier(),
        title="Zero-study project",
        project_type=ProjectType.REGULATORY_NETWORK,
    )

    response = client.get(PROJECTS_URL)

    assert response.status_code == 200
    body = response.json()
    assert [row["title"] for row in body] == [
        "Central Carbon Reconstruction",
        "Zero-study project",
    ]
    with_studies, without_studies = body
    assert with_studies["study_count"] == 2
    assert with_studies["project_type"] == "MICROBIAL_METABOLISM"
    assert with_studies["biological_context_summary"] == "E. coli · K-12"
    assert without_studies["study_count"] == 0
    assert without_studies["biological_context_summary"] is None


def test_get_one_project(client: TestClient, db_session) -> None:
    stable_identifier = _stable_identifier()
    result = persist_project(
        stable_identifier=stable_identifier,
        title="Yeast Fatty Acid Engineering",
        project_type=ProjectType.MICROBIAL_METABOLISM,
        session=db_session,
        strain_genotype_notes="BY4741",
    )

    response = client.get(f"{PROJECTS_URL}/{result.entity_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(result.entity_id)
    assert body["stable_identifier"] == stable_identifier
    assert body["title"] == "Yeast Fatty Acid Engineering"
    assert body["strain_genotype_notes"] == "BY4741"
    assert body["created_at"]


def test_get_unknown_project_returns_404_not_500(client: TestClient) -> None:
    response = client.get(f"{PROJECTS_URL}/{uuid.uuid4()}")

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["code"] == "NOT_FOUND"


def test_get_project_rejects_malformed_id_with_422(client: TestClient) -> None:
    response = client.get(f"{PROJECTS_URL}/not-a-uuid")

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "VALIDATION_ERROR"
