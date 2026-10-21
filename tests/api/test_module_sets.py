"""Tests for the Module-Set first increment's own API surface: creating/inspecting/discarding/
saving a draft, reopening a saved version, and inspecting a member's own boundary ports.

See ``docs/21_module_set_first_increment.md``. Covers, per this increment's own explicit testing
requirements: ownership isolation, save idempotency/duplicate-save protection, and immutability
of a reopened version -- the API-layer counterparts of ``tests/persistence/test_module_set.py``'s
own equivalent coverage.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.persistence.model_module import list_model_modules_for_run
from app.persistence.module_boundary_port import persist_candidate_boundary_ports
from tests.persistence.conftest import (
    make_model_id,
    make_project_id,
    make_subproject_id,
    make_succeeded_hierarchical_run,
)

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def _drafts_url(project_id, subproject_id) -> str:
    return f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/module-set-drafts"


def _sets_url(project_id, subproject_id) -> str:
    return f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/module-sets"


# --- create draft --------------------------------------------------------------


def test_create_draft_from_run(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id, leaf_count=3)

    response = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run.id)}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "OPEN"
    assert body["module_set_id"] is None
    assert body["base_run_record_id"] == str(run.id)
    assert body["origin_method"] == "AUTOMATED"
    assert len(body["members"]) == 3
    expected_module_ids = {str(m.id) for m in list_model_modules_for_run(db_session, run.id)}
    assert {m["model_module_id"] for m in body["members"]} == expected_module_ids
    # Honest disclosure: no invented "name" field anywhere on a member.
    assert "name" not in body["members"][0]


def test_create_draft_rejects_a_run_belonging_to_a_different_study(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    owning_subproject_id = make_subproject_id(db_session, project_id=project_id)
    other_subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=owning_subproject_id)

    response = client.post(
        _drafts_url(project_id, other_subproject_id), json={"run_record_id": str(run.id)}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_create_draft_rejects_a_run_with_no_model(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(
        db_session, subproject_id=subproject_id, include_model=False
    )

    response = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run.id)}
    )

    assert response.status_code == 422
    assert "associated Model" in response.json()["detail"]["message"]


def test_create_draft_for_unknown_project_returns_404(client: TestClient, db_session) -> None:
    subproject_id = make_subproject_id(db_session)
    response = client.post(
        _drafts_url(uuid.uuid4(), subproject_id), json={"run_record_id": str(uuid.uuid4())}
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


# --- inspect draft (hierarchy/boundaries) ---------------------------------------


def test_get_draft_ownership_mismatch_returns_404(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    owning_subproject_id = make_subproject_id(db_session, project_id=project_id)
    other_subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=owning_subproject_id)
    draft_id = client.post(
        _drafts_url(project_id, owning_subproject_id), json={"run_record_id": str(run.id)}
    ).json()["id"]

    response = client.get(f"{_drafts_url(project_id, other_subproject_id)}/{draft_id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_get_draft_member_boundary_ports_shows_structural_and_decided_fields(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id, leaf_count=1)
    (module,) = list_model_modules_for_run(db_session, run.id)
    persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "ACoA", "direction": "OUTPUT"}],
        session=db_session,
    )

    draft = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run.id)}
    ).json()
    member_id = draft["members"][0]["id"]

    response = client.get(
        f"{_drafts_url(project_id, subproject_id)}/{draft['id']}/members/{member_id}/boundary-ports"
    )

    assert response.status_code == 200
    (port,) = response.json()
    assert port["species_id"] == "ACoA"
    assert port["direction"] == "OUTPUT"
    assert port["treatment_type"] == "UNRESOLVED"
    assert port["resolution_status"] == "PENDING_REVIEW"
    assert port["decided_by"] is None


def test_get_draft_member_boundary_ports_404_for_unknown_member(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft_id = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run.id)}
    ).json()["id"]

    response = client.get(
        f"{_drafts_url(project_id, subproject_id)}/{draft_id}/members/{uuid.uuid4()}/boundary-ports"
    )

    assert response.status_code == 404


# --- discard ---------------------------------------------------------------------


def test_discard_draft(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft_id = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run.id)}
    ).json()["id"]

    response = client.post(f"{_drafts_url(project_id, subproject_id)}/{draft_id}/discard")

    assert response.status_code == 200
    assert response.json()["status"] == "DISCARDED"

    # Hidden from the default listing -- the decided rule.
    listing = client.get(_drafts_url(project_id, subproject_id)).json()
    assert draft_id not in [d["id"] for d in listing]


def test_discard_draft_twice_returns_409(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft_id = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run.id)}
    ).json()["id"]
    client.post(f"{_drafts_url(project_id, subproject_id)}/{draft_id}/discard")

    response = client.post(f"{_drafts_url(project_id, subproject_id)}/{draft_id}/discard")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CONFLICT"


# --- save: new_set / new_version / duplicate-save protection --------------------


def test_save_as_new_set_then_reopen(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id, leaf_count=2)
    draft = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run.id)}
    ).json()

    save_response = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft['id']}/save",
        json={"mode": "new_set", "set_name": "Expert partition", "saved_by": "Morgan Lee"},
    )

    assert save_response.status_code == 201
    saved = save_response.json()
    assert saved["version"] == 1
    assert saved["module_set_stable_identifier"] == "MS-001"
    assert saved["module_set_name"] == "Expert partition"
    assert saved["saved_by"] == "Morgan Lee"
    assert {m["model_module_id"] for m in saved["members"]} == {
        m["model_module_id"] for m in draft["members"]
    }

    # Reopen: read-only, identical content.
    reopen_response = client.get(
        f"{_sets_url(project_id, subproject_id)}/{saved['module_set_id']}/versions/1"
    )
    assert reopen_response.status_code == 200
    assert reopen_response.json() == saved

    # Appears in the study's own catalog.
    catalog = client.get(_sets_url(project_id, subproject_id)).json()
    assert len(catalog) == 1
    assert catalog[0]["stable_identifier"] == "MS-001"
    assert catalog[0]["latest_version"] == 1


def test_save_is_idempotent_a_second_save_returns_409_with_resulting_version(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft_id = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run.id)}
    ).json()["id"]
    first_save = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft_id}/save",
        json={"mode": "new_set", "set_name": "Once"},
    ).json()

    second_save = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft_id}/save",
        json={"mode": "new_set", "set_name": "Twice"},
    )

    assert second_save.status_code == 409
    body = second_save.json()
    assert body["detail"]["code"] == "CONFLICT"
    assert body["detail"]["context"]["resulting_version_id"] == first_save["id"]

    # No second module set was created.
    catalog = client.get(_sets_url(project_id, subproject_id)).json()
    assert len(catalog) == 1


def test_save_new_version_allocates_next_integer_and_preserves_the_first(
    client: TestClient, db_session
) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    model_id = make_model_id(db_session, subproject_id=subproject_id)
    run_1 = make_succeeded_hierarchical_run(
        db_session, subproject_id=subproject_id, model_id=model_id
    )
    draft_1_id = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run_1.id)}
    ).json()["id"]
    version_1 = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft_1_id}/save",
        json={"mode": "new_set", "set_name": "Set"},
    ).json()

    run_2 = make_succeeded_hierarchical_run(
        db_session, subproject_id=subproject_id, model_id=model_id
    )
    draft_2_id = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run_2.id)}
    ).json()["id"]
    version_2 = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft_2_id}/save",
        json={"mode": "new_version", "existing_set_id": version_1["module_set_id"]},
    ).json()

    assert version_2["version"] == 2
    assert version_2["base_version_id"] == version_1["id"]

    # v1 is still exactly reachable and unchanged.
    reread_v1 = client.get(
        f"{_sets_url(project_id, subproject_id)}/{version_1['module_set_id']}/versions/1"
    ).json()
    assert reread_v1 == version_1


def test_save_new_version_with_mismatched_model_returns_422(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run_1 = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft_1_id = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run_1.id)}
    ).json()["id"]
    version_1 = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft_1_id}/save",
        json={"mode": "new_set", "set_name": "Set"},
    ).json()

    run_2 = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft_2_id = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run_2.id)}
    ).json()["id"]

    response = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft_2_id}/save",
        json={"mode": "new_version", "existing_set_id": version_1["module_set_id"]},
    )

    assert response.status_code == 422
    assert "revalidation" in response.json()["detail"]["message"]


def test_save_as_new_set_requires_a_set_name(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft_id = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run.id)}
    ).json()["id"]

    response = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft_id}/save", json={"mode": "new_set"}
    )

    assert response.status_code == 422


# --- reopen ownership / unknown version -------------------------------------------


def test_reopen_version_ownership_mismatch_returns_404(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    owning_subproject_id = make_subproject_id(db_session, project_id=project_id)
    other_subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=owning_subproject_id)
    draft_id = client.post(
        _drafts_url(project_id, owning_subproject_id), json={"run_record_id": str(run.id)}
    ).json()["id"]
    version = client.post(
        f"{_drafts_url(project_id, owning_subproject_id)}/{draft_id}/save",
        json={"mode": "new_set", "set_name": "Set"},
    ).json()

    response = client.get(
        f"{_sets_url(project_id, other_subproject_id)}/{version['module_set_id']}/versions/1"
    )

    assert response.status_code == 404


def test_reopen_unknown_version_number_returns_404(client: TestClient, db_session) -> None:
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft_id = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run.id)}
    ).json()["id"]
    version = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft_id}/save",
        json={"mode": "new_set", "set_name": "Set"},
    ).json()

    response = client.get(
        f"{_sets_url(project_id, subproject_id)}/{version['module_set_id']}/versions/99"
    )

    assert response.status_code == 404
