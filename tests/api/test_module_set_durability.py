"""Independent-session/independent-request durability tests for the module-set mutating
routes. See `docs/22_database_configuration_and_verification_safety.md` -- these are the
tests that would have caught `docs/21`'s two live-verification-only bugs (a missing
`session.commit()` in every mutating route, and CORS's `allow_methods=["GET"]` blocking every
POST), neither of which the ordinary API test suite could catch, because its `client`/
`db_session` fixtures share one SQLAlchemy session between a test's own request and its own
assertions -- an uncommitted write is still visible to a read sharing that same transaction,
which is exactly the condition that does not hold between two independent real HTTP requests.

Unlike every other API test file, these tests bypass that shared-session machinery on purpose:
each request here gets its own freshly-opened `Session`, exactly like a real `uvicorn` process
would hand out, and verification queries run through a *second*, independently-opened session.
Because this performs real, out-of-band commits against the shared test database (rather than
relying on the per-test `SAVEPOINT` rollback every other test file uses), this file's own
fixture replays the full migration history before and after -- the same mechanism
`tests/conftest.py::reset_test_database` already uses for session startup, and the same
rationale: see `agent1-biochemical-curator/docs/29_test_database_isolation.md`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models.enums import ModelSourceType, ProjectType, RunStage, RunStatus, SubprojectTaskType
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model import persist_model
from app.persistence.model_module import materialize_accepted_modules
from app.persistence.project import persist_project
from app.persistence.run_record import complete_run, create_run_record, start_run
from app.persistence.subproject import persist_subproject
from tests.conftest import reset_test_database


@pytest.fixture(autouse=True)
def _clean_database_before_and_after(
    alembic_config: Config, migrated_engine: Engine
) -> Iterator[None]:
    """This file performs real, out-of-band commits -- restore a clean baseline both before and
    after every test, rather than hand-building cross-table deletion logic in exact FK order,
    which would be easy to get wrong and would leave the shared test database dirty for other
    test files on a mistake."""
    del migrated_engine
    reset_test_database(alembic_config)
    yield
    reset_test_database(alembic_config)


@pytest.fixture
def real_session_app(migrated_engine: Engine) -> Iterator[FastAPI]:
    """A FastAPI app whose `get_session` dependency hands out a freshly-opened, independently
    -committing `Session` per call -- exactly how production's own `get_session()` behaves,
    unlike every other test file's shared, rolled-back `db_session`."""
    from app.main import create_app

    def _override_get_session() -> Iterator[Session]:
        session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
        try:
            yield session
        finally:
            session.close()

    application = create_app()
    application.dependency_overrides[get_session] = _override_get_session
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def real_client(real_session_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(real_session_app) as test_client:
        yield test_client


def _seed_run_with_modules(
    migrated_engine: Engine, *, reaction_ids_per_module: list[list[str]] | None = None
) -> tuple[str, str, str]:
    """Creates one project/subproject/model/SUCCEEDED-hierarchical-run-with-2-modules through
    a real, independently-committing session -- a smaller, standalone version of
    `tests/persistence/conftest.py::make_succeeded_hierarchical_run`, which cannot be reused
    directly here because it depends on the shared, rolled-back `db_session` fixture.

    `reaction_ids_per_module` (default: each module gets the single literal id `"r1"`, exactly
    the original durability tests' own fixture shape) lets the Manual-Editing increment's own
    durability tests give each of the two sibling modules distinct, real reaction ids, needed
    to exercise a genuine cross-module reassignment.

    Returns (subproject_id, run_record_id) as strings, plus the session is closed before
    returning so the caller's own requests get fully independent sessions.
    """
    session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    try:
        project_id = persist_project(
            stable_identifier="PRJ-DURABILITY",
            title="Durability test project",
            project_type=ProjectType.MICROBIAL_METABOLISM,
            session=session,
        ).entity_id
        subproject_id = persist_subproject(
            project_id=project_id,
            title="Durability test study",
            objective="Prove writes survive independent requests.",
            task_type=SubprojectTaskType.BUILD_MODEL,
            session=session,
        ).entity_id
        model_id = persist_model(
            subproject_id=subproject_id,
            stable_identifier="MOD-DURABILITY",
            name="Durability test model",
            source_type=ModelSourceType.GENERATED,
            version_label="v1",
            session=session,
        ).entity_id

        run = create_run_record(
            subproject_id=subproject_id, stage=RunStage.HARNESS, session=session, model_id=model_id
        )
        start_run(run_record_id=run.id, session=session)
        names = ["module_one", "module_two"]
        nodes = [
            {
                "node_id": f"node::depth0::root::{run.id}",
                "depth": 0,
                "parent_modularization_id": None,
                "parent_module_id": None,
                "child_submodel_id": f"m1-{run.id}",
                "child_modularization_id": f"cand-root-{run.id}",
                "child_module_ids": names,
                "accepted": True,
                "reason": "accepted",
                "baseline_score": None,
                "child_score": "0.5",
                "branch_stopping_reason": None,
                "recursive_search_stopping_reason": "MAX_ROUNDS",
                "recursive_search_rounds": 1,
                "recursive_search_policy_version": "durability-test-v1",
                "attach_payload": None,
            }
        ]
        for i, name in enumerate(names):
            reaction_ids = (
                reaction_ids_per_module[i] if reaction_ids_per_module is not None else ["r1"]
            )
            nodes.append(
                {
                    "node_id": f"node::depth1::{name}::{i:06d}::{run.id}",
                    "depth": 1,
                    "parent_modularization_id": f"cand-root-{run.id}",
                    "parent_module_id": name,
                    "child_submodel_id": f"m1-{run.id}::submodel::{name}",
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
                        "module_ids": [name],
                        "memberships": [
                            {"module_id": name, "component_type": "REACTION", "component_id": rid}
                            for rid in reaction_ids
                        ],
                    },
                }
            )
        create_hierarchy_nodes(run_record_id=run.id, nodes=nodes, session=session)
        materialize_accepted_modules(run_record_id=run.id, session=session)
        complete_run(run_record_id=run.id, status=RunStatus.SUCCEEDED, session=session)
        session.commit()
        return str(project_id), str(subproject_id), str(run.id)
    finally:
        session.close()


