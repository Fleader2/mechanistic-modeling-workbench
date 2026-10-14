"""Tests for ``app.orchestration.run_orchestrator``.

One real, end-to-end cross-repo integration test invokes the actual
sibling ``agent-integration-harness`` repository's canonical entrypoint as
a genuine subprocess (skipped automatically if that repository or its
venv is not present on this machine). Every other test mocks
``invoke_harness`` -- the ``RunRecord`` lifecycle logic itself does not
need a real harness to be exercised correctly.
"""

from __future__ import annotations

import json

import pytest

from app.contracts.harness import (
    CONTRACT_VERSION,
    HarnessRunError,
    HarnessRunResult,
    HarnessRunStatus,
)
from app.models.enums import RunStatus
from app.orchestration import run_orchestrator
from app.orchestration.harness_client import (
    HARNESS_REPO_DIR,
    HarnessClientError,
    harness_is_available,
)
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.database

_HARNESS_FIXTURES = HARNESS_REPO_DIR / "tests" / "fixtures"
_HARNESS_UNAVAILABLE = harness_is_available()


def _make_ids(db_session):
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    return project_id, subproject_id


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_end_to_end_run_succeeds(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run_record = run_orchestrator.submit_subproject_run(
        subproject_id=subproject_id,
        project_id=project_id,
        task_type="BUILD_MODEL",
        session=db_session,
        stage4_request_path=str(_HARNESS_FIXTURES / "synthetic_stage4_request.json"),
        stage5_request_path=str(_HARNESS_FIXTURES / "synthetic_stage5_request.json"),
        synthetic_fixture_path=str(_HARNESS_FIXTURES / "synthetic_agent1_view.json"),
    )
    assert run_record.status is RunStatus.SUCCEEDED
    assert run_record.contract_version == CONTRACT_VERSION
    assert run_record.artifact_reference is not None
    payload = json.loads(run_record.artifact_reference)
    assert payload["model_artifact_reference"] is not None


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_run_populates_model_artifact_reference(db_session):
    from app.models.enums import ModelSourceType
    from app.persistence.model import get_model, persist_model

    project_id, subproject_id = _make_ids(db_session)
    model_result = persist_model(
        subproject_id=subproject_id,
        stable_identifier="MODEL_orchestrator_test",
        name="orchestrator test model",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )

    run_orchestrator.submit_subproject_run(
        subproject_id=subproject_id,
        project_id=project_id,
        task_type="BUILD_MODEL",
        session=db_session,
        model_id=model_result.entity_id,
        stage4_request_path=str(_HARNESS_FIXTURES / "synthetic_stage4_request.json"),
        stage5_request_path=str(_HARNESS_FIXTURES / "synthetic_stage5_request.json"),
        synthetic_fixture_path=str(_HARNESS_FIXTURES / "synthetic_agent1_view.json"),
    )

    model_row = get_model(db_session, model_result.entity_id)
    assert model_row.artifact_reference is not None


def test_requires_exactly_one_stage1_input(db_session):
    project_id, subproject_id = _make_ids(db_session)
    with pytest.raises(ValueError):
        run_orchestrator.submit_subproject_run(
            subproject_id=subproject_id,
            project_id=project_id,
            task_type="BUILD_MODEL",
            session=db_session,
            stage4_request_path="/tmp/x.json",
            stage5_request_path="/tmp/y.json",
        )


# --- Scoped-Build Support increment: real, end-to-end ModelBuildRequest wiring -------------


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_scoped_build_run_persists_model_build_request_id_and_warnings(db_session):
    """A real, end-to-end run (no mocks) supplying ``model_build_request_id``: the Workbench
    serializes the persisted ``ModelBuildRequest``, the harness forwards it to a real Agent 2
    subprocess, and the resulting warning (the synthetic fixture's own reaction ids are plain
    strings, not real Agent 1 UUIDs, so this request's own reference is unresolved by
    design) round-trips back onto the ``RunRecord``."""
    import json

    from app.models.enums import ModelBuildRequestReactionRole
    from app.persistence.model_build_request import add_reaction, persist_model_build_request

    project_id, subproject_id = _make_ids(db_session)
    mbr_id = persist_model_build_request(subproject_id=subproject_id, session=db_session).entity_id
    add_reaction(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestReactionRole.SEED,
        session=db_session,
        raw_identifier="reaction-1",
    )

    run_record = run_orchestrator.submit_subproject_run(
        subproject_id=subproject_id,
        project_id=project_id,
        task_type="BUILD_MODEL",
        session=db_session,
        model_build_request_id=mbr_id,
        stage4_request_path=str(_HARNESS_FIXTURES / "synthetic_stage4_request.json"),
        stage5_request_path=str(_HARNESS_FIXTURES / "synthetic_stage5_request.json"),
        synthetic_fixture_path=str(_HARNESS_FIXTURES / "synthetic_agent1_view.json"),
    )

    assert run_record.status is RunStatus.SUCCEEDED
    assert run_record.model_build_request_id == mbr_id
    assert run_record.warnings is not None
    warnings = json.loads(run_record.warnings)
    assert any("UNRESOLVED_RAW_IDENTIFIER" in w for w in warnings)


def test_harness_subprocess_failure_completes_run_as_failed(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)

    def _fake_invoke(request):
        return None, HarnessClientError(code="HARNESS_REPO_NOT_FOUND", message="not found")

    monkeypatch.setattr(run_orchestrator, "invoke_harness", _fake_invoke)

    run_record = run_orchestrator.submit_subproject_run(
        subproject_id=subproject_id,
        project_id=project_id,
        task_type="BUILD_MODEL",
        session=db_session,
        stage4_request_path="/tmp/x.json",
        stage5_request_path="/tmp/y.json",
        synthetic_fixture_path="/tmp/stage1.json",
    )
    assert run_record.status is RunStatus.FAILED
    assert "HARNESS_REPO_NOT_FOUND" in run_record.error_summary


def test_harness_reported_failure_completes_run_as_failed(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)

    def _fake_invoke(request):
        return (
            HarnessRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HarnessRunStatus.FAILED,
                stages_executed=("agent1_curation",),
                output_artifact_references={},
                model_artifact_reference=None,
                agent_contract_versions={},
                started_at="2026-01-01T00:00:00+00:00",
                completed_at="2026-01-01T00:00:01+00:00",
                error=HarnessRunError(
                    code="WORKFLOW_FAILED", message="stage failed", stage_name="agent2_assembly"
                ),
                summary="workflow stopped",
            ),
            None,
        )

    monkeypatch.setattr(run_orchestrator, "invoke_harness", _fake_invoke)

    run_record = run_orchestrator.submit_subproject_run(
        subproject_id=subproject_id,
        project_id=project_id,
        task_type="BUILD_MODEL",
        session=db_session,
        stage4_request_path="/tmp/x.json",
        stage5_request_path="/tmp/y.json",
        synthetic_fixture_path="/tmp/stage1.json",
    )
    assert run_record.status is RunStatus.FAILED
    assert run_record.error_summary == "stage failed"


