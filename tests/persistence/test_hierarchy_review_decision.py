"""Tests for ``app.persistence.hierarchy_review_decision``."""

from __future__ import annotations

import pytest

from app.models.enums import HierarchyReviewDecisionValue, RunStage
from app.persistence.hierarchy_checkpoint import create_hierarchy_checkpoint
from app.persistence.hierarchy_pending_review_item import create_pending_review_items
from app.persistence.hierarchy_review_decision import get_decision_for_item, submit_review_decision
from app.persistence.run_record import create_run_record, start_run
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


def _make_pending_item(db_session, *, pending_id: str = "p1", module_id: str = "modA"):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    checkpoint = create_hierarchy_checkpoint(
        run_record_id=run.id,
        sequence=0,
        checkpoint_payload={
            "checkpoint_version": "v1",
            "policy_version": "p1",
            "hierarchy_id": "h1",
        },
        session=db_session,
    )
    rows = create_pending_review_items(
        hierarchy_checkpoint_id=checkpoint.id,
        pending_review_modules=[
            {
                "pending_id": pending_id,
                "parent_node_id": "node::depth0::root::000000",
                "module_id": module_id,
                "depth": 1,
                "reaction_count": 3,
            }
        ],
        session=db_session,
    )
    return rows[0]


def test_submit_review_decision_persists_decision(db_session):
    item = _make_pending_item(db_session)
    row = submit_review_decision(
        pending_review_item_id=item.id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
        decided_by="test-user",
        notes="looks fine",
    )
    assert row.decision is HierarchyReviewDecisionValue.APPROVE
    assert row.decided_by == "test-user"
    assert row.notes == "looks fine"
    assert row.decided_at is not None


def test_get_decision_for_item_returns_none_when_undecided(db_session):
    item = _make_pending_item(db_session)
    assert get_decision_for_item(db_session, item.id) is None


def test_resubmitting_the_identical_decision_is_idempotent(db_session):
    item = _make_pending_item(db_session)
    first = submit_review_decision(
        pending_review_item_id=item.id,
        decision=HierarchyReviewDecisionValue.REJECT,
        session=db_session,
    )
    second = submit_review_decision(
        pending_review_item_id=item.id,
        decision=HierarchyReviewDecisionValue.REJECT,
        session=db_session,
    )
    assert first.id == second.id

    from app.models.hierarchy_review_decision import HierarchyReviewDecision

    all_rows = (
        db_session.query(HierarchyReviewDecision).filter_by(pending_review_item_id=item.id).all()
    )
    assert len(all_rows) == 1


def test_resubmitting_a_different_decision_raises(db_session):
    item = _make_pending_item(db_session)
    submit_review_decision(
        pending_review_item_id=item.id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )
    with pytest.raises(ValueError, match="already decided"):
        submit_review_decision(
            pending_review_item_id=item.id,
            decision=HierarchyReviewDecisionValue.REJECT,
            session=db_session,
        )


def test_decisions_for_different_items_are_independent(db_session):
    item1 = _make_pending_item(db_session, pending_id="p1", module_id="modA")
    item2 = _make_pending_item(db_session, pending_id="p2", module_id="modB")
    submit_review_decision(
        pending_review_item_id=item1.id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )
    submit_review_decision(
        pending_review_item_id=item2.id,
        decision=HierarchyReviewDecisionValue.REJECT,
        session=db_session,
    )
    assert (
        get_decision_for_item(db_session, item1.id).decision is HierarchyReviewDecisionValue.APPROVE
    )
    assert (
        get_decision_for_item(db_session, item2.id).decision is HierarchyReviewDecisionValue.REJECT
    )
