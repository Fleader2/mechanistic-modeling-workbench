"""Tests for the Module-Set Manual Editing increment's own API surface: creating an editable
draft from a saved version, renaming/reassigning membership, live validation findings,
boundary-port invalidation, stale-edit conflict detection, and save-time enforcement.

See ``docs/23_module_set_manual_editing_increment.md``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.persistence.module_boundary_port import persist_candidate_boundary_ports
from tests.persistence.conftest import (
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


def _make_three_sibling_draft(client: TestClient, db_session):
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(
        db_session,
        subproject_id=subproject_id,
        leaf_count=3,
        reaction_ids_per_leaf=[["rA1", "rA2"], ["rB1", "rB2"], ["rC1", "rC2"]],
    )
    draft = client.post(
        _drafts_url(project_id, subproject_id), json={"run_record_id": str(run.id)}
    ).json()
    member_a = next(
        m for m in draft["members"] if sorted(m["reaction_component_ids"]) == ["rA1", "rA2"]
    )
    member_b = next(
        m for m in draft["members"] if sorted(m["reaction_component_ids"]) == ["rB1", "rB2"]
    )
    return project_id, subproject_id, draft, member_a, member_b


def _edit_url(project_id, subproject_id, draft_id, member_id) -> str:
    return f"{_drafts_url(project_id, subproject_id)}/{draft_id}/members/{member_id}"


# --- rename / membership editing -------------------------------------------------


def test_rename_a_member(client: TestClient, db_session) -> None:
    project_id, subproject_id, draft, member_a, _member_b = _make_three_sibling_draft(
        client, db_session
    )

    response = client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_a["id"]),
        json={"expected_edit_version": 0, "display_name": "Fatty acid synthesis"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["findings"] == []
    renamed = next(m for m in body["draft"]["members"] if m["id"] == member_a["id"])
    assert renamed["display_name"] == "Fatty acid synthesis"
    assert body["draft"]["edit_version"] == 1
    assert body["draft"]["origin_method"] == "MIXED_EDITED"


def test_rename_rejects_an_empty_name(client: TestClient, db_session) -> None:
    project_id, subproject_id, draft, member_a, _member_b = _make_three_sibling_draft(
        client, db_session
    )

    response = client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_a["id"]),
        json={"expected_edit_version": 0, "display_name": "   "},
    )

    assert response.status_code == 422


def test_moving_a_reaction_between_siblings_shows_up_on_both_members(
    client: TestClient, db_session
) -> None:
    project_id, subproject_id, draft, member_a, member_b = _make_three_sibling_draft(
        client, db_session
    )

    response = client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_b["id"]),
        json={"expected_edit_version": 0, "reaction_component_ids": ["rB1", "rB2", "rA1"]},
    )

    assert response.status_code == 200
    body = response.json()["draft"]
    updated_a = next(m for m in body["members"] if m["id"] == member_a["id"])
    updated_b = next(m for m in body["members"] if m["id"] == member_b["id"])
    assert sorted(updated_b["reaction_component_ids"]) == ["rA1", "rB1", "rB2"]
    assert sorted(updated_a["reaction_component_ids"]) == ["rA2"]
    assert updated_a["membership_edited"] is True
    assert updated_b["membership_edited"] is True


def test_rejects_an_unknown_reaction_id(client: TestClient, db_session) -> None:
    project_id, subproject_id, draft, member_a, _member_b = _make_three_sibling_draft(
        client, db_session
    )

    response = client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_a["id"]),
        json={"expected_edit_version": 0, "reaction_component_ids": ["made-up-reaction"]},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_stale_edit_version_returns_409_with_current_version(
    client: TestClient, db_session
) -> None:
    project_id, subproject_id, draft, member_a, _member_b = _make_three_sibling_draft(
        client, db_session
    )
    client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_a["id"]),
        json={"expected_edit_version": 0, "display_name": "First"},
    )

    response = client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_a["id"]),
        json={"expected_edit_version": 0, "display_name": "Conflicting"},
    )

    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["code"] == "CONFLICT"
    assert body["context"]["current_edit_version"] == 1


def test_editing_an_unknown_member_returns_404(client: TestClient, db_session) -> None:
    project_id, subproject_id, draft, _member_a, _member_b = _make_three_sibling_draft(
        client, db_session
    )

    response = client.patch(
        _edit_url(project_id, subproject_id, draft["id"], "00000000-0000-0000-0000-000000000000"),
        json={"expected_edit_version": 0, "display_name": "Nope"},
    )

    assert response.status_code == 404


# --- live validation findings ----------------------------------------------------


def test_validation_is_empty_for_an_unedited_draft(client: TestClient, db_session) -> None:
    project_id, subproject_id, draft, _member_a, _member_b = _make_three_sibling_draft(
        client, db_session
    )

    response = client.get(f"{_drafts_url(project_id, subproject_id)}/{draft['id']}/validation")

    assert response.status_code == 200
    assert response.json() == []


def test_validation_reports_an_unassigned_reaction(client: TestClient, db_session) -> None:
    project_id, subproject_id, draft, member_a, _member_b = _make_three_sibling_draft(
        client, db_session
    )
    client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_a["id"]),
        json={"expected_edit_version": 0, "reaction_component_ids": ["rA1"]},
    )

    response = client.get(f"{_drafts_url(project_id, subproject_id)}/{draft['id']}/validation")

    assert response.status_code == 200
    findings = response.json()
    assert len(findings) == 1
    assert findings[0]["code"] == "UNASSIGNED_REACTION"
    assert findings[0]["reaction_id"] == "rA2"


# --- boundary-port invalidation ---------------------------------------------------


def test_boundary_ports_are_invalidated_after_a_membership_edit(
    client: TestClient, db_session
) -> None:
    project_id, subproject_id, draft, member_a, member_b = _make_three_sibling_draft(
        client, db_session
    )
    persist_candidate_boundary_ports(
        model_module_id=member_a["model_module_id"],
        candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
        session=db_session,
    )
    db_session.commit()

    client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_b["id"]),
        json={"expected_edit_version": 0, "reaction_component_ids": ["rB1", "rB2", "rA1"]},
    )

    response = client.get(
        f"{_drafts_url(project_id, subproject_id)}/{draft['id']}/members/{member_a['id']}"
        "/boundary-ports"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CONFLICT"


def test_boundary_ports_still_available_for_an_untouched_member(
    client: TestClient, db_session
) -> None:
    project_id, subproject_id, draft, member_a, member_b = _make_three_sibling_draft(
        client, db_session
    )
    persist_candidate_boundary_ports(
        model_module_id=member_a["model_module_id"],
        candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
        session=db_session,
    )
    db_session.commit()

    client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_b["id"]),
        json={"expected_edit_version": 0, "reaction_component_ids": ["rB1", "rB2"]},
    )

    response = client.get(
        f"{_drafts_url(project_id, subproject_id)}/{draft['id']}/members/{member_a['id']}"
        "/boundary-ports"
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


# --- save with edits ---------------------------------------------------------------


def test_save_is_blocked_with_structured_findings_while_a_reaction_is_unassigned(
    client: TestClient, db_session
) -> None:
    project_id, subproject_id, draft, member_a, _member_b = _make_three_sibling_draft(
        client, db_session
    )
    client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_a["id"]),
        json={"expected_edit_version": 0, "reaction_component_ids": ["rA1"]},
    )

    response = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft['id']}/save",
        json={"mode": "new_set", "set_name": "Should not save"},
    )

    assert response.status_code == 422
    findings = response.json()["detail"]["context"]["findings"]
    assert findings[0]["code"] == "UNASSIGNED_REACTION"


def test_save_after_edits_persists_name_and_membership_and_marks_mixed_edited(
    client: TestClient, db_session
) -> None:
    project_id, subproject_id, draft, member_a, member_b = _make_three_sibling_draft(
        client, db_session
    )
    client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_a["id"]),
        json={"expected_edit_version": 0, "display_name": "Renamed A"},
    )
    client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_b["id"]),
        json={"expected_edit_version": 1, "reaction_component_ids": ["rB1", "rB2", "rA1"]},
    )
    client.patch(
        _edit_url(project_id, subproject_id, draft["id"], member_a["id"]),
        json={"expected_edit_version": 2, "reaction_component_ids": ["rA2"]},
    )

    response = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft['id']}/save",
        json={"mode": "new_set", "set_name": "Edited partition"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["origin_method"] == "MIXED_EDITED"
    saved_a = next(
        m for m in body["members"] if m["id"] != member_b["id"] and m["display_name"] == "Renamed A"
    )
    assert saved_a["reaction_component_ids"] == ["rA2"]
    saved_b = next(
        m for m in body["members"] if sorted(m["reaction_component_ids"]) == ["rA1", "rB1", "rB2"]
    )
    assert saved_b["membership_edited"] is True


# --- edit draft created from a saved version ---------------------------------------


def test_create_edit_draft_from_a_saved_version_then_resave_as_new_version(
    client: TestClient, db_session
) -> None:
    project_id, subproject_id, draft, member_a, _member_b = _make_three_sibling_draft(
        client, db_session
    )
    save_response = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft['id']}/save",
        json={"mode": "new_set", "set_name": "Original partition"},
    )
    module_set_id = save_response.json()["module_set_id"]

    edit_draft_response = client.post(
        f"{_sets_url(project_id, subproject_id)}/{module_set_id}/versions/1/edit"
    )
    assert edit_draft_response.status_code == 201
    edit_draft = edit_draft_response.json()
    assert edit_draft["base_version_id"] == save_response.json()["id"]
    assert edit_draft["status"] == "OPEN"

    new_member_a = next(
        m for m in edit_draft["members"] if m["model_module_id"] == member_a["model_module_id"]
    )
    client.patch(
        _edit_url(project_id, subproject_id, edit_draft["id"], new_member_a["id"]),
        json={"expected_edit_version": 0, "display_name": "Second round rename"},
    )

    save_v2 = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{edit_draft['id']}/save",
        json={"mode": "new_version", "existing_set_id": module_set_id},
    )
    assert save_v2.status_code == 201
    assert save_v2.json()["version"] == 2
    renamed = next(
        m for m in save_v2.json()["members"] if m["model_module_id"] == member_a["model_module_id"]
    )
    assert renamed["display_name"] == "Second round rename"

    # v1 must still be exactly as originally saved.
    v1_reread = client.get(f"{_sets_url(project_id, subproject_id)}/{module_set_id}/versions/1")
    original_a = next(
        m
        for m in v1_reread.json()["members"]
        if m["model_module_id"] == member_a["model_module_id"]
    )
    assert original_a["display_name"] is None


def test_edit_draft_from_version_ownership_mismatch_returns_404(
    client: TestClient, db_session
) -> None:
    project_id, subproject_id, draft, _member_a, _member_b = _make_three_sibling_draft(
        client, db_session
    )
    save_response = client.post(
        f"{_drafts_url(project_id, subproject_id)}/{draft['id']}/save",
        json={"mode": "new_set", "set_name": "Owned by study A"},
    )
    module_set_id = save_response.json()["module_set_id"]

    other_subproject_id = make_subproject_id(db_session, project_id=project_id)
    response = client.post(
        f"{_sets_url(project_id, other_subproject_id)}/{module_set_id}/versions/1/edit"
    )

    assert response.status_code == 404
