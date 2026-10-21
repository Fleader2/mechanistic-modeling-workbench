"""Tests for
``GET /api/v1/projects/{project_id}/subprojects/{subproject_id}/models``
(the "03 — Modeling Study" screen's "Models" table).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.models.enums import ModelSourceType, ModelStatus
from app.persistence.model import persist_model
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def test_list_modeling_study_models_empty_for_study_with_none(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    study_id = make_subproject_id(db_session, project_id=project_id)

    response = client.get(f"{PROJECTS_URL}/{project_id}/subprojects/{study_id}/models")

    assert response.status_code == 200
    assert response.json() == []


def test_list_modeling_study_models_returns_identity_version_and_status_ordered_by_name(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    study_id = make_subproject_id(db_session, project_id=project_id)
    other_study_id = make_subproject_id(db_session, project_id=project_id)
    first = persist_model(
        subproject_id=study_id,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="zz curated fatty acid model",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
        status=ModelStatus.ACTIVE,
        version_label="v1.3",
    )
    second = persist_model(
        subproject_id=study_id,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="aa draft pathway model",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )
    # Belongs to a different study -- must never appear in this study's list.
    persist_model(
        subproject_id=other_study_id,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="belongs to a different study",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )

    response = client.get(f"{PROJECTS_URL}/{project_id}/subprojects/{study_id}/models")

    assert response.status_code == 200
    body = response.json()
    assert [row["name"] for row in body] == [
        "aa draft pathway model",
        "zz curated fatty acid model",
    ]
    draft, curated = body
    assert draft["id"] == str(second.entity_id)
    assert draft["version_label"] is None
    assert draft["status"] == "DRAFT"
    assert curated["id"] == str(first.entity_id)
    assert curated["version_label"] == "v1.3"
    assert curated["status"] == "ACTIVE"
    # Never invented: Figma's "Construction" / "Calibration / validation"
    # columns have no backing schema and must not appear here.
    assert "construction" not in curated
    assert "calibration" not in curated


def test_list_modeling_study_models_for_unknown_project_returns_404_not_empty_list(
    client: TestClient, db_session
) -> None:
    study_id = make_subproject_id(db_session)

    response = client.get(f"{PROJECTS_URL}/{uuid.uuid4()}/subprojects/{study_id}/models")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_list_modeling_study_models_for_unknown_study_returns_404_not_empty_list(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)

    response = client.get(f"{PROJECTS_URL}/{project_id}/subprojects/{uuid.uuid4()}/models")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_list_modeling_study_models_for_ownership_mismatch_returns_404_not_the_models(
    client: TestClient, db_session
) -> None:
    owning_project_id = make_project_id(db_session)
    other_project_id = make_project_id(db_session)
    study_id = make_subproject_id(db_session, project_id=owning_project_id)
    persist_model(
        subproject_id=study_id,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="should never leak through the wrong project",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )

    response = client.get(f"{PROJECTS_URL}/{other_project_id}/subprojects/{study_id}/models")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_list_modeling_study_models_rejects_malformed_study_id_with_422(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)

    response = client.get(f"{PROJECTS_URL}/{project_id}/subprojects/not-a-uuid/models")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"
