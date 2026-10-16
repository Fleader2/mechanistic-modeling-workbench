"""Tests for ``app.persistence.hierarchy_checkpoint``."""

from __future__ import annotations

import json

import pytest

from app.models.enums import RunStage, RunStatus
from app.models.hierarchy_checkpoint import HierarchyCheckpoint
from app.persistence.hierarchy_checkpoint import (
    create_hierarchy_checkpoint,
    get_current_checkpoint_for_run,
    mark_checkpoint_consumed,
)
from app.persistence.run_record import complete_run, create_run_record, start_run
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


def _payload(**overrides) -> dict:
    data = {
        "checkpoint_version": "hierarchical-recursion-checkpoint-v1",
        "policy_version": "hierarchical-recursion-v1",
        "hierarchy_id": "hierarchical-recursion::test-run",
        "root_model_id": "m1",
        "pending_review_modules": [{"pending_id": "p1", "module_id": "modA"}],
    }
    data.update(overrides)
    return data


def _make_run(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    return run


def test_create_hierarchy_checkpoint_persists_payload_verbatim(db_session):
    run = _make_run(db_session)
    row = create_hierarchy_checkpoint(
        run_record_id=run.id, sequence=0, checkpoint_payload=_payload(), session=db_session
    )
    assert row.checkpoint_version == "hierarchical-recursion-checkpoint-v1"
    assert row.policy_version == "hierarchical-recursion-v1"
    assert row.hierarchy_id == "hierarchical-recursion::test-run"
    assert json.loads(row.payload) == _payload()
    assert row.consumed_at is None


def test_get_current_checkpoint_for_run_returns_highest_sequence(db_session):
    run = _make_run(db_session)
    create_hierarchy_checkpoint(
        run_record_id=run.id, sequence=0, checkpoint_payload=_payload(), session=db_session
    )
    create_hierarchy_checkpoint(
        run_record_id=run.id,
        sequence=1,
        checkpoint_payload=_payload(hierarchy_id="second-pause"),
        session=db_session,
    )
    current = get_current_checkpoint_for_run(db_session, run.id)
    assert current is not None
    assert current.sequence == 1
    assert current.hierarchy_id == "second-pause"


def test_get_current_checkpoint_for_run_returns_none_when_never_paused(db_session):
    run = _make_run(db_session)
    assert get_current_checkpoint_for_run(db_session, run.id) is None


def test_duplicate_sequence_for_the_same_run_is_rejected(db_session):
    from sqlalchemy.exc import IntegrityError

    run = _make_run(db_session)
    create_hierarchy_checkpoint(
        run_record_id=run.id, sequence=0, checkpoint_payload=_payload(), session=db_session
    )
    with pytest.raises(IntegrityError):
        create_hierarchy_checkpoint(
            run_record_id=run.id, sequence=0, checkpoint_payload=_payload(), session=db_session
        )


def test_mark_checkpoint_consumed_sets_timestamp(db_session):
    run = _make_run(db_session)
    row = create_hierarchy_checkpoint(
        run_record_id=run.id, sequence=0, checkpoint_payload=_payload(), session=db_session
    )
    consumed = mark_checkpoint_consumed(db_session, row.id)
    assert consumed.consumed_at is not None


def test_mark_checkpoint_consumed_twice_raises(db_session):
    run = _make_run(db_session)
    row = create_hierarchy_checkpoint(
        run_record_id=run.id, sequence=0, checkpoint_payload=_payload(), session=db_session
    )
    mark_checkpoint_consumed(db_session, row.id)
    with pytest.raises(ValueError, match="already consumed"):
        mark_checkpoint_consumed(db_session, row.id)


def test_hierarchy_checkpoints_are_deleted_when_run_record_is_deleted(db_session):
    run = _make_run(db_session)
    row = create_hierarchy_checkpoint(
        run_record_id=run.id, sequence=0, checkpoint_payload=_payload(), session=db_session
    )
    complete_run(run_record_id=run.id, status=RunStatus.FAILED, session=db_session)
    db_session.delete(run)
    db_session.flush()
    db_session.expunge_all()

    assert db_session.get(HierarchyCheckpoint, row.id) is None
