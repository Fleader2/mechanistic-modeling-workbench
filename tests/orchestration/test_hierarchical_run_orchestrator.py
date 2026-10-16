"""Tests for ``app.orchestration.hierarchical_run_orchestrator``.

One real, end-to-end cross-repo integration test invokes the actual sibling
``agent-integration-harness`` repository's hierarchical-recursion canonical entrypoint as a
genuine subprocess (skipped automatically if that repository or its venv is not present) --
this is the one place in this repository that exercises the Workbench -> Harness boundary for
the Automatic Hierarchical Recursive Modularization increment, mirroring
``tests/orchestration/test_run_orchestrator.py``'s own identical convention for the
`FULL_PIPELINE` workflow. Every other test mocks ``invoke_hierarchical_harness`` -- the
``RunRecord``/``HierarchyNode`` persistence logic itself does not need a real harness to be
exercised correctly.
"""

from __future__ import annotations

import pytest

from app.contracts.hierarchical_recursion import (
    CONTRACT_VERSION,
    HierarchicalRunError,
    HierarchicalRunResult,
    HierarchicalRunStatus,
    HierarchyNodeSummary,
)
from app.models.enums import RunStatus
from app.orchestration import hierarchical_run_orchestrator
from app.orchestration.hierarchical_harness_client import (
    HARNESS_REPO_DIR,
    HierarchicalHarnessClientError,
    harness_is_available,
)
from app.persistence.hierarchy_node import list_hierarchy_nodes_for_run
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
        "require_human_review": False,
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


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_end_to_end_run_succeeds_and_persists_hierarchy_nodes(db_session):
    """Exercises the Workbench -> Harness boundary for the hierarchical API: a real subprocess
    call to ``run_workbench_hierarchical_request.py``, which itself drives a real Agent 2
    subprocess chain -- the lower Harness -> Agent 2 boundary this same call also proves."""
    project_id, subproject_id = _make_ids(db_session)

    run_record = hierarchical_run_orchestrator.submit_hierarchical_run(
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

    assert run_record.status is RunStatus.SUCCEEDED
    assert run_record.contract_version == CONTRACT_VERSION
    assert run_record.artifact_reference is not None

    nodes = list_hierarchy_nodes_for_run(db_session, run_record.id)
    assert len(nodes) >= 1
    root = next(n for n in nodes if n.depth == 0)
    assert root.accepted is True
    assert root.parent_modularization_id is None
    assert root.parent_module_id is None


def test_requires_exactly_one_stage1_input(db_session):
    project_id, subproject_id = _make_ids(db_session)
    with pytest.raises(ValueError):
        hierarchical_run_orchestrator.submit_hierarchical_run(
            subproject_id=subproject_id,
            project_id=project_id,
            session=db_session,
            criteria_weights=_criteria_weights(),
            search_policy=_search_policy(),
            calibration_selection_policy=_calibration_selection_policy(),
            flat_orchestration_policy=_flat_orchestration_policy(),
            recursion_policy=_recursion_policy(),
        )


def test_harness_subprocess_failure_completes_run_as_failed_with_no_nodes(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)

    def _fake_invoke(request):
        return None, HierarchicalHarnessClientError(
            code="HARNESS_REPO_NOT_FOUND", message="not found"
        )

    monkeypatch.setattr(hierarchical_run_orchestrator, "invoke_hierarchical_harness", _fake_invoke)

    run_record = hierarchical_run_orchestrator.submit_hierarchical_run(
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
    assert run_record.status is RunStatus.FAILED
    assert "HARNESS_REPO_NOT_FOUND" in run_record.error_summary
    assert list_hierarchy_nodes_for_run(db_session, run_record.id) == []


def test_harness_reported_failure_completes_run_as_failed(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)

    def _fake_invoke(request):
        return (
            HierarchicalRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HierarchicalRunStatus.FAILED,
                root_model_id=None,
                nodes=(),
                total_nodes_created=0,
                total_functional_evaluations_used=0,
                total_calibration_runs_used=0,
                requires_user_review=False,
                pending_review_modules=(),
                recursion_policy_version="",
                started_at="2026-01-01T00:00:00+00:00",
                completed_at="2026-01-01T00:00:01+00:00",
                error=HierarchicalRunError(code="INVALID_STAGE1_INPUT", message="bad input"),
                summary="rejected",
            ),
            None,
        )

    monkeypatch.setattr(hierarchical_run_orchestrator, "invoke_hierarchical_harness", _fake_invoke)

    run_record = hierarchical_run_orchestrator.submit_hierarchical_run(
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
    assert run_record.status is RunStatus.FAILED
    assert run_record.error_summary == "bad input"
    assert list_hierarchy_nodes_for_run(db_session, run_record.id) == []


def test_harness_reported_success_persists_nodes_from_mocked_result(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)

    def _fake_invoke(request):
        return (
            HierarchicalRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HierarchicalRunStatus.SUCCEEDED,
                root_model_id="m1",
                nodes=(
                    HierarchyNodeSummary(
                        node_id="node::depth0::root::aaaa",
                        depth=0,
                        parent_modularization_id=None,
                        parent_module_id=None,
                        child_submodel_id="m1",
                        child_modularization_id="cand-root",
                        child_module_ids=("modA", "modB"),
                        accepted=True,
                        reason="accepted",
                        baseline_score=None,
                        child_score="0.5",
                        branch_stopping_reason=None,
                        recursive_search_stopping_reason="MAX_ROUNDS",
                        recursive_search_rounds=1,
                        recursive_search_policy_version="test-v1",
                    ),
                ),
                total_nodes_created=1,
                total_functional_evaluations_used=0,
                total_calibration_runs_used=0,
                requires_user_review=False,
                pending_review_modules=(),
                recursion_policy_version="hierarchical-recursion-v1",
                started_at="2026-01-01T00:00:00+00:00",
                completed_at="2026-01-01T00:00:05+00:00",
                error=None,
                summary="1 node(s) explored",
            ),
            None,
        )

    monkeypatch.setattr(hierarchical_run_orchestrator, "invoke_hierarchical_harness", _fake_invoke)

    run_record = hierarchical_run_orchestrator.submit_hierarchical_run(
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
    assert run_record.status is RunStatus.SUCCEEDED
    nodes = list_hierarchy_nodes_for_run(db_session, run_record.id)
    assert len(nodes) == 1
    assert nodes[0].child_modularization_id == "cand-root"


def test_existing_terminal_run_record_is_replayed_without_reinvoking_harness(
    db_session, monkeypatch
):
    project_id, subproject_id = _make_ids(db_session)

    def _fail_if_called(request):
        raise AssertionError("the harness must not be invoked again for a terminal run")

    def _fake_invoke_once(request):
        return (
            HierarchicalRunResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status=HierarchicalRunStatus.SUCCEEDED,
                root_model_id="m1",
                nodes=(),
                total_nodes_created=0,
                total_functional_evaluations_used=0,
                total_calibration_runs_used=0,
                requires_user_review=False,
                pending_review_modules=(),
                recursion_policy_version="hierarchical-recursion-v1",
                started_at="2026-01-01T00:00:00+00:00",
                completed_at="2026-01-01T00:00:01+00:00",
                error=None,
                summary="ok",
            ),
            None,
        )

    monkeypatch.setattr(
        hierarchical_run_orchestrator, "invoke_hierarchical_harness", _fake_invoke_once
    )
    first = hierarchical_run_orchestrator.submit_hierarchical_run(
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
    assert first.status is RunStatus.SUCCEEDED

    monkeypatch.setattr(
        hierarchical_run_orchestrator, "invoke_hierarchical_harness", _fail_if_called
    )
    replayed = hierarchical_run_orchestrator.submit_hierarchical_run(
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
        criteria_weights=_criteria_weights(),
        search_policy=_search_policy(),
        calibration_selection_policy=_calibration_selection_policy(),
        flat_orchestration_policy=_flat_orchestration_policy(),
        recursion_policy=_recursion_policy(),
        synthetic_fixture_path="/tmp/stage1.json",
        run_record_id=first.id,
    )
    assert replayed.id == first.id
