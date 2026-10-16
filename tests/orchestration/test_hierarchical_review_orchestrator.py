"""Tests for ``app.orchestration.hierarchical_review_orchestrator`` (Hierarchical Review/Resume
increment).

Mirrors ``tests/orchestration/test_hierarchical_run_orchestrator.py``'s own established
convention: one real, end-to-end cross-repo integration test exercises the actual sibling
``agent-integration-harness`` repository's real subprocess chain (initial pause -> real
checkpoint -> real resume), skipped automatically if that repository or its venv is not
present; every other test mocks ``invoke_hierarchical_harness``/
``invoke_hierarchical_harness_resume`` -- the Workbench's own persistence/state-machine logic
does not need a real harness to be exercised correctly.
"""

from __future__ import annotations

import json

import pytest

from app.contracts.hierarchical_recursion import (
    CONTRACT_VERSION,
    HierarchicalRunResult,
    HierarchicalRunStatus,
    HierarchyNodeSummary,
)
from app.models.enums import HierarchyReviewDecisionValue, RunStage, RunStatus
from app.orchestration import hierarchical_review_orchestrator as review_orch
from app.orchestration import hierarchical_run_orchestrator as run_orch
from app.orchestration.hierarchical_harness_client import (
    HARNESS_REPO_DIR,
    harness_is_available,
)
from app.persistence.hierarchy_checkpoint import get_current_checkpoint_for_run
from app.persistence.hierarchy_node import list_hierarchy_nodes_for_run
from app.persistence.run_record import create_run_record
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.database

_HARNESS_FIXTURES = HARNESS_REPO_DIR / "tests" / "fixtures"
_HARNESS_UNAVAILABLE = harness_is_available()


def _make_ids(db_session):
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    return project_id, subproject_id


def _recursion_policy(**overrides) -> dict:
    data = {
        "max_depth": 2,
        "min_reactions_per_module": 1,
        "max_total_hierarchy_nodes": 20,
        "max_total_functional_evaluation_budget": 0,
        "max_total_calibration_budget": 10,
        "min_improvement_to_accept_child": "0",
        "require_human_review": True,
        "policy_version": "test-v1",
    }
    data.update(overrides)
    return data


def _search_policy(**overrides) -> dict:
    data = {
        "max_iterations": 1,
        "max_candidates_per_iteration": 10,
        "beam_width": 5,
        "allowed_operations": ["SPLIT_MODULE", "MOVE_REACTION"],
        "policy_version": "test-v1",
    }
    data.update(overrides)
    return data


def _calibration_selection_policy(**overrides) -> dict:
    data = {
        "max_candidates_per_generation": 1,
        "max_modules_per_candidate": None,
        "score_threshold": None,
        "rank_threshold": None,
        "only_if_could_change_ordering": False,
        "total_calibration_run_budget": 10,
        "policy_version": "test-v1",
    }
    data.update(overrides)
    return data


def _flat_orchestration_policy(**overrides) -> dict:
    data = {
        "max_rounds": 1,
        "max_total_candidates": 100,
        "improvement_epsilon": "0",
        "require_human_review": False,
        "policy_version": "test-v1",
    }
    data.update(overrides)
    return data


def _criteria_weights(**overrides) -> dict:
    data = {
        "weights": [{"criterion": "TOPOLOGICAL_SEPARATION", "weight": "1"}],
        "policy_version": "test-v1",
    }
    data.update(overrides)
    return data


def _root_node(**overrides) -> HierarchyNodeSummary:
    data = {
        "node_id": "node::depth0::root::000000",
        "depth": 0,
        "parent_modularization_id": None,
        "parent_module_id": None,
        "child_submodel_id": "m1",
        "child_modularization_id": "cand-root",
        "child_module_ids": ("modA", "modB"),
        "accepted": True,
        "reason": "accepted",
        "baseline_score": None,
        "child_score": "0.5",
        "branch_stopping_reason": "HUMAN_REVIEW_GATE",
        "recursive_search_stopping_reason": "MAX_ROUNDS",
        "recursive_search_rounds": 1,
        "recursive_search_policy_version": "test-v1",
    }
    data.update(overrides)
    return HierarchyNodeSummary(**data)


