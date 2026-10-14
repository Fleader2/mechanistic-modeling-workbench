"""Real, durable, cross-session Workbench <-> Harness persistence verification.

Every other test in this suite runs inside ``db_session``'s own per-test
rolled-back transaction -- correct for isolation, but it can never prove
that persisted state actually survives a real process/session boundary,
which is the entire point of this module. Every test here instead opens
its own, independent, **committing** ``Session`` against the shared
``migrated_engine``, closes it completely, and reopens a fresh one to
reload -- exactly the "subprocess exits, session closes, something else
reloads later" shape a real deployment has. Every row this module creates
is deleted (in a final, committed, fresh session) once the module's tests
finish, so nothing leaks into any other test sharing the same database.

Uses the harness's own synthetic ("Fixture B") canonical input -- no new
biological input and no scientific contract changes. Skipped automatically
if the sibling harness repository/venv is not present.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts.harness import CONTRACT_VERSION, SUPPORTED_ENTRY_STAGE, HarnessInvocationRequest
from app.models.enums import ModelSourceType, ProjectType, RunStatus, SubprojectTaskType
from app.models.model import Model
from app.models.model_build_request import ModelBuildRequest
from app.models.project import Project
from app.models.run_record import RunRecord
from app.models.subproject import Subproject
from app.orchestration import run_orchestrator
from app.orchestration.harness_client import HARNESS_REPO_DIR, harness_is_available, invoke_harness
from app.persistence.model import persist_model
from app.persistence.model_build_request import persist_model_build_request
from app.persistence.project import persist_project
from app.persistence.subproject import persist_subproject

pytestmark = pytest.mark.database

_HARNESS_FIXTURES = HARNESS_REPO_DIR / "tests" / "fixtures"
_HARNESS_UNAVAILABLE = harness_is_available()
_SKIP_IF_NO_HARNESS = pytest.mark.skipif(
    _HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE)
)

_STAGE4_REQUEST = str(_HARNESS_FIXTURES / "synthetic_stage4_request.json")
_STAGE5_REQUEST = str(_HARNESS_FIXTURES / "synthetic_stage5_request.json")
_STAGE1_SYNTHETIC_SOURCE = str(_HARNESS_FIXTURES / "synthetic_agent1_view.json")

_EXPECTED_STAGES = (
    "agent1_curation",
    "agent2_assembly",
    "agent3_simulation",
    "agent4_calibration",
    "agent5_validation",
)


def _delete_recursively(session: Session, project_id, subproject_id) -> None:
    for run_record in session.query(RunRecord).filter_by(subproject_id=subproject_id).all():
        session.delete(run_record)
    session.flush()
    for model in session.query(Model).filter_by(subproject_id=subproject_id).all():
        session.delete(model)
    session.flush()
    mbr = session.query(ModelBuildRequest).filter_by(subproject_id=subproject_id).one_or_none()
    if mbr is not None:
        session.delete(mbr)
        session.flush()
    subproject = session.get(Subproject, subproject_id)
    if subproject is not None:
        session.delete(subproject)
        session.flush()
    project = session.get(Project, project_id)
    if project is not None:
        session.delete(project)
    session.commit()


@pytest.fixture(scope="module")
def committed_setup(migrated_engine: Engine):
    """Create Project/Subproject/ModelBuildRequest/Model in a real, committed
    transaction, then close that session entirely -- simulating a prior,
    independent process boundary that the rest of this module reloads from
    scratch.
    """
    session = Session(bind=migrated_engine)
    suffix = uuid.uuid4().hex[:8]
    try:
        project_result = persist_project(
            stable_identifier=f"PROJ_e2e_{suffix}",
            title="End-to-end persistence verification project",
            project_type=ProjectType.MICROBIAL_METABOLISM,
            session=session,
        )
        subproject_result = persist_subproject(
            project_id=project_result.entity_id,
            title=f"e2e subproject {suffix}",
            task_type=SubprojectTaskType.BUILD_MODEL,
            session=session,
        )
        # ModelBuildRequest is created for metadata completeness only -- no
        # child rows, no Agent 2 scoped-build wiring. See module docstring.
        mbr_result = persist_model_build_request(
            subproject_id=subproject_result.entity_id,
            session=session,
            notes="metadata-only; Agent 2 has no scoped-build mechanism yet",
        )
        model_result = persist_model(
            subproject_id=subproject_result.entity_id,
            stable_identifier=f"MODEL_e2e_{suffix}",
            name="end-to-end verification model",
            source_type=ModelSourceType.GENERATED,
            session=session,
        )
        session.commit()
        ids = {
            "project_id": project_result.entity_id,
            "subproject_id": subproject_result.entity_id,
            "model_build_request_id": mbr_result.entity_id,
            "model_id": model_result.entity_id,
        }
    finally:
        session.close()

    yield ids

    cleanup_session = Session(bind=migrated_engine)
    try:
        _delete_recursively(cleanup_session, ids["project_id"], ids["subproject_id"])
    finally:
        cleanup_session.close()


@pytest.fixture(scope="module")
def real_run_id(committed_setup, migrated_engine: Engine) -> uuid.UUID:
    """Perform the one real, end-to-end Workbench -> Harness -> five-agent
    run, in its own committed session, closed immediately after.

    ``pytest.mark.skipif`` has no effect when applied to a fixture (marks
    only matter on test items) -- this fixture instead calls ``pytest.skip``
    itself, the correct way to make every test depending on it skip when
    the sibling harness repository/venv is not present.
    """
    if _HARNESS_UNAVAILABLE is not None:
        pytest.skip(_HARNESS_UNAVAILABLE)
    session = Session(bind=migrated_engine)
    try:
        run_record = run_orchestrator.submit_subproject_run(
            subproject_id=committed_setup["subproject_id"],
            project_id=committed_setup["project_id"],
            task_type="BUILD_MODEL",
            session=session,
            model_id=committed_setup["model_id"],
            model_build_request_id=committed_setup["model_build_request_id"],
            stage4_request_path=_STAGE4_REQUEST,
            stage5_request_path=_STAGE5_REQUEST,
            synthetic_fixture_path=_STAGE1_SYNTHETIC_SOURCE,
            correlation_id="e2e-persistence-test",
        )
        session.commit()
        return run_record.id
    finally:
        session.close()


# --- The real run itself, and its persisted state reloaded from a fresh session -----------


@_SKIP_IF_NO_HARNESS
def test_real_run_succeeds(real_run_id, migrated_engine):
    session = Session(bind=migrated_engine)
    try:
        run_record = session.get(RunRecord, real_run_id)
        assert run_record is not None
        assert run_record.status is RunStatus.SUCCEEDED
    finally:
        session.close()


@_SKIP_IF_NO_HARNESS
def test_run_record_timestamps_are_consistent_with_pending_running_succeeded(
    real_run_id, migrated_engine
):
    """The transient PENDING/RUNNING states are, by construction, already
    overwritten by the time a synchronous run returns -- each is directly
    exercised in isolation by ``tests/persistence/test_run_record.py``.
    This asserts the one thing a fresh reload *can* still prove about that
    sequence having genuinely happened: real, ordered start/completion
    timestamps, not ``None`` placeholders.
    """
    session = Session(bind=migrated_engine)
    try:
        run_record = session.get(RunRecord, real_run_id)
        assert run_record.started_at is not None
        assert run_record.completed_at is not None
        assert run_record.started_at <= run_record.completed_at
    finally:
        session.close()


@_SKIP_IF_NO_HARNESS
def test_stages_executed_reflects_the_actual_run(real_run_id, migrated_engine):
    session = Session(bind=migrated_engine)
    try:
        run_record = session.get(RunRecord, real_run_id)
        payload = json.loads(run_record.artifact_reference)
        executed = set(payload["output_artifact_references"].keys())
        assert executed == set(_EXPECTED_STAGES)
    finally:
        session.close()


@_SKIP_IF_NO_HARNESS
def test_all_output_artifact_references_exist_on_disk(real_run_id, migrated_engine):
    session = Session(bind=migrated_engine)
    try:
        run_record = session.get(RunRecord, real_run_id)
        payload = json.loads(run_record.artifact_reference)
        for stage_name, path in payload["output_artifact_references"].items():
            assert Path(path).is_file(), f"missing artifact for {stage_name}: {path}"
    finally:
        session.close()


@_SKIP_IF_NO_HARNESS
def test_model_artifact_reference_persisted_onto_the_model_row(
    real_run_id, migrated_engine, committed_setup
):
    session = Session(bind=migrated_engine)
    try:
        run_record = session.get(RunRecord, real_run_id)
        payload = json.loads(run_record.artifact_reference)
        model_row = session.get(Model, committed_setup["model_id"])
        assert model_row.artifact_reference == payload["model_artifact_reference"]
        assert model_row.artifact_reference is not None
        assert Path(model_row.artifact_reference).is_file()
    finally:
        session.close()


@_SKIP_IF_NO_HARNESS
def test_contract_version_metadata_is_persisted(real_run_id, migrated_engine):
    session = Session(bind=migrated_engine)
    try:
        run_record = session.get(RunRecord, real_run_id)
        assert run_record.contract_version == CONTRACT_VERSION
    finally:
        session.close()


@_SKIP_IF_NO_HARNESS
def test_the_workbench_never_parses_or_duplicates_scientific_content(real_run_id, migrated_engine):
    """Every value this module asserts against is a plain string (a status, a
    timestamp, a file path, a version string) -- never anything resembling
    parsed Antimony text, species/reaction data, or simulation results.
    This test documents that boundary explicitly: ``RunRecord`` has no
    column capable of holding such content at all (see
    ``app/models/run_record.py``).
    """
    session = Session(bind=migrated_engine)
    try:
        run_record = session.get(RunRecord, real_run_id)
        column_names = {c.name for c in RunRecord.__table__.columns}
        assert column_names == {
            "id",
            "subproject_id",
            "model_id",
            "model_build_request_id",
            "stage",
            "status",
            "contract_version",
            "artifact_reference",
            "result_summary",
            "error_summary",
            "warnings",
            "started_at",
            "completed_at",
            "created_at",
        }
        assert run_record.result_summary is not None and isinstance(run_record.result_summary, str)
    finally:
        session.close()


@_SKIP_IF_NO_HARNESS
def test_full_run_history_is_reconstructable_from_persisted_state_alone(
    real_run_id, migrated_engine, committed_setup
):
    """What was run, when, which stages, which contract versions, where the
    artifacts are, and whether it succeeded -- reconstructed from a single
    fresh session touching only already-persisted rows, never anything
    held over from the run itself.
    """
    session = Session(bind=migrated_engine)
    try:
        project = session.get(Project, committed_setup["project_id"])
        subproject = session.get(Subproject, committed_setup["subproject_id"])
        run_record = session.get(RunRecord, real_run_id)
        model = session.get(Model, committed_setup["model_id"])

        assert project is not None and subproject.project_id == project.id
        assert run_record.subproject_id == subproject.id
        assert run_record.model_id == model.id

        # what / when / stages / versions / artifacts / outcome:
        assert subproject.task_type is SubprojectTaskType.BUILD_MODEL
        assert run_record.created_at is not None
        assert run_record.started_at is not None and run_record.completed_at is not None
        payload = json.loads(run_record.artifact_reference)
        assert set(payload["output_artifact_references"]) == set(_EXPECTED_STAGES)
        assert run_record.contract_version == CONTRACT_VERSION
        assert run_record.status is RunStatus.SUCCEEDED
    finally:
        session.close()


# --- Replay behavior ------------------------------------------------------------------------


@_SKIP_IF_NO_HARNESS
def test_workbench_layer_replay_never_reinvokes_the_harness(
    real_run_id, migrated_engine, committed_setup
):
    """Calling ``submit_subproject_run`` again with the identical, already-
    terminal ``run_record_id`` must return instantly (no new subprocess
    chain) and must not create a second ``RunRecord`` or touch ``Model``
    lineage.
    """
    session = Session(bind=migrated_engine)
    try:
        before_run_record_count = (
            session.query(RunRecord)
            .filter_by(subproject_id=committed_setup["subproject_id"])
            .count()
        )
        before_model_count = (
            session.query(Model).filter_by(subproject_id=committed_setup["subproject_id"]).count()
        )

        started = time.monotonic()
        replayed_run_record = run_orchestrator.submit_subproject_run(
            subproject_id=committed_setup["subproject_id"],
            project_id=committed_setup["project_id"],
            task_type="BUILD_MODEL",
            session=session,
            model_id=committed_setup["model_id"],
            stage4_request_path=_STAGE4_REQUEST,
            stage5_request_path=_STAGE5_REQUEST,
            synthetic_fixture_path=_STAGE1_SYNTHETIC_SOURCE,
            run_record_id=real_run_id,
        )
        elapsed = time.monotonic() - started
        session.commit()

        after_run_record_count = (
            session.query(RunRecord)
            .filter_by(subproject_id=committed_setup["subproject_id"])
            .count()
        )
        after_model_count = (
            session.query(Model).filter_by(subproject_id=committed_setup["subproject_id"]).count()
        )

        assert replayed_run_record.id == real_run_id
        assert replayed_run_record.status is RunStatus.SUCCEEDED
        # No subprocess chain (tens of seconds) can have run in this time.
        assert elapsed < 2.0
        assert after_run_record_count == before_run_record_count
        assert after_model_count == before_model_count
    finally:
        session.close()


@_SKIP_IF_NO_HARNESS
def test_harness_layer_replay_cache_is_hit_for_the_same_run_id(real_run_id, migrated_engine):
    """Distinct from the Workbench-layer short-circuit above: invoking the
    harness client *directly* (bypassing ``submit_subproject_run``'s own
    terminal-run short-circuit entirely) with the identical ``run_id``
    still gets back the harness's own cached result, with ``replayed=True``
    -- proving the harness's own on-disk replay cache (keyed by ``run_id``)
    is what actually backs this, not merely the Workbench's own shortcut.
    """
    request = HarnessInvocationRequest(
        contract_version=CONTRACT_VERSION,
        run_id=str(real_run_id),
        project_id="irrelevant-for-a-replay",
        subproject_id="irrelevant-for-a-replay",
        task_type="BUILD_MODEL",
        requested_entry_stage=SUPPORTED_ENTRY_STAGE,
    )
    result, error = invoke_harness(request)
    assert error is None
    assert result.replayed is True
    assert result.status.value == "SUCCEEDED"


# --- Failure-path check ----------------------------------------------------------------------


@_SKIP_IF_NO_HARNESS
def test_real_pre_flight_rejection_is_persisted_as_failed_without_corrupting_the_prior_run(
    real_run_id, migrated_engine, committed_setup
):
    """A genuinely new ``RunRecord``/``Model`` pair, deliberately pointed at a
    missing ``stage4_request`` artifact -- a real subprocess invocation of
    the harness's own canonical entrypoint, which really rejects it
    (``MISSING_INPUT_ARTIFACT``), never mocked.
    """
    session = Session(bind=migrated_engine)
    try:
        failing_model_result = persist_model(
            subproject_id=committed_setup["subproject_id"],
            stable_identifier=f"MODEL_e2e_failure_{uuid.uuid4().hex[:8]}",
            name="end-to-end failure-path model",
            source_type=ModelSourceType.GENERATED,
            session=session,
        )
        session.commit()
        failing_model_id = failing_model_result.entity_id

        failed_run_record = run_orchestrator.submit_subproject_run(
            subproject_id=committed_setup["subproject_id"],
            project_id=committed_setup["project_id"],
            task_type="BUILD_MODEL",
            session=session,
            model_id=failing_model_id,
            stage4_request_path=str(Path("/nonexistent") / "stage4_request.json"),
            stage5_request_path=_STAGE5_REQUEST,
            synthetic_fixture_path=_STAGE1_SYNTHETIC_SOURCE,
        )
        session.commit()
        failed_run_record_id = failed_run_record.id
    finally:
        session.close()

    # Reload everything fresh, independently verifying both the new failure
    # and that the prior, already-successful run was left untouched.
    session = Session(bind=migrated_engine)
    try:
        failed = session.get(RunRecord, failed_run_record_id)
        assert failed.status is RunStatus.FAILED
        assert failed.error_summary is not None
        assert "stage4_request" in failed.error_summary

        failing_model_row = session.get(Model, failing_model_id)
        assert failing_model_row.artifact_reference is None  # no false success recorded

        # The prior successful run and its Model are unchanged.
        prior_run_record = session.get(RunRecord, real_run_id)
        assert prior_run_record.status is RunStatus.SUCCEEDED
        prior_model_row = session.get(Model, committed_setup["model_id"])
        assert prior_model_row.artifact_reference is not None
    finally:
        session.delete(session.get(RunRecord, failed_run_record_id))
        session.delete(session.get(Model, failing_model_id))
        session.commit()
        session.close()
