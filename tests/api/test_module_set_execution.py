"""Tests for the Module-Set Edited-Module Materialization increment, Phase B's own API
surface: boundary review/derivation, decision submission, readiness, and simulation
submission/lifecycle. Harness calls are mocked via ``monkeypatch`` at the orchestrator's own
import location, mirroring every other API test file's established convention; real,
end-to-end harness behavior is proven separately (Harness repo tests + this increment's own
live browser verification with a real Agent 2/Agent 3 round trip).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config.settings import API_V1_PREFIX
from app.contracts.module_boundary_derivation import ModuleBoundaryDerivationResult
from app.orchestration import module_set_execution_orchestrator
from tests.persistence.conftest import (
    make_project_id,
    make_subproject_id,
    make_succeeded_hierarchical_run,
)

pytestmark = pytest.mark.api

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


def _fake_boundary_derivation_success(candidates):
    def _fake(request):
        return (
            ModuleBoundaryDerivationResult(
                contract_version=request.contract_version,
                run_id=request.run_id,
                status="SUCCEEDED",
                module_id=request.module_id,
                candidates=tuple(candidates),
                started_at="t0",
                completed_at="t1",
                error=None,
                summary="ok",
            ),
            None,
        )

    return _fake


def _saved_member_urls(client: TestClient, db_session, *, reaction_ids_per_leaf=None):
    """Create a project/study, a SUCCEEDED hierarchical run, draft it, and save it as a new
    module set -- returns every id/URL a test needs to reach the one saved member."""
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(
        db_session,
        subproject_id=subproject_id,
        leaf_count=1,
        reaction_ids_per_leaf=reaction_ids_per_leaf or [["rA1", "rA2"]],
    )
    # Needed by `resolve_stage1_inputs`, which every module-set-execution orchestrator function
    # relies on -- `make_succeeded_hierarchical_run` never records one itself.
    run.artifact_reference = json.dumps({"stage1_synthetic_source": "/tmp/fake_agent1_view.json"})
    db_session.flush()

    base = f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}"
    draft = client.post(f"{base}/module-set-drafts", json={"run_record_id": str(run.id)}).json()
    saved = client.post(
        f"{base}/module-set-drafts/{draft['id']}/save",
        json={"mode": "new_set", "set_name": "Set"},
    ).json()
    member_id = saved["members"][0]["id"]
    member_base = f"{base}/module-sets/{saved['module_set_id']}/versions/1/members/{member_id}"
    return {
        "project_id": project_id,
        "subproject_id": subproject_id,
        "module_set_id": saved["module_set_id"],
        "member_id": member_id,
        "base": base,
        "member_base": member_base,
    }


def _resolve_member_to_ready(
    client: TestClient, monkeypatch, urls: dict, *, species_id="AcCoA"
) -> int:
    monkeypatch.setattr(
        module_set_execution_orchestrator,
        "invoke_module_boundary_derivation",
        _fake_boundary_derivation_success([{"species_id": species_id, "direction": "OUTPUT"}]),
    )
    review = client.post(f"{urls['member_base']}/boundary-review/derive").json()
    port_id = review["ports"][0]["id"]
    decided = client.post(
        f"{urls['member_base']}/boundary-review/ports/{port_id}/decision",
        json={
            "expected_review_version": review["review_version"],
            "treatment_type": "EXTERNALLY_CONTROLLED",
            "initial_value": "1.0",
            "unit": "mM",
        },
    ).json()
    return decided["review_version"]


# --- boundary review: derive / inspect / decide ---------------------------------------------


def test_derive_boundary_review_persists_candidates(
    client: TestClient, db_session, monkeypatch
) -> None:
    urls = _saved_member_urls(client, db_session)
    monkeypatch.setattr(
        module_set_execution_orchestrator,
        "invoke_module_boundary_derivation",
        _fake_boundary_derivation_success([{"species_id": "AcCoA", "direction": "OUTPUT"}]),
    )

    response = client.post(f"{urls['member_base']}/boundary-review/derive")

    assert response.status_code == 200
    body = response.json()
    assert len(body["ports"]) == 1
    assert body["ports"][0]["species_id"] == "AcCoA"
    assert body["ready"] is False
    assert body["findings"][0]["code"] == "UNRESOLVED_BOUNDARY_PORT"


def test_boundary_review_derivation_404s_for_an_unknown_member(
    client: TestClient, db_session
) -> None:
    urls = _saved_member_urls(client, db_session)
    bogus = urls["member_base"].rsplit("/", 1)[0] + "/00000000-0000-0000-0000-000000000000"
    response = client.post(f"{bogus}/boundary-review/derive")
    assert response.status_code == 404


def test_get_boundary_review_before_any_derivation_shows_no_ports_finding(
    client: TestClient, db_session
) -> None:
    urls = _saved_member_urls(client, db_session)
    response = client.get(f"{urls['member_base']}/boundary-review")
    assert response.status_code == 200
    body = response.json()
    assert body["ports"] == []
    assert body["findings"][0]["code"] == "NO_BOUNDARY_PORTS_DERIVED"
    assert body["ready"] is False


def test_submitting_a_decision_resolves_the_port_and_becomes_ready(
    client: TestClient, db_session, monkeypatch
) -> None:
    urls = _saved_member_urls(client, db_session)
    review_version = _resolve_member_to_ready(client, monkeypatch, urls)
    assert review_version == 1

    final = client.get(f"{urls['member_base']}/boundary-review").json()
    assert final["ready"] is True
    assert final["ports"][0]["treatment_type"] == "EXTERNALLY_CONTROLLED"


def test_a_stale_review_version_decision_returns_409(
    client: TestClient, db_session, monkeypatch
) -> None:
    urls = _saved_member_urls(client, db_session)
    monkeypatch.setattr(
        module_set_execution_orchestrator,
        "invoke_module_boundary_derivation",
        _fake_boundary_derivation_success([{"species_id": "AcCoA", "direction": "OUTPUT"}]),
    )
    review = client.post(f"{urls['member_base']}/boundary-review/derive").json()
    port_id = review["ports"][0]["id"]
    client.post(
        f"{urls['member_base']}/boundary-review/ports/{port_id}/decision",
        json={
            "expected_review_version": 0,
            "treatment_type": "EXTERNALLY_CONTROLLED",
            "initial_value": "1.0",
            "unit": "mM",
        },
    )

    response = client.post(
        f"{urls['member_base']}/boundary-review/ports/{port_id}/decision",
        json={"expected_review_version": 0, "treatment_type": "PRESCRIBED_INPUT"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["context"]["current_review_version"] == 1


# --- simulation submission/lifecycle ----------------------------------------------------------


def test_submitting_a_simulation_when_not_ready_returns_422_with_findings(
    client: TestClient, db_session
) -> None:
    urls = _saved_member_urls(client, db_session)
    response = client.post(
        f"{urls['member_base']}/simulations",
        json={"expected_review_version": 0},
    )
    assert response.status_code == 422
    assert (
        response.json()["detail"]["context"]["findings"][0]["code"] == "NO_BOUNDARY_PORTS_DERIVED"
    )


def test_submitting_a_ready_simulation_returns_a_pending_run(
    client: TestClient, db_session, monkeypatch
) -> None:
    urls = _saved_member_urls(client, db_session)
    review_version = _resolve_member_to_ready(client, monkeypatch, urls)

    response = client.post(
        f"{urls['member_base']}/simulations",
        json={"expected_review_version": review_version, "saved_by": "Morgan Lee"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["agent3_report"] is None


def test_a_second_submission_while_one_is_active_returns_409(
    client: TestClient, db_session, monkeypatch
) -> None:
    urls = _saved_member_urls(client, db_session)
    review_version = _resolve_member_to_ready(client, monkeypatch, urls)
    first = client.post(
        f"{urls['member_base']}/simulations", json={"expected_review_version": review_version}
    ).json()

    response = client.post(
        f"{urls['member_base']}/simulations", json={"expected_review_version": review_version}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["context"]["existing_run_id"] == first["id"]


def test_listing_and_reopening_simulations(client: TestClient, db_session, monkeypatch) -> None:
    urls = _saved_member_urls(client, db_session)
    review_version = _resolve_member_to_ready(client, monkeypatch, urls)
    submitted = client.post(
        f"{urls['member_base']}/simulations", json={"expected_review_version": review_version}
    ).json()

    listing = client.get(f"{urls['member_base']}/simulations").json()
    assert [r["id"] for r in listing] == [submitted["id"]]

    reopened = client.get(f"{urls['member_base']}/simulations/{submitted['id']}")
    assert reopened.status_code == 200
    assert reopened.json()["id"] == submitted["id"]


def test_reopening_an_unknown_run_404s(client: TestClient, db_session) -> None:
    urls = _saved_member_urls(client, db_session)
    response = client.get(f"{urls['member_base']}/simulations/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# --- ownership isolation ----------------------------------------------------------------------


def test_a_member_from_a_different_study_is_not_reachable(client: TestClient, db_session) -> None:
    urls = _saved_member_urls(client, db_session)
    other_project_id = make_project_id(db_session)
    other_subproject_id = make_subproject_id(db_session, project_id=other_project_id)

    response = client.get(
        f"{PROJECTS_URL}/{other_project_id}/subprojects/{other_subproject_id}/module-sets/"
        f"{urls['module_set_id']}/versions/1/members/{urls['member_id']}/boundary-review"
    )
    assert response.status_code == 404


def test_a_draft_member_has_no_execution_route_at_all(client: TestClient, db_session) -> None:
    """Drafts live under a completely different URL namespace
    (``.../module-set-drafts/{id}/...``) -- there is no route under it for boundary review or
    simulation at all, so draft execution is rejected by routing, not by a runtime check."""
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    run = make_succeeded_hierarchical_run(
        db_session, subproject_id=subproject_id, leaf_count=1, reaction_ids_per_leaf=[["rA1"]]
    )
    base = f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}"
    draft = client.post(f"{base}/module-set-drafts", json={"run_record_id": str(run.id)}).json()
    draft_member_id = draft["members"][0]["id"]

    response = client.post(
        f"{base}/module-set-drafts/{draft['id']}/members/{draft_member_id}/boundary-review/derive"
    )
    assert response.status_code == 404


# --- historical preservation --------------------------------------------------------------------


def test_submitting_a_simulation_for_one_member_never_touches_another_versions_data(
    client: TestClient, db_session, monkeypatch
) -> None:
    urls = _saved_member_urls(client, db_session)
    review_version = _resolve_member_to_ready(client, monkeypatch, urls)
    client.post(
        f"{urls['member_base']}/simulations", json={"expected_review_version": review_version}
    )

    # Reopening the saved version itself (increment 21's own route) must be completely
    # unaffected -- no execution/review state leaks into the saved version's own shape.
    version = client.get(f"{urls['base']}/module-sets/{urls['module_set_id']}/versions/1")
    assert version.status_code == 200
    assert len(version.json()["members"]) == 1
