"""Tests for ``GET /api/v1/projects/{project_id}/subprojects/{subproject_id}/hierarchical-runs``
(the "pick a run to draft a module set from" list)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from tests.persistence.conftest import (
    make_project_id,
    make_subproject_id,
    make_succeeded_hierarchical_run,
)

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def test_list_draftable_runs_empty_for_study_with_none(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/hierarchical-runs"
    )

    assert response.status_code == 200
    assert response.json() == []


def test_list_draftable_runs_returns_module_count_and_excludes_model_less_runs(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    draftable = make_succeeded_hierarchical_run(
        db_session, subproject_id=subproject_id, leaf_count=3
    )
    make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id, include_model=False)

    response = client.get(
        f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/hierarchical-runs"
    )

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body] == [str(draftable.id)]
    assert body[0]["module_count"] == 3
    assert body[0]["model_id"] == str(draftable.model_id)


def test_list_draftable_runs_for_unknown_project_returns_404(client: TestClient) -> None:
    response = client.get(
        f"{PROJECTS_URL}/{uuid.uuid4()}/subprojects/{uuid.uuid4()}/hierarchical-runs"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"
