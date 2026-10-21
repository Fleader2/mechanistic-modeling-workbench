"""Independent-session/independent-request durability tests for the Module-Set Edited-Module
Materialization increment's own API surface (boundary review, decisions, and simulation
submission) -- the same rationale and machinery as `tests/api/test_module_set_durability.py`:
every assertion here queries through a brand-new `Session`/connection opened *after* the
triggering request has fully returned, so an uncommitted write (the exact bug class increment
21 shipped once) cannot hide behind a shared test transaction.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.contracts.module_boundary_derivation import ModuleBoundaryDerivationResult
from app.models.enums import ModelSourceType, ProjectType, RunStage, RunStatus, SubprojectTaskType
from app.orchestration import module_set_execution_orchestrator
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model import persist_model
from app.persistence.model_module import materialize_accepted_modules
from app.persistence.project import persist_project
from app.persistence.run_record import complete_run, create_run_record, start_run
from app.persistence.subproject import persist_subproject
from tests.api.test_module_set_durability import real_client, real_session_app  # noqa: F401
from tests.conftest import reset_test_database


@pytest.fixture(autouse=True)
def _clean_database_before_and_after(
    alembic_config: Config, migrated_engine: Engine
) -> Iterator[None]:
    del migrated_engine
    reset_test_database(alembic_config)
    yield
    reset_test_database(alembic_config)


def _seed_saved_member(migrated_engine: Engine) -> tuple[str, str, str, str]:
    """One project/subproject/model/SUCCEEDED-hierarchical-run with a single module, saved as a
    new module-set version through real, independently-committing sessions -- with a recorded
    stage-1 input (`resolve_stage1_inputs`, which every module-set-execution orchestrator
    function relies on, and which the shared `_seed_run_with_modules` helper never sets).
    Returns (project_id, subproject_id, module_set_id, member_id)."""
    session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    try:
        project_id = persist_project(
            stable_identifier="PRJ-EXEC-DURABILITY",
            title="Execution durability test project",
            project_type=ProjectType.MICROBIAL_METABOLISM,
            session=session,
        ).entity_id
        subproject_id = persist_subproject(
            project_id=project_id,
            title="Execution durability test study",
            objective="Prove review/simulation writes survive independent requests.",
            task_type=SubprojectTaskType.BUILD_MODEL,
            session=session,
        ).entity_id
        model_id = persist_model(
            subproject_id=subproject_id,
            stable_identifier="MOD-EXEC-DURABILITY",
            name="Execution durability test model",
            source_type=ModelSourceType.GENERATED,
            version_label="v1",
            session=session,
        ).entity_id

        run = create_run_record(
            subproject_id=subproject_id, stage=RunStage.HARNESS, session=session, model_id=model_id
        )
        start_run(run_record_id=run.id, session=session)
        nodes = [
            {
                "node_id": f"node::depth0::root::{run.id}",
                "depth": 0,
                "parent_modularization_id": None,
                "parent_module_id": None,
                "child_submodel_id": f"m1-{run.id}",
                "child_modularization_id": f"cand-root-{run.id}",
                "child_module_ids": ["module_one"],
                "accepted": True,
                "reason": "accepted",
                "baseline_score": None,
                "child_score": "0.5",
                "branch_stopping_reason": None,
                "recursive_search_stopping_reason": "MAX_ROUNDS",
                "recursive_search_rounds": 1,
                "recursive_search_policy_version": "durability-test-v1",
                "attach_payload": None,
            },
            {
                "node_id": f"node::depth1::module_one::000000::{run.id}",
                "depth": 1,
                "parent_modularization_id": f"cand-root-{run.id}",
                "parent_module_id": "module_one",
                "child_submodel_id": f"m1-{run.id}::submodel::module_one",
                "child_modularization_id": None,
                "child_module_ids": [],
                "accepted": False,
                "reason": "recursive search never retained a genuine candidate",
                "baseline_score": "0.3",
                "child_score": None,
                "branch_stopping_reason": "NO_VALID_CHILD_DECOMPOSITION",
                "recursive_search_stopping_reason": "SEARCH_EXHAUSTED",
                "recursive_search_rounds": 1,
                "recursive_search_policy_version": "durability-test-v1",
                "attach_payload": {
                    "modularization_id": f"cand-root-{run.id}",
                    "module_ids": ["module_one"],
                    "memberships": [
                        {
                            "module_id": "module_one",
                            "component_type": "REACTION",
                            "component_id": "r1",
                        }
                    ],
                },
            },
        ]
        create_hierarchy_nodes(run_record_id=run.id, nodes=nodes, session=session)
        materialize_accepted_modules(run_record_id=run.id, session=session)
        complete_run(
            run_record_id=run.id,
            status=RunStatus.SUCCEEDED,
            session=session,
            artifact_reference=json.dumps(
                {"stage1_synthetic_source": "/tmp/fake_agent1_view.json"}
            ),
        )
        session.commit()
        run_id = str(run.id)
    finally:
        session.close()

    return str(project_id), str(subproject_id), run_id, "module_one"


def _query_scalar(migrated_engine: Engine, sql: str, **params: object) -> object:
    session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    try:
        return session.execute(text(sql), params).scalar()
    finally:
        session.close()


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


def _save_new_set(real_client, project_id: str, subproject_id: str, run_id: str) -> dict:  # noqa: F811
    draft = real_client.post(
        f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts",
        json={"run_record_id": run_id},
    ).json()
    return real_client.post(
        f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts/"
        f"{draft['id']}/save",
        json={"mode": "new_set", "set_name": "Execution durability set"},
    ).json()


class TestBoundaryReviewDurability:
    def test_a_derived_candidate_and_a_decision_are_visible_from_a_second_independent_session(
        self, migrated_engine: Engine, real_client, monkeypatch  # noqa: F811
    ) -> None:
        project_id, subproject_id, run_id, _module_id = _seed_saved_member(migrated_engine)
        saved = _save_new_set(real_client, project_id, subproject_id, run_id)
        member_id = saved["members"][0]["id"]
        member_base = (
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-sets/"
            f"{saved['module_set_id']}/versions/1/members/{member_id}"
        )

        monkeypatch.setattr(
            module_set_execution_orchestrator,
            "invoke_module_boundary_derivation",
            _fake_boundary_derivation_success([{"species_id": "AcCoA", "direction": "OUTPUT"}]),
        )
        derive_response = real_client.post(f"{member_base}/boundary-review/derive")
        assert derive_response.status_code == 200
        port_id = derive_response.json()["ports"][0]["id"]

        port_species = _query_scalar(
            migrated_engine,
            "SELECT species_id FROM module_set_member_boundary_port WHERE id = :id",
            id=port_id,
        )
        assert port_species == "AcCoA"

        decision_response = real_client.post(
            f"{member_base}/boundary-review/ports/{port_id}/decision",
            json={
                "expected_review_version": 0,
                "treatment_type": "EXTERNALLY_CONTROLLED",
                "initial_value": "1.0",
                "unit": "mM",
            },
        )
        assert decision_response.status_code == 200

        resolution_status = _query_scalar(
            migrated_engine,
            "SELECT resolution_status FROM module_set_member_boundary_port WHERE id = :id",
            id=port_id,
        )
        review_version = _query_scalar(
            migrated_engine,
            "SELECT review_version FROM module_set_member_review WHERE module_set_member_id = :id",
            id=member_id,
        )
        assert resolution_status == "RESOLVED"
        assert review_version == 1


class TestSimulationSubmissionDurability:
    def test_a_submitted_simulation_and_its_pinned_snapshot_are_durable(
        self, migrated_engine: Engine, real_client, monkeypatch  # noqa: F811
    ) -> None:
        project_id, subproject_id, run_id, _module_id = _seed_saved_member(migrated_engine)
        saved = _save_new_set(real_client, project_id, subproject_id, run_id)
        member_id = saved["members"][0]["id"]
        member_base = (
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-sets/"
            f"{saved['module_set_id']}/versions/1/members/{member_id}"
        )

        monkeypatch.setattr(
            module_set_execution_orchestrator,
            "invoke_module_boundary_derivation",
            _fake_boundary_derivation_success([{"species_id": "AcCoA", "direction": "OUTPUT"}]),
        )
        review = real_client.post(f"{member_base}/boundary-review/derive").json()
        port_id = review["ports"][0]["id"]
        real_client.post(
            f"{member_base}/boundary-review/ports/{port_id}/decision",
            json={
                "expected_review_version": 0,
                "treatment_type": "EXTERNALLY_CONTROLLED",
                "initial_value": "1.0",
                "unit": "mM",
            },
        )

        submit_response = real_client.post(
            f"{member_base}/simulations",
            json={"expected_review_version": 1, "saved_by": "Durability tester"},
        )
        assert submit_response.status_code == 201
        run_record_id = submit_response.json()["id"]

        status_value = _query_scalar(
            migrated_engine, "SELECT status FROM run_record WHERE id = :id", id=run_record_id
        )
        module_set_member_id = _query_scalar(
            migrated_engine,
            "SELECT module_set_member_id FROM run_record WHERE id = :id",
            id=run_record_id,
        )
        assert status_value == "PENDING"
        assert str(module_set_member_id) == member_id

        snapshot_count = _query_scalar(
            migrated_engine,
            "SELECT COUNT(*) FROM module_execution_snapshot WHERE run_record_id = :id",
            id=run_record_id,
        )
        assert snapshot_count == 1

        # A second, independent request reopening it must also see the same PENDING run.
        reopened = real_client.get(f"{member_base}/simulations/{run_record_id}")
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "PENDING"


class TestCorsPreflight:
    def test_boundary_review_derive_post_preflight_succeeds(
        self, migrated_engine: Engine, real_client  # noqa: F811
    ) -> None:
        project_id, subproject_id, run_id, _module_id = _seed_saved_member(migrated_engine)
        saved = _save_new_set(real_client, project_id, subproject_id, run_id)
        member_id = saved["members"][0]["id"]
        member_base = (
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-sets/"
            f"{saved['module_set_id']}/versions/1/members/{member_id}"
        )

        response = real_client.options(
            f"{member_base}/boundary-review/derive",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code != 400, response.text
        assert "POST" in response.headers.get("access-control-allow-methods", "")

    def test_simulations_post_preflight_succeeds(
        self, migrated_engine: Engine, real_client  # noqa: F811
    ) -> None:
        project_id, subproject_id, run_id, _module_id = _seed_saved_member(migrated_engine)
        saved = _save_new_set(real_client, project_id, subproject_id, run_id)
        member_id = saved["members"][0]["id"]
        member_base = (
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-sets/"
            f"{saved['module_set_id']}/versions/1/members/{member_id}"
        )

        response = real_client.options(
            f"{member_base}/simulations",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code != 400, response.text
        assert "POST" in response.headers.get("access-control-allow-methods", "")


class TestWorkerCrashRecoveryIsDisclosedNotAutomatic:
    """Proves the documented limitation directly: a run claimed (`PENDING` -> `RUNNING`) by
    `claim_next_pending_module_set_run` is durably visible as `RUNNING` to a second, independent
    session even if no worker ever finishes it -- exactly what a crashed/killed worker process
    leaves behind, with no automatic recovery."""

    def test_a_claimed_but_never_completed_run_stays_running_for_other_sessions(
        self, migrated_engine: Engine, real_client, monkeypatch  # noqa: F811
    ) -> None:
        from app.persistence.module_set_execution import claim_next_pending_module_set_run

        project_id, subproject_id, run_id, _module_id = _seed_saved_member(migrated_engine)
        saved = _save_new_set(real_client, project_id, subproject_id, run_id)
        member_id = saved["members"][0]["id"]
        member_base = (
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-sets/"
            f"{saved['module_set_id']}/versions/1/members/{member_id}"
        )

        monkeypatch.setattr(
            module_set_execution_orchestrator,
            "invoke_module_boundary_derivation",
            _fake_boundary_derivation_success([{"species_id": "AcCoA", "direction": "OUTPUT"}]),
        )
        real_client.post(f"{member_base}/boundary-review/derive")
        port_id = _query_scalar(
            migrated_engine,
            "SELECT id FROM module_set_member_boundary_port WHERE species_id = 'AcCoA'",
        )
        real_client.post(
            f"{member_base}/boundary-review/ports/{port_id}/decision",
            json={
                "expected_review_version": 0,
                "treatment_type": "EXTERNALLY_CONTROLLED",
                "initial_value": "1.0",
                "unit": "mM",
            },
        )
        submitted = real_client.post(
            f"{member_base}/simulations", json={"expected_review_version": 1}
        ).json()

        claim_session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
        try:
            claimed = claim_next_pending_module_set_run(claim_session)
            assert claimed is not None
            assert str(claimed.id) == submitted["id"]
        finally:
            claim_session.close()
        # No worker ever processes it -- simulating a crash right after the claim.

        status_value = _query_scalar(
            migrated_engine, "SELECT status FROM run_record WHERE id = :id", id=submitted["id"]
        )
        assert status_value == "RUNNING"