def test_replaying_an_already_terminal_run_never_invokes_the_harness(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)

    def _fake_invoke(request):
        return (
            HarnessRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HarnessRunStatus.SUCCEEDED,
                stages_executed=("agent1_curation",),
                output_artifact_references={"agent1_curation": "/tmp/stage1.json"},
                model_artifact_reference=None,
                agent_contract_versions={},
                started_at="2026-01-01T00:00:00+00:00",
                completed_at="2026-01-01T00:00:01+00:00",
                error=None,
                summary="ok",
            ),
            None,
        )

    monkeypatch.setattr(run_orchestrator, "invoke_harness", _fake_invoke)

    first = run_orchestrator.submit_subproject_run(
        subproject_id=subproject_id,
        project_id=project_id,
        task_type="BUILD_MODEL",
        session=db_session,
        stage4_request_path="/tmp/x.json",
        stage5_request_path="/tmp/y.json",
        synthetic_fixture_path="/tmp/stage1.json",
    )
    assert first.status is RunStatus.SUCCEEDED

    def _fail_if_called(request):
        raise AssertionError("invoke_harness must not be called for an already-terminal replay")

    monkeypatch.setattr(run_orchestrator, "invoke_harness", _fail_if_called)

    second = run_orchestrator.submit_subproject_run(
        subproject_id=subproject_id,
        project_id=project_id,
        task_type="BUILD_MODEL",
        session=db_session,
        stage4_request_path="/tmp/x.json",
        stage5_request_path="/tmp/y.json",
        synthetic_fixture_path="/tmp/stage1.json",
        run_record_id=first.id,
    )
    assert second.id == first.id
    assert second.status is RunStatus.SUCCEEDED


def test_unknown_run_record_id_raises(db_session):
    import uuid

    project_id, subproject_id = _make_ids(db_session)
    with pytest.raises(ValueError):
        run_orchestrator.submit_subproject_run(
            subproject_id=subproject_id,
            project_id=project_id,
            task_type="BUILD_MODEL",
            session=db_session,
            stage4_request_path="/tmp/x.json",
            stage5_request_path="/tmp/y.json",
            synthetic_fixture_path="/tmp/stage1.json",
            run_record_id=uuid.uuid4(),
        )
