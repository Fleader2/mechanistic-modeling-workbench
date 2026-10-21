"""Independent-session/independent-request durability tests for the Downloadable Two-Tab
Excel Template increment's own API surface, plus CORS preflight for its two new POST routes --
the same rationale and machinery as ``tests/api/test_module_set_execution_durability.py``:
every assertion here queries through a brand-new ``Session``/connection opened *after* the
triggering request has fully returned, so an uncommitted write could never hide behind a
shared test transaction.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config.settings import API_V1_PREFIX
from app.models.enums import ProjectType, SubprojectTaskType
from app.persistence.project import persist_project
from app.persistence.subproject import persist_subproject
from tests.api.test_module_set_durability import real_client, real_session_app  # noqa: F401
from tests.conftest import reset_test_database
from tests.time_series_helpers import fixture_workbook_bytes

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(autouse=True)
def _clean_database_before_and_after(
    alembic_config: Config, migrated_engine: Engine
) -> Iterator[None]:
    del migrated_engine
    reset_test_database(alembic_config)
    yield
    reset_test_database(alembic_config)


def _seed_project_and_study(migrated_engine: Engine) -> tuple[str, str]:
    session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    try:
        project_id = persist_project(
            stable_identifier="PRJ-TS-DURABILITY",
            title="Time-series durability test project",
            project_type=ProjectType.MICROBIAL_METABOLISM,
            session=session,
        ).entity_id
        subproject_id = persist_subproject(
            project_id=project_id,
            title="Time-series durability test study",
            objective="Prove a saved dataset survives independent requests.",
            task_type=SubprojectTaskType.BUILD_MODEL,
            session=session,
        ).entity_id
        session.commit()
        return str(project_id), str(subproject_id)
    finally:
        session.close()


def _base_url(project_id: str, subproject_id: str) -> str:
    return (
        f"{API_V1_PREFIX}/projects/{project_id}/subprojects/{subproject_id}"
        "/datasets/time-series"
    )


class TestSaveSurvivesAnIndependentSession:
    def test_a_save_is_visible_from_a_second_independent_request(
        self, migrated_engine: Engine, real_client  # noqa: F811
    ) -> None:
        project_id, subproject_id = _seed_project_and_study(migrated_engine)
        base = _base_url(project_id, subproject_id)

        save_response = real_client.post(
            base, files={"file": ("ras_mapk.xlsx", fixture_workbook_bytes(), _XLSX_MEDIA_TYPE)}
        )
        assert save_response.status_code == 201
        dataset_id = save_response.json()["id"]

        # A brand-new request, through a brand-new session -- an uncommitted write would be
        # invisible here even though it was visible to a shared-transaction test fixture.
        reopened = real_client.get(f"{base}/{dataset_id}")
        assert reopened.status_code == 200
        assert len(reopened.json()["content"]["rows"]) == 5

        listing = real_client.get(base)
        assert listing.status_code == 200
        assert len(listing.json()) == 1


class TestCorsPreflight:
    def test_preview_post_preflight_succeeds(
        self, migrated_engine: Engine, real_client  # noqa: F811
    ) -> None:
        project_id, subproject_id = _seed_project_and_study(migrated_engine)
        response = real_client.options(
            f"{_base_url(project_id, subproject_id)}/preview",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code != 400, response.text
        assert "POST" in response.headers.get("access-control-allow-methods", "")

    def test_save_post_preflight_succeeds(
        self, migrated_engine: Engine, real_client  # noqa: F811
    ) -> None:
        project_id, subproject_id = _seed_project_and_study(migrated_engine)
        response = real_client.options(
            _base_url(project_id, subproject_id),
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code != 400, response.text
        assert "POST" in response.headers.get("access-control-allow-methods", "")
