"""Tests for ``app.persistence.model_module``."""

from __future__ import annotations

import json

import pytest

from app.models.enums import RunStage
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model_module import (
    build_attach_payload,
    count_model_modules_by_run,
    get_model_module,
    list_model_modules_for_run,
    materialize_accepted_modules,
)
from app.persistence.run_record import create_run_record, start_run
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


def _attach_payload(modularization_id: str, module_id: str) -> dict:
    return {
        "modularization_id": modularization_id,
        "module_ids": [module_id],
        "memberships": [
            {"module_id": module_id, "component_type": "REACTION", "component_id": "r1"}
        ],
    }


def _root_node(**overrides) -> dict:
    data = {
        "node_id": "node::depth0::root::000000",
        "depth": 0,
        "parent_modularization_id": None,
        "parent_module_id": None,
        "child_submodel_id": "m1",
        "child_modularization_id": "cand-root",
        "child_module_ids": ["modA", "modB", "modC", "modD"],
        "accepted": True,
        "reason": "accepted",
        "baseline_score": None,
        "child_score": "0.5",
        "branch_stopping_reason": None,
        "recursive_search_stopping_reason": "MAX_ROUNDS",
        "recursive_search_rounds": 1,
        "recursive_search_policy_version": "test-v1",
        "attach_payload": None,
    }
    data.update(overrides)
    return data


def _modA_node(**overrides) -> dict:
    """Depth 1, accepted=False (its own further split was rejected) but genuinely
    materialized -- the common "leaf module" case, still a valid ModelModule."""
    data = {
        "node_id": "node::depth1::modA::000001",
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
        "attach_payload": _attach_payload("cand-root", "modA"),
    }
    data.update(overrides)
    return data


def _modB_node(**overrides) -> dict:
    """Depth 1, accepted=True -- splits further into modB1/modB2."""
    data = {
        "node_id": "node::depth1::modB::000002",
        "depth": 1,
        "parent_modularization_id": "cand-root",
        "parent_module_id": "modB",
        "child_submodel_id": "m1::submodel::modB",
        "child_modularization_id": "cand-modB",
        "child_module_ids": ["modB1", "modB2"],
        "accepted": True,
        "reason": "accepted",
        "baseline_score": "0.2",
        "child_score": "0.6",
        "branch_stopping_reason": None,
        "recursive_search_stopping_reason": "MAX_ROUNDS",
        "recursive_search_rounds": 1,
        "recursive_search_policy_version": "test-v1",
        "attach_payload": _attach_payload("cand-root", "modB"),
    }
    data.update(overrides)
    return data


def _modB1_node(**overrides) -> dict:
    """Depth 2 -- a child of modB's own accepted split."""
    data = {
        "node_id": "node::depth2::modB1::000003",
        "depth": 2,
        "parent_modularization_id": "cand-modB",
        "parent_module_id": "modB1",
        "child_submodel_id": "m1::submodel::modB::submodel::modB1",
        "child_modularization_id": None,
        "child_module_ids": [],
        "accepted": False,
        "reason": "recursive search never retained a genuine, non-degenerate candidate",
        "baseline_score": "0.1",
        "child_score": None,
        "branch_stopping_reason": "NO_VALID_CHILD_DECOMPOSITION",
        "recursive_search_stopping_reason": "SEARCH_EXHAUSTED",
        "recursive_search_rounds": 1,
        "recursive_search_policy_version": "test-v1",
        "attach_payload": _attach_payload("cand-modB", "modB1"),
    }
    data.update(overrides)
    return data


def _too_small_node(**overrides) -> dict:
    data = {
        "node_id": "node::depth1::modC::000004",
        "depth": 1,
        "parent_modularization_id": "cand-root",
        "parent_module_id": "modC",
        "child_submodel_id": None,
        "child_modularization_id": None,
        "child_module_ids": [],
        "accepted": False,
        "reason": "1 reaction(s) is below min_reactions_per_module=2 -- never attempted",
        "baseline_score": None,
        "child_score": None,
        "branch_stopping_reason": "MODULE_TOO_SMALL",
        "recursive_search_stopping_reason": "",
        "recursive_search_rounds": 0,
        "recursive_search_policy_version": "",
        "attach_payload": None,
    }
    data.update(overrides)
    return data


def _rejected_node(**overrides) -> dict:
    data = {
        "node_id": "node::depth1::modD::000005",
        "depth": 1,
        "parent_modularization_id": "cand-root",
        "parent_module_id": "modD",
        "child_submodel_id": None,
        "child_modularization_id": None,
        "child_module_ids": [],
        "accepted": False,
        "reason": "rejected by human review -- never searched",
        "baseline_score": None,
        "child_score": None,
        "branch_stopping_reason": "HUMAN_REVIEW_REJECTED",
        "recursive_search_stopping_reason": "",
        "recursive_search_rounds": 0,
        "recursive_search_policy_version": "",
        "attach_payload": None,
    }
    data.update(overrides)
    return data


