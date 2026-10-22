"""Independent-session/independent-request durability tests for the Model-Specific Alias
Mapping increment's own API surface, plus ownership isolation and CORS preflight for its new
routes -- the same rationale and machinery as ``tests/api/test_module_set_execution_durability
.py``: every assertion here queries through a brand-new ``Session``/connection opened *after*
the triggering request has fully returned, so an uncommitted write could never hide behind a
shared test transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config.settings import API_V1_PREFIX
from app.models.enums import (
    ModelSourceType,
    ModelSpeciesCatalogStatus,
    ProjectType,
    RunStage,
    SubprojectTaskType,
)
from app.persistence.model import persist_model
from app.persistence.model_species_catalog import CapturedSpecies, persist_model_species_catalog
from app.persistence.project import persist_project
from app.persistence.run_record import create_run_record
from app.persistence.subproject import persist_subproject
from app.persistence.time_series_dataset import persist_time_series_dataset
from tests.api.test_module_set_durability import real_client, real_session_app  # noqa: F401
from tests.conftest import reset_test_database
from tests.time_series_helpers import fixture_workbook_bytes


@pytest.fixture(autouse=True)
def _clean_database_before_and_after(
    alembic_config: Config, migrated_engine: Engine
) -> Iterator[None]:
    del migrated_engine
    reset_test_database(alembic_config)
    yield
    reset_test_database(alembic_config)


def _seed(migrated_engine: Engine, *, available: bool = True) -> tuple[str, str, str, str]:
    suffix = uuid.uuid4().hex[:8]
    session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    try:
        project_id = persist_project(
            stable_identifier=f"PRJ-alias-mapping-durability-{suffix}",
            title="alias mapping durability project",
            project_type=ProjectType.MICROBIAL_METABOLISM,
            session=session,
        ).entity_id
        subproject_id = persist_subproject(
            project_id=project_id,
            title="alias mapping durability study",
            task_type=SubprojectTaskType.BUILD_MODEL,
            session=session,
        ).entity_id
        model_id = persist_model(
            subproject_id=subproject_id,
            stable_identifier=f"MOD-alias-mapping-durability-{suffix}",
            name="alias mapping durability model",
            source_type=ModelSourceType.GENERATED,
            session=session,
        ).entity_id
        dataset_id = persist_time_series_dataset(
            session=session,
            project_id=project_id,
            subproject_id=subproject_id,
            original_filename="ras_mapk.xlsx",
            workbook_bytes=fixture_workbook_bytes(),
        ).entity_id
        if available:
            run = create_run_record(
                subproject_id=subproject_id,
                stage=RunStage.HARNESS,
                session=session,
                model_id=model_id,
            )
            session.flush()
            persist_model_species_catalog(
                session=session,
                model_id=model_id,
                source_run_record_id=run.id,
                status=ModelSpeciesCatalogStatus.AVAILABLE,
                species=[
                    CapturedSpecies(
                        antimony_species_id="s_aRAStot",
                        canonical_species_id="canonical-s_aRAStot",
                        display_name="aRAStot",
                        compartment_id="c1",
                        compartment_name="cyto",
                        kind="FLOATING",
                    )
                ],
            )
        session.commit()
        return str(project_id), str(subproject_id), str(dataset_id), str(model_id)
    finally:
        session.close()


def _mapping_url(project_id: str, subproject_id: str, dataset_id: str, model_id: str) -> str:
    return (
        f"{API_V1_PREFIX}/projects/{project_id}/subprojects/{subproject_id}/datasets/"
        f"time-series/{dataset_id}/alias-mapping/{model_id}"
    )


class TestSaveSurvivesAnIndependentSession:
    def test_a_save_is_visible_from_a_second_independent_request(
        self, migrated_engine: Engine, real_client  # noqa: F811
    ) -> None:
        project_id, subproject_id, dataset_id, model_id = _seed(migrated_engine)
        url = _mapping_url(project_id, subproject_id, dataset_id, model_id)

        save_response = real_client.post(
            url,
            json={
                "expected_revision_number": 0,
                "assignments": [
                    {
                        "column_name": "[aRAStot]",
                        "status": "ASSIGNED",
                        "target_antimony_species_id": "s_aRAStot",
                    }
                ],
            },
        )
        assert save_response.status_code == 201

        # A brand-new request, through a brand-new session -- an uncommitted write would be
        # invisible here even though it was visible to a shared-transaction test fixture.
        reopened = real_client.get(url)
        assert reopened.status_code == 200
        assert reopened.json()["revision_number"] == 1

        history = real_client.get(f"{url}/revisions")
        assert history.status_code == 200
        assert len(history.json()) == 1


class TestOwnershipIsolation:
    def test_a_dataset_from_a_different_study_is_not_reachable(
        self, migrated_engine: Engine, real_client  # noqa: F811
    ) -> None:
        _project_id, _subproject_id, dataset_id, model_id = _seed(migrated_engine)
        other_project_id, other_subproject_id, _other_dataset_id, _other_model_id = _seed(
            migrated_engine
        )

        response = real_client.get(
            _mapping_url(other_project_id, other_subproject_id, dataset_id, model_id)
        )
        assert response.status_code == 404

    def test_a_model_from_a_different_study_is_not_reachable(
        self, migrated_engine: Engine, real_client  # noqa: F811
    ) -> None:
        project_id, subproject_id, dataset_id, _model_id = _seed(migrated_engine)
        _other_project, _other_subproject, _other_dataset, other_model_id = _seed(
            migrated_engine
        )

        response = real_client.get(
            _mapping_url(project_id, subproject_id, dataset_id, other_model_id)
        )
        assert response.status_code == 404


class TestCorsPreflight:
    def test_save_post_preflight_succeeds(
        self, migrated_engine: Engine, real_client  # noqa: F811
    ) -> None:
        project_id, subproject_id, dataset_id, model_id = _seed(migrated_engine)
        response = real_client.options(
            _mapping_url(project_id, subproject_id, dataset_id, model_id),
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code != 400, response.text
        assert "POST" in response.headers.get("access-control-allow-methods", "")
