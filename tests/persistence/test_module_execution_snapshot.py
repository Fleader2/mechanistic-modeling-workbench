"""Tests for ``app.persistence.module_execution_snapshot``."""

from __future__ import annotations

import pytest

from app.models.enums import ModuleExecutionKind, RunStage
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model_module import materialize_accepted_modules
from app.persistence.module_execution_snapshot import (
    create_snapshot,
    get_snapshot_for_run,
    list_snapshots_for_module,
    read_snapshot_payload,
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
        "reason": "recursive search never retained a genuine, non-degenerate candidate",
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
    return subproject_id, module


def _make_calibration_run_record(db_session, module, subproject_id):
    run_record = create_run_record(
        subproject_id=subproject_id,
        stage=RunStage.AGENT4,
        session=db_session,
        model_id=module.root_model_id,
    )
    run_record.model_module_id = module.id
    db_session.flush()
    return start_run(run_record_id=run_record.id, session=db_session)


def test_create_snapshot_persists_payload(db_session):
    subproject_id, module = _make_module(db_session)
    run_record = _make_calibration_run_record(db_session, module, subproject_id)

    snapshot = create_snapshot(
        model_module_id=module.id,
        run_record_id=run_record.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        module_artifact_hash="abc123",
        snapshot_payload={"boundary_ports": [], "calibration_config": {"targets": []}},
        session=db_session,
    )
    assert snapshot.model_module_id == module.id
    assert snapshot.run_record_id == run_record.id
    assert snapshot.execution_kind is ModuleExecutionKind.CALIBRATION
    assert snapshot.module_artifact_hash == "abc123"
    assert read_snapshot_payload(snapshot) == {
        "boundary_ports": [],
        "calibration_config": {"targets": []},
    }


def test_create_snapshot_is_idempotent_by_run_record_id(db_session):
    subproject_id, module = _make_module(db_session)
    run_record = _make_calibration_run_record(db_session, module, subproject_id)

    first = create_snapshot(
        model_module_id=module.id,
        run_record_id=run_record.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        module_artifact_hash="hash-1",
        snapshot_payload={"a": 1},
        session=db_session,
    )
    second = create_snapshot(
        model_module_id=module.id,
        run_record_id=run_record.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        module_artifact_hash="hash-2-never-applied",
        snapshot_payload={"a": "this must never overwrite the first snapshot"},
        session=db_session,
    )
    assert second.id == first.id
    assert second.module_artifact_hash == "hash-1"
    assert read_snapshot_payload(second) == {"a": 1}


def test_get_snapshot_for_run_returns_none_when_absent(db_session):
    subproject_id, module = _make_module(db_session)
    run_record = _make_calibration_run_record(db_session, module, subproject_id)
    assert get_snapshot_for_run(db_session, run_record.id) is None


def test_list_snapshots_for_module_is_scoped(db_session):
    subproject_id, module1 = _make_module(db_session)
    _subproject_id2, module2 = _make_module(db_session)
    run1 = _make_calibration_run_record(db_session, module1, subproject_id)
    run2 = _make_calibration_run_record(db_session, module2, subproject_id)

    create_snapshot(
        model_module_id=module1.id,
        run_record_id=run1.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        module_artifact_hash="h1",
        snapshot_payload={},
        session=db_session,
    )
    create_snapshot(
        model_module_id=module2.id,
        run_record_id=run2.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        module_artifact_hash="h2",
        snapshot_payload={},
        session=db_session,
    )

    snapshots = list_snapshots_for_module(db_session, module1.id)
    assert len(snapshots) == 1
    assert snapshots[0].module_artifact_hash == "h1"


def test_multiple_calibration_runs_each_get_their_own_snapshot(db_session):
    """Repeated calibration with different conditions must never overwrite an earlier
    snapshot -- each run_record_id gets its own, permanently-distinct row."""
    subproject_id, module = _make_module(db_session)
    run1 = _make_calibration_run_record(db_session, module, subproject_id)
    run2 = _make_calibration_run_record(db_session, module, subproject_id)

    snap1 = create_snapshot(
        model_module_id=module.id,
        run_record_id=run1.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        module_artifact_hash="h-run1",
        snapshot_payload={"dataset": "A"},
        session=db_session,
    )
    snap2 = create_snapshot(
        model_module_id=module.id,
        run_record_id=run2.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        module_artifact_hash="h-run2",
        snapshot_payload={"dataset": "B"},
        session=db_session,
    )
    assert snap1.id != snap2.id
    snapshots = list_snapshots_for_module(db_session, module.id)
    assert len(snapshots) == 2
    assert {s.module_artifact_hash for s in snapshots} == {"h-run1", "h-run2"}


def test_fresh_session_reload_preserves_snapshot(db_session):
    subproject_id, module = _make_module(db_session)
    run_record = _make_calibration_run_record(db_session, module, subproject_id)
    snapshot = create_snapshot(
        model_module_id=module.id,
        run_record_id=run_record.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        module_artifact_hash="stable-hash",
        snapshot_payload={
            "boundary_ports": [{"species_id": "s1", "treatment_type": "EXTERNALLY_CONTROLLED"}]
        },
        session=db_session,
    )
    snapshot_id = snapshot.id

    db_session.expire_all()

    reloaded = get_snapshot_for_run(db_session, run_record.id)
    assert reloaded.id == snapshot_id
    assert reloaded.module_artifact_hash == "stable-hash"
    assert read_snapshot_payload(reloaded)["boundary_ports"][0]["species_id"] == "s1"
