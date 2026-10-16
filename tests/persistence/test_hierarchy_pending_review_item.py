"""Tests for ``app.persistence.hierarchy_pending_review_item``."""

from __future__ import annotations

import pytest

from app.models.enums import RunStage
from app.persistence.hierarchy_checkpoint import create_hierarchy_checkpoint
from app.persistence.hierarchy_pending_review_item import (
    create_pending_review_items,
    get_pending_review_item,
    list_pending_review_items_for_checkpoint,
)
from app.persistence.run_record import create_run_record, start_run
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


def _entry(pending_id: str, module_id: str, **overrides) -> dict:
    data = {
        "pending_id": pending_id,
        "parent_node_id": "node::depth0::root::000000",
        "module_id": module_id,
        "depth": 1,
        "reaction_count": 3,
    }
    data.update(overrides)
    return data


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


def test_create_pending_review_items_persists_every_field(db_session):
    checkpoint = _make_checkpoint(db_session)
    rows = create_pending_review_items(
        hierarchy_checkpoint_id=checkpoint.id,
        pending_review_modules=[_entry("p1", "modA"), _entry("p2", "modB", reaction_count=None)],
        session=db_session,
    )
    assert len(rows) == 2
    modA = next(r for r in rows if r.module_id == "modA")
    assert modA.pending_id == "p1"
    assert modA.parent_node_id == "node::depth0::root::000000"
    assert modA.depth == 1
    assert modA.reaction_count == 3

    modB = next(r for r in rows if r.module_id == "modB")
    assert modB.reaction_count is None


def test_list_pending_review_items_for_checkpoint_is_scoped(db_session):
    checkpoint1 = _make_checkpoint(db_session)
    checkpoint2 = _make_checkpoint(db_session)
    create_pending_review_items(
        hierarchy_checkpoint_id=checkpoint1.id,
        pending_review_modules=[_entry("p1", "modA")],
        session=db_session,
    )
    create_pending_review_items(
        hierarchy_checkpoint_id=checkpoint2.id,
        pending_review_modules=[_entry("p2", "modB")],
        session=db_session,
    )
    items1 = list_pending_review_items_for_checkpoint(db_session, checkpoint1.id)
    assert [i.module_id for i in items1] == ["modA"]


def test_duplicate_pending_id_for_the_same_checkpoint_is_rejected(db_session):
    from sqlalchemy.exc import IntegrityError

    checkpoint = _make_checkpoint(db_session)
    create_pending_review_items(
        hierarchy_checkpoint_id=checkpoint.id,
        pending_review_modules=[_entry("p1", "modA")],
        session=db_session,
    )
    with pytest.raises(IntegrityError):
        create_pending_review_items(
            hierarchy_checkpoint_id=checkpoint.id,
            pending_review_modules=[_entry("p1", "modA")],
            session=db_session,
        )


def test_get_pending_review_item_by_id(db_session):
    checkpoint = _make_checkpoint(db_session)
    rows = create_pending_review_items(
        hierarchy_checkpoint_id=checkpoint.id,
        pending_review_modules=[_entry("p1", "modA")],
        session=db_session,
    )
    fetched = get_pending_review_item(db_session, rows[0].id)
    assert fetched is not None
    assert fetched.module_id == "modA"
    assert get_pending_review_item(db_session, checkpoint.id) is None
