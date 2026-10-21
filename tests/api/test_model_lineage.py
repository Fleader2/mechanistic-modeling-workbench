"""Tests for
``GET /api/v1/projects/{project_id}/subprojects/{subproject_id}/models/{model_id}/lineage``
(the "05 — Model Overview" screen's own "History" tab).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from tests.persistence.conftest import make_model_id, make_project_id, make_subproject_id

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def test_lineage_empty_for_model_with_no_parent_or_children(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=subproject_id)

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/models/{model_id}/lineage"
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "parent": None,
        "parent_out_of_scope": False,
        "children": [],
        "children_out_of_scope_count": 0,
    }


def test_lineage_includes_parent_and_children_within_the_same_study(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    parent_id = make_model_id(db_session, subproject_id=subproject_id, name="draft model")
    model_id = make_model_id(
        db_session, subproject_id=subproject_id, name="calibrated model", parent_model_id=parent_id
    )
    child_id = make_model_id(
        db_session, subproject_id=subproject_id, name="later model", parent_model_id=model_id
    )

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/models/{model_id}/lineage"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["parent"]["id"] == str(parent_id)
    assert body["parent"]["name"] == "draft model"
    assert body["parent_out_of_scope"] is False
    assert [c["id"] for c in body["children"]] == [str(child_id)]
    assert body["children_out_of_scope_count"] == 0


def test_lineage_discloses_out_of_scope_parent_without_leaking_it(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    owning_study_id = make_subproject_id(db_session, project_id=project_id)
    other_study_id = make_subproject_id(db_session, project_id=project_id)
    parent_id = make_model_id(
        db_session, subproject_id=other_study_id, name="parent in a different study"
    )
    model_id = make_model_id(
        db_session, subproject_id=owning_study_id, name="model", parent_model_id=parent_id
    )

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{owning_study_id}/models/{model_id}/lineage"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["parent"] is None
    assert body["parent_out_of_scope"] is True


def test_lineage_discloses_out_of_scope_children_count_without_leaking_them(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    owning_study_id = make_subproject_id(db_session, project_id=project_id)
    other_study_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=owning_study_id, name="model")
    make_model_id(
        db_session,
        subproject_id=owning_study_id,
        name="in-scope child",
        parent_model_id=model_id,
    )
    make_model_id(
        db_session,
        subproject_id=other_study_id,
        name="out-of-scope child",
        parent_model_id=model_id,
    )

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{owning_study_id}/models/{model_id}/lineage"
    )

    assert response.status_code == 200
    body = response.json()
    assert [c["name"] for c in body["children"]] == ["in-scope child"]
    assert body["children_out_of_scope_count"] == 1


def test_lineage_for_unknown_project_returns_404(client: TestClient, db_session) -> None:
    model_id = make_model_id(db_session)

    response = client.get(
        f"{PROJECTS_URL}/{uuid.uuid4()}/subprojects/{uuid.uuid4()}/models/{model_id}/lineage"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_lineage_for_model_belonging_to_a_different_study_returns_404(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    owning_study_id = make_subproject_id(db_session, project_id=project_id)
    other_study_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=owning_study_id)

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{other_study_id}/models/{model_id}/lineage"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_lineage_rejects_malformed_model_id_with_422(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/models/not-a-uuid/lineage"
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"
