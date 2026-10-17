"""Tests for ``app.persistence.module_aggregate``."""

from __future__ import annotations

import pytest

from app.models.enums import ModuleAggregateCompleteness, ModuleExecutionKind, RunStage
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model_module import materialize_accepted_modules
from app.persistence.module_aggregate import (
    compute_aggregate_fingerprint,
    create_aggregate,
    get_latest_aggregate,
    list_aggregate_versions,
    read_aggregate_payload,
)
from app.persistence.run_record import create_run_record, start_run
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


def _root_node(**overrides) -> dict:
    data = {
        "node_id": "node::depth0::root::000000",
        "depth": 0,
        "parent_modularization_id": None,
        "parent_module_id": None,
        "child_submodel_id": "m1",
        "child_modularization_id": "cand-root",
        "child_module_ids": ["modA"],
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
    data = {
        "node_id": "node::depth1::modA::000001",
        "depth": 1,
        "parent_modularization_id": "cand-root",
        "parent_module_id": "modA",
        "child_submodel_id": "m1::submodel::modA",
        "child_modularization_id": None,
        "child_module_ids": [],
        "accepted": False,
        "reason": "x",
        "baseline_score": "0.3",
        "child_score": None,
        "branch_stopping_reason": "NO_VALID_CHILD_DECOMPOSITION",
        "recursive_search_stopping_reason": "SEARCH_EXHAUSTED",
        "recursive_search_rounds": 1,
        "recursive_search_policy_version": "test-v1",
        "attach_payload": {
            "modularization_id": "cand-root",
            "module_ids": ["modA"],
            "memberships": [
                {"module_id": "modA", "component_type": "REACTION", "component_id": "r1"}
            ],
        },
    }
    data.update(overrides)
    return data


def _make_module(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    create_hierarchy_nodes(
        run_record_id=run.id, nodes=[_root_node(), _modA_node()], session=db_session
    )
    (module,) = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    return run, module


def test_create_aggregate_persists_payload(db_session):
    run, module = _make_module(db_session)
    payload = {"own_result": None, "children": []}
    fingerprint = compute_aggregate_fingerprint(payload)

    aggregate = create_aggregate(
        hierarchy_run_record_id=run.id,
        target_model_module_id=module.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        completeness_status=ModuleAggregateCompleteness.EMPTY,
        input_fingerprint=fingerprint,
        summary_payload=payload,
        session=db_session,
    )
    assert aggregate.version == 1
    assert aggregate.completeness_status is ModuleAggregateCompleteness.EMPTY
    assert read_aggregate_payload(aggregate) == payload


def test_create_aggregate_is_idempotent_by_fingerprint(db_session):
    run, module = _make_module(db_session)
    payload = {"own_result": None, "children": []}
    fingerprint = compute_aggregate_fingerprint(payload)

    first = create_aggregate(
        hierarchy_run_record_id=run.id,
        target_model_module_id=module.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        completeness_status=ModuleAggregateCompleteness.EMPTY,
        input_fingerprint=fingerprint,
        summary_payload=payload,
        session=db_session,
    )
    second = create_aggregate(
        hierarchy_run_record_id=run.id,
        target_model_module_id=module.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        completeness_status=ModuleAggregateCompleteness.COMPLETE,  # must never apply
        input_fingerprint=fingerprint,
        summary_payload={"this": "must never be stored"},
        session=db_session,
    )
    assert second.id == first.id
    assert second.version == 1
    assert read_aggregate_payload(second) == payload


def test_create_aggregate_with_a_new_fingerprint_creates_a_new_version(db_session):
    run, module = _make_module(db_session)
    v1 = create_aggregate(
        hierarchy_run_record_id=run.id,
        target_model_module_id=module.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        completeness_status=ModuleAggregateCompleteness.EMPTY,
        input_fingerprint="fp-1",
        summary_payload={"v": 1},
        session=db_session,
    )
    v2 = create_aggregate(
        hierarchy_run_record_id=run.id,
        target_model_module_id=module.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        completeness_status=ModuleAggregateCompleteness.COMPLETE,
        input_fingerprint="fp-2",
        summary_payload={"v": 2},
        session=db_session,
    )
    assert v2.id != v1.id
    assert v2.version == 2

    versions = list_aggregate_versions(
        db_session, execution_kind=ModuleExecutionKind.SIMULATION, target_model_module_id=module.id
    )
    assert [v.version for v in versions] == [1, 2]

    # The old version is never touched.
    assert read_aggregate_payload(v1) == {"v": 1}

    latest = get_latest_aggregate(
        db_session, execution_kind=ModuleExecutionKind.SIMULATION, target_model_module_id=module.id
    )
    assert latest.id == v2.id


def test_execution_kinds_are_tracked_independently(db_session):
    run, module = _make_module(db_session)
    create_aggregate(
        hierarchy_run_record_id=run.id,
        target_model_module_id=module.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        completeness_status=ModuleAggregateCompleteness.COMPLETE,
        input_fingerprint="fp-sim",
        summary_payload={"kind": "sim"},
        session=db_session,
    )
    create_aggregate(
        hierarchy_run_record_id=run.id,
        target_model_module_id=module.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        completeness_status=ModuleAggregateCompleteness.EMPTY,
        input_fingerprint="fp-calib",
        summary_payload={"kind": "calib"},
        session=db_session,
    )
    sim_latest = get_latest_aggregate(
        db_session, execution_kind=ModuleExecutionKind.SIMULATION, target_model_module_id=module.id
    )
    calib_latest = get_latest_aggregate(
        db_session, execution_kind=ModuleExecutionKind.CALIBRATION, target_model_module_id=module.id
    )
    assert read_aggregate_payload(sim_latest) == {"kind": "sim"}
    assert read_aggregate_payload(calib_latest) == {"kind": "calib"}
    assert sim_latest.version == 1
    assert calib_latest.version == 1  # independent version sequence per kind


def test_root_aggregate_is_queried_by_hierarchy_run_record_id(db_session):
    run, _module = _make_module(db_session)
    root_aggregate = create_aggregate(
        hierarchy_run_record_id=run.id,
        target_model_module_id=None,
        execution_kind=ModuleExecutionKind.SIMULATION,
        completeness_status=ModuleAggregateCompleteness.COMPLETE,
        input_fingerprint="fp-root",
        summary_payload={"root": True},
        session=db_session,
    )
    fetched = get_latest_aggregate(
        db_session, execution_kind=ModuleExecutionKind.SIMULATION, hierarchy_run_record_id=run.id
    )
    assert fetched.id == root_aggregate.id
    assert fetched.target_model_module_id is None


def test_get_latest_aggregate_requires_hierarchy_run_record_id_for_root_queries(db_session):
    with pytest.raises(ValueError, match="hierarchy_run_record_id"):
        get_latest_aggregate(db_session, execution_kind=ModuleExecutionKind.SIMULATION)


def test_get_latest_aggregate_returns_none_when_absent(db_session):
    _run, module = _make_module(db_session)
    assert (
        get_latest_aggregate(
            db_session,
            execution_kind=ModuleExecutionKind.VALIDATION,
            target_model_module_id=module.id,
        )
        is None
    )


def test_fresh_session_reload_preserves_aggregate(db_session):
    run, module = _make_module(db_session)
    aggregate = create_aggregate(
        hierarchy_run_record_id=run.id,
        target_model_module_id=module.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        completeness_status=ModuleAggregateCompleteness.COMPLETE,
        input_fingerprint="fp-reload",
        summary_payload={"children": [{"species_id": "s1"}]},
        session=db_session,
    )
    aggregate_id = aggregate.id

    db_session.expire_all()

    reloaded = get_latest_aggregate(
        db_session, execution_kind=ModuleExecutionKind.SIMULATION, target_model_module_id=module.id
    )
    assert reloaded.id == aggregate_id
    assert read_aggregate_payload(reloaded)["children"][0]["species_id"] == "s1"