def _query_scalar(migrated_engine: Engine, sql: str, **params: object) -> object:
    """Runs one query through a brand-new session/connection, proving visibility does not
    depend on reusing any session a prior step happened to use."""
    session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    try:
        return session.execute(text(sql), params).scalar()
    finally:
        session.close()


class TestCreateDraftDurability:
    def test_a_created_draft_is_visible_from_a_second_independent_session(
        self, migrated_engine: Engine, real_client: TestClient
    ) -> None:
        project_id, subproject_id, run_id = _seed_run_with_modules(migrated_engine)

        response = real_client.post(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts",
            json={"run_record_id": run_id},
        )
        assert response.status_code == 201
        draft_id = response.json()["id"]

        # A fresh session/connection, opened after the request has fully returned -- exactly
        # what a second, independent HTTP request's own session would see.
        count = _query_scalar(
            migrated_engine,
            "SELECT COUNT(*) FROM module_set_draft WHERE id = :draft_id",
            draft_id=draft_id,
        )
        assert count == 1

        member_count = _query_scalar(
            migrated_engine,
            "SELECT COUNT(*) FROM module_set_draft_member WHERE draft_id = :draft_id",
            draft_id=draft_id,
        )
        assert member_count == 2


class TestDiscardDurability:
    def test_a_discarded_draft_is_durable_from_a_second_independent_session(
        self, migrated_engine: Engine, real_client: TestClient
    ) -> None:
        project_id, subproject_id, run_id = _seed_run_with_modules(migrated_engine)
        draft_id = real_client.post(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts",
            json={"run_record_id": run_id},
        ).json()["id"]

        response = real_client.post(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts/{draft_id}/discard"
        )
        assert response.status_code == 200

        status_value = _query_scalar(
            migrated_engine,
            "SELECT status FROM module_set_draft WHERE id = :draft_id",
            draft_id=draft_id,
        )
        assert status_value == "DISCARDED"