def _fake_checkpoint(**overrides) -> dict:
    data = {
        "checkpoint_version": "hierarchical-recursion-checkpoint-v1",
        "policy_version": "hierarchical-recursion-v1",
        "hierarchy_id": "hierarchical-recursion::test-run",
        "root_model_id": "m1",
        # Every other field this fake checkpoint carries is opaque payload this repository
        # never parses -- a real checkpoint has many more keys, but no test here needs them.
        "total_nodes_created": 1,
        "total_calibration_runs_used": 1,
    }
    data.update(overrides)
    return data


def _pending_entry(pending_id: str, module_id: str, **overrides) -> dict:
    data = {
        "pending_id": pending_id,
        "parent_node_id": "node::depth0::root::000000",
        "module_id": module_id,
        "depth": 1,
        "reaction_count": 3,
    }
    data.update(overrides)
    return data


def _paused_result(run_id: str, *, pending: tuple[dict, ...]) -> HierarchicalRunResult:
    return HierarchicalRunResult(
        contract_version=CONTRACT_VERSION,
        run_id=run_id,
        status=HierarchicalRunStatus.SUCCEEDED,
        root_model_id="m1",
        nodes=(_root_node(),),
        total_nodes_created=1,
        total_functional_evaluations_used=0,
        total_calibration_runs_used=1,
        requires_user_review=True,
        pending_review_modules=pending,
        recursion_policy_version="hierarchical-recursion-v1",
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:05+00:00",
        error=None,
        summary="paused for review",
        checkpoint=_fake_checkpoint(),
    )


def _start_and_pause(db_session, monkeypatch, *, pending: tuple[dict, ...]):
    project_id, subproject_id = _make_ids(db_session)
    run_id_holder: dict[str, str] = {}

    def _fake_invoke(request):
        run_id_holder["run_id"] = request.run_id
        return _paused_result(request.run_id, pending=pending), None

    monkeypatch.setattr(run_orch, "invoke_hierarchical_harness", _fake_invoke)

    run_record = run_orch.submit_hierarchical_run(
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
        criteria_weights=_criteria_weights(),
        search_policy=_search_policy(),
        calibration_selection_policy=_calibration_selection_policy(),
        flat_orchestration_policy=_flat_orchestration_policy(),
        recursion_policy=_recursion_policy(),
        synthetic_fixture_path="/tmp/stage1.json",
    )
    return run_record


# --- start -> pause -> persist checkpoint ---------------------------------------------------


def test_start_pause_persists_checkpoint_and_pending_items(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modA"), _pending_entry("p2", "modB"))
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)

    assert run_record.status is RunStatus.REQUIRES_USER_REVIEW
    assert run_record.completed_at is None  # a pause is not a terminal state

    checkpoint = get_current_checkpoint_for_run(db_session, run_record.id)
    assert checkpoint is not None
    assert checkpoint.sequence == 0
    assert checkpoint.consumed_at is None
    assert json.loads(checkpoint.payload) == _fake_checkpoint()

    nodes = list_hierarchy_nodes_for_run(db_session, run_record.id)
    assert len(nodes) == 1
    assert nodes[0].accepted is True


# --- reload from a fresh DB/session and reconstruct pending review state --------------------


