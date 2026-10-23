"""Independent-session/independent-request durability tests for the Joint Calibration
Workflow configuration-only increment's own API surface -- the same rationale and machinery as
``tests/api/test_dataset_model_alias_mapping_durability.py``: every assertion here queries
through a brand-new ``Session``/connection opened *after* the triggering request has fully
returned, so an uncommitted write could never hide behind a shared test transaction.
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
    ModelParameterCatalogStatus,
    ModelParameterKind,
    ModelSourceType,
    ModelSpeciesCatalogStatus,
    ProjectType,
    RunStage,
    SubprojectTaskType,
)
from app.persistence.model import persist_model
from app.persistence.model_parameter_catalog import (
    CapturedParameter,
    persist_model_parameter_catalog,
)
from app.persistence.model_species_catalog import CapturedSpecies, persist_model_species_catalog
from app.persistence.project import persist_project
from app.persistence.run_record import create_run_record
from app.persistence.subproject import persist_subproject
from app.persistence.time_series_dataset import persist_time_series_dataset
from tests.api.test_module_set_durability import real_client, real_session_app  # noqa: F401
from tests.conftest import reset_test_database
from tests.time_series_helpers import (
    blank_template_bytes,
    declare_independent_variables,
    declare_measurement_columns,
    declare_measurement_uncertainty,
    fixture_workbook_bytes,
    populate_data_tab,
)

PROJECTS_URL = f"{API_V1_PREFIX}/projects"


@pytest.fixture(autouse=True)
def _clean_database_before_and_after(
    alembic_config: Config, migrated_engine: Engine
) -> Iterator[None]:
    del migrated_engine
    reset_test_database(alembic_config)
    yield
    reset_test_database(alembic_config)


def _seed(migrated_engine: Engine) -> tuple[str, str, str, str]:
    suffix = uuid.uuid4().hex[:8]
    session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    try:
        project_id = persist_project(
            stable_identifier=f"PRJ-calibration-durability-{suffix}",
            title="calibration durability project",
            project_type=ProjectType.MICROBIAL_METABOLISM,
            session=session,
        ).entity_id
        subproject_id = persist_subproject(
            project_id=project_id,
            title="calibration durability study",
            task_type=SubprojectTaskType.BUILD_MODEL,
            session=session,
        ).entity_id
        model_id = persist_model(
            subproject_id=subproject_id,
            stable_identifier=f"MOD-calibration-durability-{suffix}",
            name="calibration durability model",
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
        create_run_record(
            subproject_id=subproject_id, stage=RunStage.HARNESS, session=session, model_id=model_id
        )
        session.commit()
        return str(project_id), str(subproject_id), str(dataset_id), str(model_id)
    finally:
        session.close()


def _jobs_url(project_id: str, subproject_id: str) -> str:
    return f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/calibration-jobs"


class TestConfigurationSurvivesAnIndependentSession:
    def test_a_full_job_configuration_is_visible_from_a_second_independent_request(
        self,
        migrated_engine: Engine,
        real_client,  # noqa: F811
    ) -> None:
        project_id, subproject_id, dataset_id, model_id = _seed(migrated_engine)
        jobs_url = _jobs_url(project_id, subproject_id)

        create = real_client.post(jobs_url, json={"created_by": "dr-test"})
        assert create.status_code == 201
        job_id = create.json()["id"]

        add_arm = real_client.post(
            f"{jobs_url}/{job_id}/arms",
            json={"model_id": model_id, "expected_edit_version": 0},
        )
        assert add_arm.status_code == 201
        arm_id = add_arm.json()["arms"][0]["id"]

        add_experiment = real_client.post(
            f"{jobs_url}/{job_id}/arms/{arm_id}/experiments",
            json={"time_series_dataset_id": dataset_id, "expected_edit_version": 1},
        )
        assert add_experiment.status_code == 201
        experiment_id = add_experiment.json()["arms"][0]["experiments"][0]["id"]

        add_binding = real_client.post(
            f"{jobs_url}/{job_id}/experiments/{experiment_id}/variable-bindings",
            json={
                "model_meaning": "PARAMETER_OVERRIDE",
                "target_component_id": "k_made_up",
                "value_source": "CONSTANT",
                "constant_value": "0.5",
                "expected_edit_version": 2,
            },
        )
        assert add_binding.status_code == 201

        add_role = real_client.post(
            f"{jobs_url}/{job_id}/parameter-roles",
            json={
                "parameter_name": "k1",
                "role": "MODEL_SPECIFIC",
                "arm_ids": [arm_id],
                "lower_bound": "0",
                "upper_bound": "10",
                "expected_edit_version": 3,
            },
        )
        assert add_role.status_code == 201
        edit_version_after_role = add_role.json()["edit_version"]

        # A brand-new request, through a brand-new session -- an uncommitted write would be
        # invisible here even though it was visible to a shared-transaction test fixture.
        reopened = real_client.get(f"{jobs_url}/{job_id}")
        assert reopened.status_code == 200
        body = reopened.json()
        assert body["edit_version"] == edit_version_after_role
        assert len(body["arms"]) == 1
        assert len(body["arms"][0]["experiments"]) == 1
        assert len(body["arms"][0]["experiments"][0]["variable_bindings"]) == 1
        assert body["arms"][0]["experiments"][0]["variable_bindings"][0][
            "target_component_id"
        ] == ("k_made_up")
        assert len(body["parameter_roles"]) == 1
        assert body["parameter_roles"][0]["lower_bound"] == "0"
        assert body["parameter_roles"][0]["catalog_validated"] is False

        review = real_client.get(f"{jobs_url}/{job_id}/review")
        assert review.status_code == 200
        assert review.json()["execution_capability"] == {
            "available": False,
            "reason": "Whole-model execution is not yet available for calibration.",
            "missing_capability": "WHOLE_MODEL_EXECUTION",
        }


class TestOwnershipIsolation:
    def test_a_job_from_a_different_study_is_not_reachable(
        self,
        migrated_engine: Engine,
        real_client,  # noqa: F811
    ) -> None:
        project_id, subproject_id, _dataset_id, _model_id = _seed(migrated_engine)
        other_project_id, other_subproject_id, _od, _om = _seed(migrated_engine)

        create = real_client.post(_jobs_url(project_id, subproject_id), json={})
        job_id = create.json()["id"]

        response = real_client.get(f"{_jobs_url(other_project_id, other_subproject_id)}/{job_id}")
        assert response.status_code == 404


class TestParameterCatalogValidationSurvivesAnIndependentSession:
    def test_catalog_validated_is_true_from_a_second_independent_request(
        self,
        migrated_engine: Engine,
        real_client,  # noqa: F811
    ) -> None:
        project_id, subproject_id, _dataset_id, model_id = _seed(migrated_engine)
        session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
        try:
            run = create_run_record(
                subproject_id=subproject_id,
                stage=RunStage.HARNESS,
                session=session,
                model_id=model_id,
            )
            session.flush()
            persist_model_parameter_catalog(
                session=session,
                model_id=model_id,
                source_run_record_id=run.id,
                status=ModelParameterCatalogStatus.AVAILABLE,
                parameters=[
                    CapturedParameter(
                        antimony_parameter_id="k1",
                        canonical_parameter_id="canonical-k1",
                        display_name="k1",
                        kind=ModelParameterKind.INDEPENDENT.value,
                        unit="1/s",
                    )
                ],
            )
            session.commit()
        finally:
            session.close()

        jobs_url = _jobs_url(project_id, subproject_id)
        job_id = real_client.post(jobs_url, json={}).json()["id"]
        add_arm = real_client.post(
            f"{jobs_url}/{job_id}/arms", json={"model_id": model_id, "expected_edit_version": 0}
        )
        arm_id = add_arm.json()["arms"][0]["id"]

        add_role = real_client.post(
            f"{jobs_url}/{job_id}/parameter-roles",
            json={
                "parameter_name": "k1",
                "role": "MODEL_SPECIFIC",
                "arm_ids": [arm_id],
                "expected_edit_version": 1,
            },
        )
        assert add_role.status_code == 201

        # A brand-new request, through a brand-new session.
        reopened = real_client.get(f"{jobs_url}/{job_id}")
        assert reopened.json()["parameter_roles"][0]["catalog_validated"] is True


class TestJobRevisionsSurviveAnIndependentSession:
    def test_an_earlier_revision_is_unchanged_after_a_later_edit_and_re_review(
        self,
        migrated_engine: Engine,
        real_client,  # noqa: F811
    ) -> None:
        project_id, subproject_id, dataset_id, model_id = _seed(migrated_engine)
        session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
        try:
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
        finally:
            session.close()

        jobs_url = _jobs_url(project_id, subproject_id)
        job_id = real_client.post(jobs_url, json={}).json()["id"]
        add_arm = real_client.post(
            f"{jobs_url}/{job_id}/arms", json={"model_id": model_id, "expected_edit_version": 0}
        )
        arm_id = add_arm.json()["arms"][0]["id"]
        add_experiment = real_client.post(
            f"{jobs_url}/{job_id}/arms/{arm_id}/experiments",
            json={"time_series_dataset_id": dataset_id, "expected_edit_version": 1},
        )
        experiment_id = add_experiment.json()["arms"][0]["experiments"][0]["id"]

        mapping_response = real_client.post(
            f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/datasets/time-series/"
            f"{dataset_id}/alias-mapping/{model_id}",
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
        real_client.patch(
            f"{jobs_url}/{job_id}/experiments/{experiment_id}/mapping",
            json={
                "alias_mapping_revision_number": mapping_response.json()["revision_number"],
                "expected_edit_version": 2,
            },
        )

        add_role = real_client.post(
            f"{jobs_url}/{job_id}/parameter-roles",
            json={
                "parameter_name": "k1",
                "role": "MODEL_SPECIFIC",
                "arm_ids": [arm_id],
                "expected_edit_version": 3,
            },
        )
        edit_version = add_role.json()["edit_version"]

        complete_1 = real_client.post(
            f"{jobs_url}/{job_id}/complete-review", json={"expected_edit_version": edit_version}
        )
        assert complete_1.status_code == 200
        edit_version = complete_1.json()["job"]["edit_version"]

        # A brand-new request, through a brand-new session.
        revisions_after_first = real_client.get(f"{jobs_url}/{job_id}/revisions")
        assert [r["revision_number"] for r in revisions_after_first.json()] == [1]
        first_detail = real_client.get(f"{jobs_url}/{job_id}/revisions/1")
        assert len(first_detail.json()["snapshot"]["parameter_roles"]) == 1

        # A later edit drops the job back to DRAFT and, once reviewed again, captures a
        # second revision -- the first must still read back exactly as it did before.
        add_role_2 = real_client.post(
            f"{jobs_url}/{job_id}/parameter-roles",
            json={
                "parameter_name": "k2",
                "role": "MODEL_SPECIFIC",
                "arm_ids": [arm_id],
                "expected_edit_version": edit_version,
            },
        )
        edit_version = add_role_2.json()["edit_version"]
        complete_2 = real_client.post(
            f"{jobs_url}/{job_id}/complete-review", json={"expected_edit_version": edit_version}
        )
        assert complete_2.status_code == 200

        revisions_after_second = real_client.get(f"{jobs_url}/{job_id}/revisions")
        assert [r["revision_number"] for r in revisions_after_second.json()] == [2, 1]
        first_detail_reread = real_client.get(f"{jobs_url}/{job_id}/revisions/1")
        assert first_detail_reread.json()["snapshot"] == first_detail.json()["snapshot"]
        second_detail = real_client.get(f"{jobs_url}/{job_id}/revisions/2")
        assert len(second_detail.json()["snapshot"]["parameter_roles"]) == 2


class TestDatasetColumnBindingSurvivesAnIndependentSession:
    def test_a_dataset_column_binding_is_visible_from_a_second_independent_request(
        self,
        migrated_engine: Engine,
        real_client,  # noqa: F811
    ) -> None:
        suffix = uuid.uuid4().hex[:8]
        workbook_bytes = declare_independent_variables(
            populate_data_tab(
                blank_template_bytes(),
                headers=("time", "dose_uM"),
                rows=((0, 10.0),),
            ),
            {"dose_uM": ("uM", None)},
        )
        session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
        try:
            project_id = persist_project(
                stable_identifier=f"PRJ-calibration-ivcol-{suffix}",
                title="calibration independent-variable-column durability project",
                project_type=ProjectType.MICROBIAL_METABOLISM,
                session=session,
            ).entity_id
            subproject_id = persist_subproject(
                project_id=project_id,
                title="calibration independent-variable-column durability study",
                task_type=SubprojectTaskType.BUILD_MODEL,
                session=session,
            ).entity_id
            model_id = persist_model(
                subproject_id=subproject_id,
                stable_identifier=f"MOD-calibration-ivcol-{suffix}",
                name="calibration independent-variable-column durability model",
                source_type=ModelSourceType.GENERATED,
                session=session,
            ).entity_id
            dataset_id = persist_time_series_dataset(
                session=session,
                project_id=project_id,
                subproject_id=subproject_id,
                original_filename="dose_response.xlsx",
                workbook_bytes=workbook_bytes,
            ).entity_id
            session.commit()
            project_id, subproject_id = str(project_id), str(subproject_id)
            dataset_id, model_id = str(dataset_id), str(model_id)
        finally:
            session.close()

        jobs_url = _jobs_url(project_id, subproject_id)
        job_id = real_client.post(jobs_url, json={}).json()["id"]
        add_arm = real_client.post(
            f"{jobs_url}/{job_id}/arms", json={"model_id": model_id, "expected_edit_version": 0}
        )
        arm_id = add_arm.json()["arms"][0]["id"]
        add_experiment = real_client.post(
            f"{jobs_url}/{job_id}/arms/{arm_id}/experiments",
            json={"time_series_dataset_id": dataset_id, "expected_edit_version": 1},
        )
        experiment_id = add_experiment.json()["arms"][0]["experiments"][0]["id"]
        assert add_experiment.json()["arms"][0]["experiments"][0]["available_dataset_columns"] == [
            "dose_uM"
        ]

        add_binding = real_client.post(
            f"{jobs_url}/{job_id}/experiments/{experiment_id}/variable-bindings",
            json={
                "model_meaning": "INTERVENTION",
                "target_component_id": "s_made_up_target",
                "value_source": "DATASET_COLUMN",
                "source_column_name": "dose_uM",
                "intervention_time": "0",
                "expected_edit_version": 2,
            },
        )
        assert add_binding.status_code == 201

        # A brand-new request, through a brand-new session.
        reopened = real_client.get(f"{jobs_url}/{job_id}")
        binding = reopened.json()["arms"][0]["experiments"][0]["variable_bindings"][0]
        assert binding["value_source"] == "DATASET_COLUMN"
        assert binding["source_column_name"] == "dose_uM"


class TestOutputWeightingSurvivesAnIndependentSession:
    """``docs/32``'s minimal error/weighting contract."""

    def test_a_measured_output_weighting_and_its_revision_survive_independent_requests(
        self,
        migrated_engine: Engine,
        real_client,  # noqa: F811
    ) -> None:
        suffix = uuid.uuid4().hex[:8]
        workbook_bytes = declare_measurement_uncertainty(
            declare_measurement_columns(
                populate_data_tab(
                    blank_template_bytes(),
                    headers=("time", "glucose_mM", "glucose_mM__sigma"),
                    rows=((0, 1.0, 0.1), (60, 2.0, 0.2)),
                ),
                {"glucose_mM": ("mM", None)},
            ),
            {"glucose_mM__sigma": ("glucose_mM", "SD", "mM", None)},
        )
        session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
        try:
            project_id = persist_project(
                stable_identifier=f"PRJ-calibration-outweight-{suffix}",
                title="calibration output-weighting durability project",
                project_type=ProjectType.MICROBIAL_METABOLISM,
                session=session,
            ).entity_id
            subproject_id = persist_subproject(
                project_id=project_id,
                title="calibration output-weighting durability study",
                task_type=SubprojectTaskType.BUILD_MODEL,
                session=session,
            ).entity_id
            model_id = persist_model(
                subproject_id=subproject_id,
                stable_identifier=f"MOD-calibration-outweight-{suffix}",
                name="calibration output-weighting durability model",
                source_type=ModelSourceType.GENERATED,
                session=session,
            ).entity_id
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
                        antimony_species_id="s_glucose",
                        canonical_species_id="canonical-s_glucose",
                        display_name="glucose",
                        compartment_id="c1",
                        compartment_name="cyto",
                        kind="FLOATING",
                    )
                ],
            )
            dataset_id = persist_time_series_dataset(
                session=session,
                project_id=project_id,
                subproject_id=subproject_id,
                original_filename="glucose.xlsx",
                workbook_bytes=workbook_bytes,
            ).entity_id
            session.commit()
            project_id, subproject_id = str(project_id), str(subproject_id)
            dataset_id, model_id = str(dataset_id), str(model_id)
        finally:
            session.close()

        jobs_url = _jobs_url(project_id, subproject_id)
        job_id = real_client.post(jobs_url, json={}).json()["id"]
        add_arm = real_client.post(
            f"{jobs_url}/{job_id}/arms", json={"model_id": model_id, "expected_edit_version": 0}
        )
        arm_id = add_arm.json()["arms"][0]["id"]
        add_experiment = real_client.post(
            f"{jobs_url}/{job_id}/arms/{arm_id}/experiments",
            json={"time_series_dataset_id": dataset_id, "expected_edit_version": 1},
        )
        experiment_json = add_experiment.json()["arms"][0]["experiments"][0]
        experiment_id = experiment_json["id"]
        assert experiment_json["outputs_with_measured_uncertainty"] == ["glucose_mM"]

        mapping_response = real_client.post(
            f"{PROJECTS_URL}/{project_id}/subprojects/{subproject_id}/datasets/time-series/"
            f"{dataset_id}/alias-mapping/{model_id}",
            json={
                "expected_revision_number": 0,
                "assignments": [
                    {
                        "column_name": "glucose_mM",
                        "status": "ASSIGNED",
                        "target_antimony_species_id": "s_glucose",
                    }
                ],
            },
        )
        real_client.patch(
            f"{jobs_url}/{job_id}/experiments/{experiment_id}/mapping",
            json={
                "alias_mapping_revision_number": mapping_response.json()["revision_number"],
                "expected_edit_version": 2,
            },
        )

        add_weighting = real_client.put(
            f"{jobs_url}/{job_id}/experiments/{experiment_id}/output-weightings",
            json={
                "output_column_name": "glucose_mM",
                "uncertainty_source": "MEASURED",
                "relative_output_weight": "1",
                "expected_edit_version": 3,
            },
        )
        assert add_weighting.status_code == 200
        edit_version = add_weighting.json()["edit_version"]

        add_role = real_client.post(
            f"{jobs_url}/{job_id}/parameter-roles",
            json={
                "parameter_name": "k1",
                "role": "MODEL_SPECIFIC",
                "arm_ids": [arm_id],
                "expected_edit_version": edit_version,
            },
        )
        edit_version = add_role.json()["edit_version"]
        complete = real_client.post(
            f"{jobs_url}/{job_id}/complete-review", json={"expected_edit_version": edit_version}
        )
        assert complete.status_code == 200

        # Brand-new requests, through brand-new sessions.
        reopened = real_client.get(f"{jobs_url}/{job_id}")
        reopened_weighting = reopened.json()["arms"][0]["experiments"][0]["output_weightings"][0]
        assert reopened_weighting["uncertainty_source"] == "MEASURED"
        assert reopened_weighting["relative_output_weight"] == "1"
        # Resolved from the dataset's own declared uncertainty column, never duplicated onto
        # the weighting row itself (docs/32's statistic-kind distinction).
        assert reopened_weighting["effective_statistic_kind"] == "STANDARD_DEVIATION"

        revision_detail = real_client.get(f"{jobs_url}/{job_id}/revisions/1")
        captured = revision_detail.json()["snapshot"]["arms"][0]["experiments"][0][
            "output_weightings"
        ]
        assert len(captured) == 1
        assert captured[0]["output_column_name"] == "glucose_mM"
        assert captured[0]["uncertainty_source"] == "MEASURED"


