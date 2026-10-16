"""Tests for ``app.persistence.hierarchy_resume_attempt``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import HierarchyResumeAttemptStatus, RunStage
from app.persistence.hierarchy_checkpoint import create_hierarchy_checkpoint
from app.persistence.hierarchy_resume_attempt import (
    STALE_RESUME_ATTEMPT_THRESHOLD_SECONDS,
    get_attempt_for_checkpoint,
    get_or_create_resume_attempt,
    is_attempt_stale,
    mark_attempt_failed,
    mark_attempt_in_progress,
    mark_attempt_succeeded,
)
from app.persistence.run_record import create_run_record, start_run
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


def _make_checkpoint(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    return create_hierarchy_checkpoint(
        run_record_id=run.id,
        sequence=0,
        checkpoint_payload={
            "checkpoint_version": "v1",
            "policy_version": "p1",
            "hierarchy_id": "h1",
        },
        session=db_session,
    )


def test_get_or_create_resume_attempt_creates_pending_row(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    assert attempt.status is HierarchyResumeAttemptStatus.PENDING
    assert attempt.attempt_count == 0
    assert attempt.started_at is None


def test_get_or_create_resume_attempt_is_idempotent(db_session):
    checkpoint = _make_checkpoint(db_session)
    first = get_or_create_resume_attempt(hierarchy_checkpoint_id=checkpoint.id, session=db_session)
    second = get_or_create_resume_attempt(hierarchy_checkpoint_id=checkpoint.id, session=db_session)
    assert first.id == second.id


def test_get_attempt_for_checkpoint_returns_none_when_absent(db_session):
    checkpoint = _make_checkpoint(db_session)
    assert get_attempt_for_checkpoint(db_session, checkpoint.id) is None


def test_mark_attempt_in_progress_bumps_count_and_sets_started_at(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    updated = mark_attempt_in_progress(attempt.id, db_session)
    assert updated.status is HierarchyResumeAttemptStatus.IN_PROGRESS
    assert updated.attempt_count == 1
    assert updated.started_at is not None


def test_mark_attempt_in_progress_twice_without_force_raises(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    mark_attempt_in_progress(attempt.id, db_session)
    with pytest.raises(ValueError, match="already IN_PROGRESS"):
        mark_attempt_in_progress(attempt.id, db_session)


def test_mark_attempt_in_progress_twice_with_force_retries(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    mark_attempt_in_progress(attempt.id, db_session)
    retried = mark_attempt_in_progress(attempt.id, db_session, force=True)
    assert retried.attempt_count == 2


def test_mark_attempt_succeeded_requires_in_progress(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    with pytest.raises(ValueError, match="not IN_PROGRESS"):
        mark_attempt_succeeded(attempt.id, db_session)


def test_mark_attempt_succeeded_sets_completed_at(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    mark_attempt_in_progress(attempt.id, db_session)
    succeeded = mark_attempt_succeeded(attempt.id, db_session)
    assert succeeded.status is HierarchyResumeAttemptStatus.SUCCEEDED
    assert succeeded.completed_at is not None


def test_mark_attempt_failed_records_error_summary(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    mark_attempt_in_progress(attempt.id, db_session)
    failed = mark_attempt_failed(attempt.id, db_session, error_summary="boom")
    assert failed.status is HierarchyResumeAttemptStatus.FAILED
    assert failed.error_summary == "boom"
    assert failed.completed_at is not None


def test_mark_attempt_failed_requires_in_progress(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    with pytest.raises(ValueError, match="not IN_PROGRESS"):
        mark_attempt_failed(attempt.id, db_session, error_summary="boom")


def test_failed_attempt_is_retryable_via_mark_in_progress(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    mark_attempt_in_progress(attempt.id, db_session)
    mark_attempt_failed(attempt.id, db_session, error_summary="boom")
    retried = mark_attempt_in_progress(attempt.id, db_session)  # no force needed from FAILED
    assert retried.status is HierarchyResumeAttemptStatus.IN_PROGRESS
    assert retried.attempt_count == 2
    assert retried.error_summary is None  # cleared on retry


def test_is_attempt_stale_false_for_fresh_in_progress(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    attempt = mark_attempt_in_progress(attempt.id, db_session)
    assert is_attempt_stale(attempt) is False


def test_is_attempt_stale_true_once_threshold_exceeded(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    attempt = mark_attempt_in_progress(attempt.id, db_session)
    far_future = attempt.started_at + timedelta(seconds=STALE_RESUME_ATTEMPT_THRESHOLD_SECONDS + 1)
    assert is_attempt_stale(attempt, now=far_future) is True


def test_is_attempt_stale_false_for_non_in_progress_status(db_session):
    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    mark_attempt_in_progress(attempt.id, db_session)
    succeeded = mark_attempt_succeeded(attempt.id, db_session)
    far_future = datetime.now(UTC) + timedelta(seconds=STALE_RESUME_ATTEMPT_THRESHOLD_SECONDS + 1)
    assert is_attempt_stale(succeeded, now=far_future) is False


def test_attempt_is_deleted_when_checkpoint_is_deleted(db_session):
    from app.models.hierarchy_resume_attempt import HierarchyResumeAttempt

    checkpoint = _make_checkpoint(db_session)
    attempt = get_or_create_resume_attempt(
        hierarchy_checkpoint_id=checkpoint.id, session=db_session
    )
    attempt_id = attempt.id

    db_session.delete(checkpoint)
    db_session.flush()
    db_session.expunge_all()

    assert db_session.get(HierarchyResumeAttempt, attempt_id) is None
