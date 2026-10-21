"""Tests for ``GET /api/v1/projects/{project_id}/subprojects`` (the "Modeling
Studies" table on the "02 — Current Project" screen).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.models.enums import ModelSourceType, SubprojectTaskType
from app.persistence.dataset_reference import persist_dataset_reference
from app.persistence.model import persist_model
from app.persistence.subproject import persist_subproject
from tests.persistence.conftest import make_project_id

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def test_list_modeling_studies_empty_for_project_with_none(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)

    response = client.get(f"{PROJECTS_URL}/{project_id}/subprojects")

    assert response.status_code == 200
    assert response.json() == []


def test_list_modeling_studies_returns_counts_and_ordering(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    study_a = persist_subproject(
        project_id=project_id,
        title="zz last study",
        objective="How does reduced ACC1 activity alter flux?",
        task_type=SubprojectTaskType.BUILD_MODEL,
        session=db_session,
    ).entity_id
    study_b = persist_subproject(
        project_id=project_id,
        title="aa first study",
        task_type=SubprojectTaskType.CALIBRATE_MODEL,
        session=db_session,
    ).entity_id
    persist_model(
        subproject_id=study_a,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="model one",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )
    persist_model(
        subproject_id=study_a,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="model two",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )
    persist_dataset_reference(
        project_id=project_id,
        subproject_id=study_a,
        name="dataset one",
        dataset_type="experimental_observation",
        artifact_reference="s3://bucket/one.csv",
        session=db_session,
    )
    # Scoped to the project only -- must never inflate any study's count.
    persist_dataset_reference(
        project_id=project_id,
        name="project-wide dataset",
        dataset_type="experimental_observation",
        artifact_reference="s3://bucket/project-wide.csv",
        session=db_session,
    )

    response = client.get(f"{PROJECTS_URL}/{project_id}/subprojects")

    assert response.status_code == 200
    body = response.json()
    assert [row["title"] for row in body] == ["aa first study", "zz last study"]
    first_study, last_study = body
    assert first_study["id"] == str(study_b)
    assert first_study["objective"] is None
    assert first_study["model_count"] == 0
    assert first_study["dataset_count"] == 0
    assert last_study["id"] == str(study_a)
    assert last_study["objective"] == "How does reduced ACC1 activity alter flux?"
    assert last_study["model_count"] == 2
    assert last_study["dataset_count"] == 1


def test_list_modeling_studies_for_unknown_project_returns_404_not_empty_list(
    client: TestClient,
) -> None:
    response = client.get(f"{PROJECTS_URL}/{uuid.uuid4()}/subprojects")

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["code"] == "NOT_FOUND"


def test_list_modeling_studies_rejects_malformed_id_with_422(client: TestClient) -> None:
    response = client.get(f"{PROJECTS_URL}/not-a-uuid/subprojects")

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "VALIDATION_ERROR"
