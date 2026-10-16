"""Tests for ``app.persistence.hierarchy_node``."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import RunStage, RunStatus
from app.persistence.hierarchy_node import create_hierarchy_nodes, list_hierarchy_nodes_for_run
from app.persistence.run_record import complete_run, create_run_record, start_run
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


def _root_node(**overrides) -> dict:
    data = {
        "node_id": "node::depth0::root::aaaa1111",
        "depth": 0,
        "parent_modularization_id": None,
        "parent_module_id": None,
        "child_submodel_id": "m1",
        "child_modularization_id": "cand-root",
        "child_module_ids": ["modA", "modB"],
        "accepted": True,
        "reason": "accepted: overall_score=0.5",
        "baseline_score": None,
        "child_score": "0.5",
        "branch_stopping_reason": None,
        "recursive_search_stopping_reason": "MAX_ROUNDS",
        "recursive_search_rounds": 1,
        "recursive_search_policy_version": "test-v1",
    }
    data.update(overrides)
    return data


def _child_node(**overrides) -> dict:
    data = {
        "node_id": "node::depth1::modA::bbbb2222",
        "depth": 1,
        "parent_modularization_id": "cand-root",
        "parent_module_id": "modA",
        "child_submodel_id": "m1::submodel::modA",
        "child_modularization_id": None,
        "child_module_ids": [],
        "accepted": False,
        "reason": "recursive search never retained a genuine, non-degenerate candidate",
        "baseline_score": "0.3",
        "child_score": None,
        "branch_stopping_reason": "NO_VALID_CHILD_DECOMPOSITION",
        "recursive_search_stopping_reason": "SEARCH_EXHAUSTED",
        "recursive_search_rounds": 1,
        "recursive_search_policy_version": "test-v1",
    }
    data.update(overrides)
    return data


def _make_run(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    return run


def test_create_hierarchy_nodes_persists_every_field(db_session):
    run = _make_run(db_session)
    rows = create_hierarchy_nodes(
        run_record_id=run.id, nodes=[_root_node(), _child_node()], session=db_session
    )
    assert len(rows) == 2
    root_row = next(r for r in rows if r.depth == 0)
    assert root_row.accepted is True
    assert root_row.child_modularization_id == "cand-root"
    assert root_row.child_score == Decimal("0.5")
    assert root_row.baseline_score is None
    assert root_row.branch_stopping_reason is None

    child_row = next(r for r in rows if r.depth == 1)
    assert child_row.accepted is False
    assert child_row.parent_module_id == "modA"
    assert child_row.baseline_score == Decimal("0.3")
    assert child_row.child_score is None
    assert child_row.branch_stopping_reason == "NO_VALID_CHILD_DECOMPOSITION"


def test_list_hierarchy_nodes_for_run_orders_depth_first(db_session):
    run = _make_run(db_session)
    create_hierarchy_nodes(
        run_record_id=run.id,
        nodes=[
            _child_node(node_id="node::depth1::modB::cccc3333", parent_module_id="modB"),
            _root_node(),
            _child_node(),
        ],
        session=db_session,
    )
    nodes = list_hierarchy_nodes_for_run(db_session, run.id)
    assert [n.depth for n in nodes] == [0, 1, 1]


def test_list_hierarchy_nodes_for_run_is_scoped_to_one_run(db_session):
    run1 = _make_run(db_session)
    run2 = _make_run(db_session)
    create_hierarchy_nodes(run_record_id=run1.id, nodes=[_root_node()], session=db_session)
    create_hierarchy_nodes(
        run_record_id=run2.id,
        nodes=[
            _root_node(node_id="node::depth0::root::other", child_modularization_id="cand-other")
        ],
        session=db_session,
    )
    nodes_run1 = list_hierarchy_nodes_for_run(db_session, run1.id)
    assert len(nodes_run1) == 1
    assert nodes_run1[0].child_modularization_id == "cand-root"


def test_hierarchy_nodes_are_deleted_when_run_record_is_deleted(db_session):
    run = _make_run(db_session)
    create_hierarchy_nodes(run_record_id=run.id, nodes=[_root_node()], session=db_session)
    complete_run(run_record_id=run.id, status=RunStatus.SUCCEEDED, session=db_session)

    db_session.delete(run)
    db_session.flush()

    nodes = list_hierarchy_nodes_for_run(db_session, run.id)
    assert nodes == []