def _make_run(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    return run


def test_materialize_creates_a_module_for_a_genuinely_materialized_leaf_node(db_session):
    """A depth>=1 node whose own further split was rejected (accepted=False) is still a
    legitimate, materializable module -- the common case for a real model."""
    run = _make_run(db_session)
    create_hierarchy_nodes(
        run_record_id=run.id, nodes=[_root_node(), _modA_node()], session=db_session
    )
    modules = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    assert len(modules) == 1
    assert modules[0].module_id == "modA"
    assert modules[0].depth == 1
    assert modules[0].source_modularization_id == "cand-root"
    assert modules[0].parent_model_module_id is None  # parent is the root model, not a module


def test_materialize_excludes_too_small_and_rejected_nodes(db_session):
    run = _make_run(db_session)
    create_hierarchy_nodes(
        run_record_id=run.id,
        nodes=[_root_node(), _too_small_node(), _rejected_node()],
        session=db_session,
    )
    modules = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    assert modules == []


def test_materialize_excludes_the_root_node_itself(db_session):
    run = _make_run(db_session)
    create_hierarchy_nodes(run_record_id=run.id, nodes=[_root_node()], session=db_session)
    modules = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    assert modules == []


def test_parent_module_provenance_chain(db_session):
    run = _make_run(db_session)
    create_hierarchy_nodes(
        run_record_id=run.id,
        nodes=[_root_node(), _modB_node(), _modB1_node()],
        session=db_session,
    )
    modules = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    by_module_id = {m.module_id: m for m in modules}
    assert by_module_id["modB"].parent_model_module_id is None
    assert by_module_id["modB1"].parent_model_module_id == by_module_id["modB"].id


def test_materialize_is_idempotent_across_repeated_calls(db_session):
    """Hierarchical Review/Resume increment's own resume/replay never duplicates a module."""
    run = _make_run(db_session)
    create_hierarchy_nodes(
        run_record_id=run.id, nodes=[_root_node(), _modA_node()], session=db_session
    )
    first = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    assert len(first) == 1

    second = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    assert second == []  # nothing new to create

    all_modules = list_model_modules_for_run(db_session, run.id)
    assert len(all_modules) == 1


def test_materialize_handles_new_nodes_added_after_a_resume(db_session):
    run = _make_run(db_session)
    create_hierarchy_nodes(
        run_record_id=run.id, nodes=[_root_node(), _modB_node()], session=db_session
    )
    materialize_accepted_modules(run_record_id=run.id, session=db_session)

    # Simulate a resume that adds modB1 as a new child of the already-materialized modB.
    create_hierarchy_nodes(run_record_id=run.id, nodes=[_modB1_node()], session=db_session)
    new_modules = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    assert len(new_modules) == 1
    assert new_modules[0].module_id == "modB1"

    all_modules = list_model_modules_for_run(db_session, run.id)
    assert len(all_modules) == 2


def test_list_model_modules_for_run_is_scoped_to_one_run(db_session):
    run1 = _make_run(db_session)
    run2 = _make_run(db_session)
    create_hierarchy_nodes(
        run_record_id=run1.id, nodes=[_root_node(), _modA_node()], session=db_session
    )
    create_hierarchy_nodes(
        run_record_id=run2.id,
        nodes=[
            _root_node(node_id="node::depth0::root::other"),
            _modA_node(node_id="node::depth1::modA::other"),
        ],
        session=db_session,
    )
    materialize_accepted_modules(run_record_id=run1.id, session=db_session)
    materialize_accepted_modules(run_record_id=run2.id, session=db_session)
    assert len(list_model_modules_for_run(db_session, run1.id)) == 1
    assert len(list_model_modules_for_run(db_session, run2.id)) == 1


def test_build_attach_payload_round_trips(db_session):
    run = _make_run(db_session)
    create_hierarchy_nodes(
        run_record_id=run.id, nodes=[_root_node(), _modA_node()], session=db_session
    )
    (module,) = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    assert build_attach_payload(module) == _attach_payload("cand-root", "modA")


def test_fresh_session_reload_preserves_identity_and_provenance(db_session):
    run = _make_run(db_session)
    create_hierarchy_nodes(
        run_record_id=run.id, nodes=[_root_node(), _modB_node(), _modB1_node()], session=db_session
    )
    materialize_accepted_modules(run_record_id=run.id, session=db_session)
    db_session.flush()
    db_session.expire_all()

    modules = {m.module_id: m for m in list_model_modules_for_run(db_session, run.id)}
    assert modules["modB1"].parent_model_module_id == modules["modB"].id
    assert json.loads(modules["modB1"].attach_payload) == _attach_payload("cand-modB", "modB1")


def test_get_model_module_returns_none_when_absent(db_session):
    import uuid

    assert get_model_module(db_session, uuid.uuid4()) is None


def test_count_model_modules_by_run_empty(db_session):
    assert count_model_modules_by_run(db_session) == {}


def test_count_model_modules_by_run_aggregates_per_run(db_session):
    run_with_two = _make_run(db_session)
    create_hierarchy_nodes(
        run_record_id=run_with_two.id,
        nodes=[_root_node(), _modA_node(), _modB_node()],
        session=db_session,
    )
    materialize_accepted_modules(run_record_id=run_with_two.id, session=db_session)

    run_with_zero = _make_run(db_session)
    create_hierarchy_nodes(run_record_id=run_with_zero.id, nodes=[_root_node()], session=db_session)
    materialize_accepted_modules(run_record_id=run_with_zero.id, session=db_session)

    counts = count_model_modules_by_run(db_session)

    assert counts[run_with_two.id] == 2
    assert run_with_zero.id not in counts