def test_reload_reconstructs_pending_review_state(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modA"), _pending_entry("p2", "modB"))
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    run_record_id = run_record.id

    # Simulate a fresh read: drop every ORM identity-mapped object this session is holding and
    # re-query from the database rows alone.
    db_session.expire_all()

    reloaded_run_record, reloaded_nodes = review_orch.get_hierarchical_run_status(
        db_session, run_record_id
    )
    assert reloaded_run_record.status is RunStatus.REQUIRES_USER_REVIEW
    assert len(reloaded_nodes) == 1

    reloaded_pending = review_orch.list_pending_review_items(db_session, run_record_id)
    assert {item.pending_id for item in reloaded_pending} == {"p1", "p2"}
    assert {item.module_id for item in reloaded_pending} == {"modA", "modB"}


# --- approve -> resume -> complete -----------------------------------------------------------


def test_approve_resume_completes(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modA"),)
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    items = review_orch.list_pending_review_items(db_session, run_record.id)
    assert len(items) == 1

    review_orch.submit_review_decision(
        pending_review_item_id=items[0].id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )

    def _fake_resume_invoke(request):
        assert request.decisions == {"p1": "APPROVE"}
        child_node = _root_node(
            node_id="node::depth1::modA::000001",
            depth=1,
            parent_modularization_id="cand-root",
            parent_module_id="modA",
            child_submodel_id="m1::submodel::modA",
            child_modularization_id="cand-childA",
            child_module_ids=("modA1", "modA2"),
            branch_stopping_reason=None,
        )
        return (
            HierarchicalRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HierarchicalRunStatus.SUCCEEDED,
                root_model_id="m1",
                nodes=(_root_node(), child_node),
                total_nodes_created=2,
                total_functional_evaluations_used=0,
                total_calibration_runs_used=2,
                requires_user_review=False,
                pending_review_modules=(),
                recursion_policy_version="hierarchical-recursion-v1",
                started_at="2026-01-01T00:01:00+00:00",
                completed_at="2026-01-01T00:01:05+00:00",
                error=None,
                summary="resumed: complete",
            ),
            None,
        )

    monkeypatch.setattr(review_orch, "invoke_hierarchical_harness_resume", _fake_resume_invoke)

    resumed = review_orch.resume_hierarchical_run(run_record_id=run_record.id, session=db_session)
    assert resumed.status is RunStatus.SUCCEEDED

    final_nodes = review_orch.get_final_hierarchy(db_session, run_record.id)
    assert len(final_nodes) == 2
    child = next(n for n in final_nodes if n.depth == 1)
    assert child.accepted is True
    assert child.parent_module_id == "modA"


# --- reject branch ----------------------------------------------------------------------------


def test_reject_branch_records_terminal_node(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modB"),)
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    items = review_orch.list_pending_review_items(db_session, run_record.id)

    review_orch.submit_review_decision(
        pending_review_item_id=items[0].id,
        decision=HierarchyReviewDecisionValue.REJECT,
        session=db_session,
    )

    def _fake_resume_invoke(request):
        assert request.decisions == {"p1": "REJECT"}
        rejected_node = _root_node(
            node_id="node::depth1::modB::000001",
            depth=1,
            parent_modularization_id="cand-root",
            parent_module_id="modB",
            child_submodel_id=None,
            child_modularization_id=None,
            child_module_ids=(),
            accepted=False,
            reason="rejected by human review -- never searched",
            child_score=None,
            branch_stopping_reason="HUMAN_REVIEW_REJECTED",
            recursive_search_stopping_reason="",
            recursive_search_rounds=0,
        )
        return (
            HierarchicalRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HierarchicalRunStatus.SUCCEEDED,
                root_model_id="m1",
                nodes=(_root_node(), rejected_node),
                total_nodes_created=2,
                total_functional_evaluations_used=0,
                total_calibration_runs_used=1,
                requires_user_review=False,
                pending_review_modules=(),
                recursion_policy_version="hierarchical-recursion-v1",
                started_at="2026-01-01T00:01:00+00:00",
                completed_at="2026-01-01T00:01:05+00:00",
                error=None,
                summary="resumed: complete",
            ),
            None,
        )

    monkeypatch.setattr(review_orch, "invoke_hierarchical_harness_resume", _fake_resume_invoke)
    resumed = review_orch.resume_hierarchical_run(run_record_id=run_record.id, session=db_session)
    assert resumed.status is RunStatus.SUCCEEDED

    final_nodes = review_orch.get_final_hierarchy(db_session, run_record.id)
    rejected = next(n for n in final_nodes if n.depth == 1)
    assert rejected.accepted is False
    assert rejected.branch_stopping_reason == "HUMAN_REVIEW_REJECTED"


# --- mixed approve/reject decisions ------------------------------------------------------------


def test_mixed_approve_and_reject_decisions(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modA"), _pending_entry("p2", "modB"))
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    items = {
        item.module_id: item
        for item in review_orch.list_pending_review_items(db_session, run_record.id)
    }

    review_orch.submit_review_decision(
        pending_review_item_id=items["modA"].id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )
    review_orch.submit_review_decision(
        pending_review_item_id=items["modB"].id,
        decision=HierarchyReviewDecisionValue.REJECT,
        session=db_session,
    )

    captured_decisions = {}

    def _fake_resume_invoke(request):
        captured_decisions.update(request.decisions)
        return (
            HierarchicalRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HierarchicalRunStatus.SUCCEEDED,
                root_model_id="m1",
                nodes=(_root_node(),),
                total_nodes_created=1,
                total_functional_evaluations_used=0,
                total_calibration_runs_used=1,
                requires_user_review=False,
                pending_review_modules=(),
                recursion_policy_version="hierarchical-recursion-v1",
                started_at="2026-01-01T00:01:00+00:00",
                completed_at="2026-01-01T00:01:05+00:00",
                error=None,
                summary="resumed",
            ),
            None,
        )

    monkeypatch.setattr(review_orch, "invoke_hierarchical_harness_resume", _fake_resume_invoke)
    review_orch.resume_hierarchical_run(run_record_id=run_record.id, session=db_session)
    assert captured_decisions == {"p1": "APPROVE", "p2": "REJECT"}


# --- repeated/idempotent review submission ------------------------------------------------------


def test_repeated_identical_review_submission_is_idempotent(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modA"),)
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    items = review_orch.list_pending_review_items(db_session, run_record.id)

    first = review_orch.submit_review_decision(
        pending_review_item_id=items[0].id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )
    second = review_orch.submit_review_decision(
        pending_review_item_id=items[0].id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )
    assert first.id == second.id


def test_conflicting_review_resubmission_is_rejected(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modA"),)
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    items = review_orch.list_pending_review_items(db_session, run_record.id)

    review_orch.submit_review_decision(
        pending_review_item_id=items[0].id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )
    with pytest.raises(ValueError):
        review_orch.submit_review_decision(
            pending_review_item_id=items[0].id,
            decision=HierarchyReviewDecisionValue.REJECT,
            session=db_session,
        )


# --- invalid/stale checkpoint or review decision -------------------------------------------------


def test_resume_without_all_decisions_raises(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modA"), _pending_entry("p2", "modB"))
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    items = review_orch.list_pending_review_items(db_session, run_record.id)

    review_orch.submit_review_decision(
        pending_review_item_id=items[0].id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )
    with pytest.raises(ValueError, match="has not been decided"):
        review_orch.resume_hierarchical_run(run_record_id=run_record.id, session=db_session)


def test_repeated_resume_call_never_reinvokes_the_harness(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modA"),)
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    items = review_orch.list_pending_review_items(db_session, run_record.id)
    review_orch.submit_review_decision(
        pending_review_item_id=items[0].id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )

    call_count = {"n": 0}

    def _fake_resume_invoke(request):
        call_count["n"] += 1
        return (
            HierarchicalRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HierarchicalRunStatus.SUCCEEDED,
                root_model_id="m1",
                nodes=(_root_node(),),
                total_nodes_created=1,
                total_functional_evaluations_used=0,
                total_calibration_runs_used=1,
                requires_user_review=False,
                pending_review_modules=(),
                recursion_policy_version="hierarchical-recursion-v1",
                started_at="2026-01-01T00:01:00+00:00",
                completed_at="2026-01-01T00:01:05+00:00",
                error=None,
                summary="resumed",
            ),
            None,
        )

    monkeypatch.setattr(review_orch, "invoke_hierarchical_harness_resume", _fake_resume_invoke)
    resumed = review_orch.resume_hierarchical_run(run_record_id=run_record.id, session=db_session)
    assert resumed.status is RunStatus.SUCCEEDED
    assert call_count["n"] == 1

    # The run is no longer REQUIRES_USER_REVIEW -- a second, repeated call for the identical
    # pause is rejected before ever reaching the harness again (no duplicate child search).
    with pytest.raises(ValueError, match="not REQUIRES_USER_REVIEW"):
        review_orch.resume_hierarchical_run(run_record_id=run_record.id, session=db_session)
    assert call_count["n"] == 1  # the harness was never invoked a second time


def test_submitting_a_decision_against_an_already_consumed_checkpoint_is_rejected_as_stale(
    db_session, monkeypatch
):
    pending = (_pending_entry("p1", "modA"), _pending_entry("p2", "modB"))
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    items = {
        item.module_id: item
        for item in review_orch.list_pending_review_items(db_session, run_record.id)
    }

    review_orch.submit_review_decision(
        pending_review_item_id=items["modA"].id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )
    review_orch.submit_review_decision(
        pending_review_item_id=items["modB"].id,
        decision=HierarchyReviewDecisionValue.REJECT,
        session=db_session,
    )

    def _fake_resume_invoke(request):
        return (
            HierarchicalRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HierarchicalRunStatus.SUCCEEDED,
                root_model_id="m1",
                nodes=(_root_node(),),
                total_nodes_created=1,
                total_functional_evaluations_used=0,
                total_calibration_runs_used=1,
                requires_user_review=False,
                pending_review_modules=(),
                recursion_policy_version="hierarchical-recursion-v1",
                started_at="2026-01-01T00:01:00+00:00",
                completed_at="2026-01-01T00:01:05+00:00",
                error=None,
                summary="resumed",
            ),
            None,
        )

    monkeypatch.setattr(review_orch, "invoke_hierarchical_harness_resume", _fake_resume_invoke)
    review_orch.resume_hierarchical_run(run_record_id=run_record.id, session=db_session)

    # modB's own pending item belonged to the now-consumed checkpoint; a late decision change
    # attempt against it must fail clearly, never silently succeed or affect anything.
    with pytest.raises(review_orch.StaleCheckpointError):
        review_orch.submit_review_decision(
            pending_review_item_id=items["modB"].id,
            decision=HierarchyReviewDecisionValue.APPROVE,
            session=db_session,
        )


def test_resume_on_a_run_not_awaiting_review_raises(db_session):
    _project_id, subproject_id = _make_ids(db_session)
    run_record = create_run_record(
        subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session
    )
    with pytest.raises(ValueError, match="not REQUIRES_USER_REVIEW"):
        review_orch.resume_hierarchical_run(run_record_id=run_record.id, session=db_session)


# --- parent/child/root provenance integrity -----------------------------------------------------


def test_parent_child_root_provenance_integrity_after_resume(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modA"),)
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    items = review_orch.list_pending_review_items(db_session, run_record.id)
    review_orch.submit_review_decision(
        pending_review_item_id=items[0].id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )

    def _fake_resume_invoke(request):
        child_node = _root_node(
            node_id="node::depth1::modA::000001",
            depth=1,
            parent_modularization_id="cand-root",
            parent_module_id="modA",
            child_submodel_id="m1::submodel::modA",
            child_modularization_id="cand-childA",
            child_module_ids=("modA1", "modA2"),
            branch_stopping_reason=None,
        )
        return (
            HierarchicalRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HierarchicalRunStatus.SUCCEEDED,
                root_model_id="m1",
                nodes=(_root_node(), child_node),
                total_nodes_created=2,
                total_functional_evaluations_used=0,
                total_calibration_runs_used=2,
                requires_user_review=False,
                pending_review_modules=(),
                recursion_policy_version="hierarchical-recursion-v1",
                started_at="2026-01-01T00:01:00+00:00",
                completed_at="2026-01-01T00:01:05+00:00",
                error=None,
                summary="resumed",
            ),
            None,
        )

    monkeypatch.setattr(review_orch, "invoke_hierarchical_harness_resume", _fake_resume_invoke)
    review_orch.resume_hierarchical_run(run_record_id=run_record.id, session=db_session)

    nodes = {n.depth: n for n in review_orch.get_final_hierarchy(db_session, run_record.id)}
    root = nodes[0]
    child = nodes[1]
    assert root.parent_modularization_id is None
    assert child.parent_modularization_id == root.child_modularization_id
    assert child.parent_module_id == "modA"
    assert child.run_record_id == root.run_record_id == run_record.id


# --- no duplication of completed hierarchy nodes/artifacts ---------------------------------------


def test_root_node_is_not_duplicated_across_pause_and_resume(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modA"),)
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    items = review_orch.list_pending_review_items(db_session, run_record.id)
    review_orch.submit_review_decision(
        pending_review_item_id=items[0].id,
        decision=HierarchyReviewDecisionValue.APPROVE,
        session=db_session,
    )

    def _fake_resume_invoke(request):
        child_node = _root_node(
            node_id="node::depth1::modA::000001", depth=1, parent_module_id="modA"
        )
        # The harness's own result always carries the already-completed root node forward
        # unchanged, ahead of any new ones -- this fake mirrors that exactly.
        return (
            HierarchicalRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HierarchicalRunStatus.SUCCEEDED,
                root_model_id="m1",
                nodes=(_root_node(), child_node),
                total_nodes_created=2,
                total_functional_evaluations_used=0,
                total_calibration_runs_used=2,
                requires_user_review=False,
                pending_review_modules=(),
                recursion_policy_version="hierarchical-recursion-v1",
                started_at="2026-01-01T00:01:00+00:00",
                completed_at="2026-01-01T00:01:05+00:00",
                error=None,
                summary="resumed",
            ),
            None,
        )

    monkeypatch.setattr(review_orch, "invoke_hierarchical_harness_resume", _fake_resume_invoke)
    review_orch.resume_hierarchical_run(run_record_id=run_record.id, session=db_session)

    nodes = list_hierarchy_nodes_for_run(db_session, run_record.id)
    assert len(nodes) == 2
    root_nodes = [n for n in nodes if n.depth == 0]
    assert len(root_nodes) == 1


# --- final hierarchy retrieval ---------------------------------------------------------------


def test_final_hierarchy_requires_a_succeeded_run(db_session, monkeypatch):
    pending = (_pending_entry("p1", "modA"),)
    run_record = _start_and_pause(db_session, monkeypatch, pending=pending)
    with pytest.raises(ValueError, match="not SUCCEEDED"):
        review_orch.get_final_hierarchy(db_session, run_record.id)


# --- real, end-to-end subprocess integration --------------------------------------------------


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_end_to_end_pause_persist_reload_approve_resume_complete(db_session):
    """Workbench -> Harness -> real Agent 2 subprocess -> HUMAN_REVIEW_GATE -> persisted
    Workbench state -> reload -> approve -> Harness resume -> real Agent 2 subprocess ->
    persisted resumed result. The one real, live cross-repo exercise of this increment."""
    project_id, subproject_id = _make_ids(db_session)

    run_record = run_orch.submit_hierarchical_run(
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
        criteria_weights=_criteria_weights(),
        search_policy=_search_policy(),
        calibration_selection_policy=_calibration_selection_policy(),
        flat_orchestration_policy=_flat_orchestration_policy(),
        recursion_policy=_recursion_policy(),
        exclude_single_module_from_ranking=False,
        synthetic_fixture_path=str(_HARNESS_FIXTURES / "synthetic_agent1_view.json"),
    )
    assert run_record.status is RunStatus.REQUIRES_USER_REVIEW, (
        f"expected a real pause for review: {run_record.result_summary}"
    )
    run_record_id = run_record.id

    # Reload: forget every in-memory object, reconstruct purely from the database.
    db_session.expire_all()
    reloaded_run_record, reloaded_nodes = review_orch.get_hierarchical_run_status(
        db_session, run_record_id
    )
    assert reloaded_run_record.status is RunStatus.REQUIRES_USER_REVIEW
    assert len(reloaded_nodes) >= 1
    root_before = next(n for n in reloaded_nodes if n.depth == 0)

    pending_items = review_orch.list_pending_review_items(db_session, run_record_id)
    assert len(pending_items) >= 1

    for i, item in enumerate(pending_items):
        review_orch.submit_review_decision(
            pending_review_item_id=item.id,
            decision=(
                HierarchyReviewDecisionValue.APPROVE
                if i == 0
                else HierarchyReviewDecisionValue.REJECT
            ),
            session=db_session,
        )

    resumed_run_record = review_orch.resume_hierarchical_run(
        run_record_id=run_record_id, session=db_session
    )
    assert resumed_run_record.status in (RunStatus.SUCCEEDED, RunStatus.REQUIRES_USER_REVIEW)

    nodes_after_resume = list_hierarchy_nodes_for_run(db_session, run_record_id)
    root_after = next(n for n in nodes_after_resume if n.depth == 0)
    assert root_after.id == root_before.id  # the real root node was never re-persisted
    assert len(nodes_after_resume) > len(reloaded_nodes)  # real new node(s) were added