class TestCorsPreflightAllowsPutAndDelete:
    """``docs/32`` §2's own migration/infrastructure finding: ``allow_methods`` never
    included ``PUT``/``DELETE`` (only ``GET``/``POST``/``PATCH``) -- the exact class of bug
    ``tests/api/test_module_set_durability.py::TestCorsPreflight`` already exists to catch for
    ``POST`` (docs/21/22), silently blocking every ``DELETE``-based "Remove" button and this
    increment's own new ``PUT`` output-weightings route in a real cross-origin browser, even
    though the ordinary, shared-session API test suite could never observe it."""

    def test_delete_preflight_from_the_configured_frontend_origin_succeeds(
        self,
        migrated_engine: Engine,
        real_client,  # noqa: F811
    ) -> None:
        project_id, subproject_id, _dataset_id, model_id = _seed(migrated_engine)
        jobs_url = _jobs_url(project_id, subproject_id)
        job_id = real_client.post(jobs_url, json={}).json()["id"]
        add_arm = real_client.post(
            f"{jobs_url}/{job_id}/arms", json={"model_id": model_id, "expected_edit_version": 0}
        )
        arm_id = add_arm.json()["arms"][0]["id"]

        response = real_client.options(
            f"{jobs_url}/{job_id}/arms/{arm_id}",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code != 400, response.text
        assert "DELETE" in response.headers.get("access-control-allow-methods", "")

    def test_put_preflight_from_the_configured_frontend_origin_succeeds(
        self,
        migrated_engine: Engine,
        real_client,  # noqa: F811
    ) -> None:
        project_id, subproject_id, dataset_id, model_id = _seed(migrated_engine)
        jobs_url = _jobs_url(project_id, subproject_id)
        job_id = real_client.post(jobs_url, json={}).json()["id"]
        add_arm = real_client.post(
            f"{jobs_url}/{job_id}/arms", json={"model_id": model_id, "expected_edit_version": 0}
        )
        arm_id = add_arm.json()["arms"][0]["id"]
        add_experiment = real_client.post(
            f"{jobs_url}/{job_id}/arms/{arm_id}/experiments",
            json={"time_series_dataset_id": dataset_id, "expected_edit_version": 1},
        )
        experiment_id = add_experiment.json()["arms"][0]["experiments"][0]["id"]

        response = real_client.options(
            f"{jobs_url}/{job_id}/experiments/{experiment_id}/output-weightings",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code != 400, response.text
        assert "PUT" in response.headers.get("access-control-allow-methods", "")
