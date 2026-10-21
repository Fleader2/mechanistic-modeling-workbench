"""Tests for ``app.persistence.run_record``."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import RunStage, RunStatus
from app.persistence.model_build_request import persist_model_build_request
from app.persistence.run_record import (
    complete_run,
    create_run_record,
    get_run_record,
    list_hierarchical_runs_for_subproject,
    start_run,
)
from tests.persistence.conftest import (
    make_model_id,
    make_subproject_id,
    make_succeeded_hierarchical_run,
)

pytestmark = pytest.mark.database


def test_run_record_lifecycle_success(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.AGENT2, session=db_session)
    assert run.status is RunStatus.PENDING
    assert run.started_at is None

    started = start_run(run_record_id=run.id, session=db_session)
    assert started.status is RunStatus.RUNNING
    assert started.started_at is not None

    completed = complete_run(
        run_record_id=run.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        contract_version="agent2-downstream-v1",
        artifact_reference="harness-run://runs/abc/stage2_output.json",
        result_summary="built 42 reactions",
    )
    assert completed.status is RunStatus.SUCCEEDED
    assert completed.completed_at is not None
    assert completed.contract_version == "agent2-downstream-v1"

    fetched = get_run_record(db_session, run.id)
    assert fetched.status is RunStatus.SUCCEEDED


def test_run_record_lifecycle_failure(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.AGENT3, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    completed = complete_run(
        run_record_id=run.id,
        status=RunStatus.FAILED,
        session=db_session,
        error_summary="numerical instability detected",
    )
    assert completed.status is RunStatus.FAILED
    assert completed.error_summary == "numerical instability detected"


def test_cannot_start_a_run_that_is_not_pending(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.AGENT1, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    with pytest.raises(ValueError):
        start_run(run_record_id=run.id, session=db_session)


def test_cannot_complete_a_run_that_is_not_running(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    with pytest.raises(ValueError):
        complete_run(run_record_id=run.id, status=RunStatus.SUCCEEDED, session=db_session)


def test_complete_run_requires_a_terminal_status(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.AGENT4, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    with pytest.raises(ValueError):
        complete_run(run_record_id=run.id, status=RunStatus.RUNNING, session=db_session)


def test_run_history_is_append_only_across_multiple_runs(db_session):
    subproject_id = make_subproject_id(db_session)
    run_a = create_run_record(
        subproject_id=subproject_id, stage=RunStage.AGENT5, session=db_session
    )
    run_b = create_run_record(
        subproject_id=subproject_id, stage=RunStage.AGENT5, session=db_session
    )
    assert run_a.id != run_b.id


def test_run_record_can_be_associated_with_a_model_build_request(db_session):
    subproject_id = make_subproject_id(db_session)
    mbr_id = persist_model_build_request(subproject_id=subproject_id, session=db_session).entity_id
    run = create_run_record(
        subproject_id=subproject_id,
        stage=RunStage.AGENT2,
        session=db_session,
        model_build_request_id=mbr_id,
    )
    assert run.model_build_request_id == mbr_id


def test_run_record_persists_structured_warnings(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.AGENT2, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    warnings = ["UNRESOLVED_REACTION_REFERENCE: ...", "UNSUPPORTED_PATHWAY_SCOPE: ..."]
    completed = complete_run(
        run_record_id=run.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        warnings=json.dumps(warnings),
    )
    assert json.loads(completed.warnings) == warnings


def test_list_hierarchical_runs_for_subproject_excludes_runs_with_no_model(db_session):
    subproject_id = make_subproject_id(db_session)
    make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id, include_model=False)

    assert list_hierarchical_runs_for_subproject(db_session, subproject_id) == []


def test_list_hierarchical_runs_for_subproject_excludes_non_harness_and_unsucceeded_runs(
    db_session,
):
    subproject_id = make_subproject_id(db_session)
    model_id = make_model_id(db_session, subproject_id=subproject_id)
    # A non-hierarchical, Agent2 run -- never listed here regardless of status.
    agent2_run = create_run_record(
        subproject_id=subproject_id, stage=RunStage.AGENT2, session=db_session, model_id=model_id
    )
    start_run(run_record_id=agent2_run.id, session=db_session)
    complete_run(run_record_id=agent2_run.id, status=RunStatus.SUCCEEDED, session=db_session)
    # A hierarchical run that never finished.
    running_run = create_run_record(
        subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session, model_id=model_id
    )
    start_run(run_record_id=running_run.id, session=db_session)

    assert list_hierarchical_runs_for_subproject(db_session, subproject_id) == []


def test_list_hierarchical_runs_for_subproject_returns_only_this_studys_own_runs_newest_first(
    db_session,
):
    subproject_id = make_subproject_id(db_session)
    other_subproject_id = make_subproject_id(db_session)
    make_succeeded_hierarchical_run(db_session, subproject_id=other_subproject_id)
    older = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    newer = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    # Postgres's own `now()` returns the *transaction's* start time, identical for every
    # statement in this one test's own transaction -- backdate explicitly so the ordering
    # assertion below is deterministic rather than relying on same-timestamp tie-breaking.
    older.created_at = datetime.now(UTC) - timedelta(minutes=5)
    db_session.flush()

    runs = list_hierarchical_runs_for_subproject(db_session, subproject_id)

    assert [r.id for r in runs] == [newer.id, older.id]