class TestSaveDurability:
    def test_a_saved_version_is_durable_from_a_second_independent_session(
        self, migrated_engine: Engine, real_client: TestClient
    ) -> None:
        project_id, subproject_id, run_id = _seed_run_with_modules(migrated_engine)
        draft_id = real_client.post(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts",
            json={"run_record_id": run_id},
        ).json()["id"]

        response = real_client.post(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts/{draft_id}/save",
            json={"mode": "new_set", "set_name": "Durability test set"},
        )
        assert response.status_code == 201
        version_id = response.json()["id"]

        version_count = _query_scalar(
            migrated_engine,
            "SELECT COUNT(*) FROM module_set_version WHERE id = :version_id",
            version_id=version_id,
        )
        assert version_count == 1
        member_count = _query_scalar(
            migrated_engine,
            "SELECT COUNT(*) FROM module_set_member WHERE module_set_version_id = :version_id",
            version_id=version_id,
        )
        assert member_count == 2

        # A second, independent request (its own session) reopening it must also see it.
        reopen = real_client.get(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-sets/"
            f"{response.json()['module_set_id']}/versions/1"
        )
        assert reopen.status_code == 200
        assert len(reopen.json()["members"]) == 2


class TestCorsPreflight:
    def test_post_preflight_from_the_configured_frontend_origin_succeeds(
        self, migrated_engine: Engine, real_client: TestClient
    ) -> None:
        """The exact check that would have caught `allow_methods=["GET"]` blocking every POST
        route: a real CORS preflight (`OPTIONS` with `Origin`/`Access-Control-Request-Method`)
        against a real mutating route."""
        project_id, subproject_id, _run_id = _seed_run_with_modules(migrated_engine)

        response = real_client.options(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code != 400, response.text
        assert "POST" in response.headers.get("access-control-allow-methods", "")

    def test_patch_preflight_from_the_configured_frontend_origin_succeeds(
        self, migrated_engine: Engine, real_client: TestClient
    ) -> None:
        """Module-Set Manual Editing increment (docs/23): the identical check, for PATCH --
        caught live during browser verification that `allow_methods` had never been updated
        for the new `PATCH .../members/{member_id}` route, the exact same bug class as the
        POST one above."""
        project_id, subproject_id, run_id = _seed_run_with_modules(migrated_engine)
        draft_id = real_client.post(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts",
            json={"run_record_id": run_id},
        ).json()["id"]

        response = real_client.options(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts/"
            f"{draft_id}/members/00000000-0000-0000-0000-000000000000",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code != 400, response.text
        assert "PATCH" in response.headers.get("access-control-allow-methods", "")


class TestEditDurability:
    """Module-Set Manual Editing increment (docs/23): the exact pattern above, extended to an
    edit, proving a PATCH's own write (a rename and a cross-module reaction reassignment)
    survives independently of the request that made it."""

    def test_an_edit_is_visible_from_a_second_independent_session(
        self, migrated_engine: Engine, real_client: TestClient
    ) -> None:
        project_id, subproject_id, run_id = _seed_run_with_modules(
            migrated_engine, reaction_ids_per_module=[["rX1", "rX2"], ["rY1"]]
        )
        draft = real_client.post(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts",
            json={"run_record_id": run_id},
        ).json()
        member_x = next(
            m for m in draft["members"] if sorted(m["reaction_component_ids"]) == ["rX1", "rX2"]
        )
        member_y = next(m for m in draft["members"] if m["reaction_component_ids"] == ["rY1"])

        response = real_client.patch(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts/"
            f"{draft['id']}/members/{member_y['id']}",
            json={"expected_edit_version": 0, "reaction_component_ids": ["rY1", "rX1"]},
        )
        assert response.status_code == 200

        # Fresh session/connection, opened after the request fully returned.
        member_y_reactions = _query_scalar(
            migrated_engine,
            "SELECT reaction_component_ids FROM module_set_draft_member WHERE id = :id",
            id=member_y["id"],
        )
        member_x_reactions = _query_scalar(
            migrated_engine,
            "SELECT reaction_component_ids FROM module_set_draft_member WHERE id = :id",
            id=member_x["id"],
        )
        assert sorted(json.loads(member_y_reactions)) == ["rX1", "rY1"]
        assert json.loads(member_x_reactions) == ["rX2"]

        edit_version = _query_scalar(
            migrated_engine,
            "SELECT edit_version FROM module_set_draft WHERE id = :id",
            id=draft["id"],
        )
        assert edit_version == 1


class TestSaveWithEditsDurability:
    """Proves the save-time outcome of an edited draft -- renamed/reassigned members, origin
    marked MIXED_EDITED, and the *un*edited member left exactly as increment 21 would have
    saved it -- is durable from a second independent session, and that the invalid,
    unresolved-edit state is rejected rather than ever reaching the database at all."""

    def test_an_invalid_edit_never_reaches_the_database(
        self, migrated_engine: Engine, real_client: TestClient
    ) -> None:
        project_id, subproject_id, run_id = _seed_run_with_modules(
            migrated_engine, reaction_ids_per_module=[["rX1", "rX2"], ["rY1"]]
        )
        draft = real_client.post(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts",
            json={"run_record_id": run_id},
        ).json()
        member_x = next(
            m for m in draft["members"] if sorted(m["reaction_component_ids"]) == ["rX1", "rX2"]
        )

        real_client.patch(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts/"
            f"{draft['id']}/members/{member_x['id']}",
            json={"expected_edit_version": 0, "reaction_component_ids": ["rX1"]},
        )

        response = real_client.post(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts/"
            f"{draft['id']}/save",
            json={"mode": "new_set", "set_name": "Should never exist"},
        )
        assert response.status_code == 422

        set_count = _query_scalar(
            migrated_engine, "SELECT COUNT(*) FROM module_set", id=draft["id"]
        )
        assert set_count == 0

    def test_a_saved_edit_is_durable_and_the_unedited_member_is_untouched(
        self, migrated_engine: Engine, real_client: TestClient
    ) -> None:
        project_id, subproject_id, run_id = _seed_run_with_modules(
            migrated_engine, reaction_ids_per_module=[["rX1", "rX2"], ["rY1"]]
        )
        draft = real_client.post(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts",
            json={"run_record_id": run_id},
        ).json()
        member_x = next(
            m for m in draft["members"] if sorted(m["reaction_component_ids"]) == ["rX1", "rX2"]
        )
        member_y = next(m for m in draft["members"] if m["reaction_component_ids"] == ["rY1"])

        real_client.patch(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts/"
            f"{draft['id']}/members/{member_x['id']}",
            json={"expected_edit_version": 0, "display_name": "Durable rename"},
        )

        save_response = real_client.post(
            f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-set-drafts/"
            f"{draft['id']}/save",
            json={"mode": "new_set", "set_name": "Edited, saved for real"},
        )
        assert save_response.status_code == 201

        origin_method = _query_scalar(
            migrated_engine,
            "SELECT origin_method FROM module_set_version WHERE id = :id",
            id=save_response.json()["id"],
        )
        assert origin_method == "MIXED_EDITED"

        saved_x_name = _query_scalar(
            migrated_engine,
            "SELECT display_name FROM module_set_member WHERE model_module_id = :id",
            id=member_x["model_module_id"],
        )
        saved_y_reactions = _query_scalar(
            migrated_engine,
            "SELECT reaction_component_ids FROM module_set_member WHERE model_module_id = :id",
            id=member_y["model_module_id"],
        )
        assert saved_x_name == "Durable rename"
        assert saved_y_reactions is None  # never edited -- the minimal-diff property holds
