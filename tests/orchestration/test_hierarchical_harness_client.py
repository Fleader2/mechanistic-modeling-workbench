"""Tests for ``app.orchestration.hierarchical_harness_client``.

Mirrors ``tests/orchestration/test_harness_client.py``'s own identical convention: every
failure path is exercised via ``monkeypatch`` against ``subprocess.run`` or the module's own
repo-location constants, so these tests run fast and never depend on the sibling harness
repository actually being present -- the one real subprocess invocation lives in
``tests/orchestration/test_hierarchical_run_orchestrator.py``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from app.contracts.hierarchical_recursion import CONTRACT_VERSION, HierarchicalInvocationRequest
from app.orchestration import hierarchical_harness_client

pytestmark = pytest.mark.unit


def _request(run_id: str = "test-run") -> HierarchicalInvocationRequest:
    return HierarchicalInvocationRequest(
        contract_version=CONTRACT_VERSION,
        run_id=run_id,
        project_id="proj-1",
        subproject_id="sub-1",
        criteria_weights={"weights": [], "policy_version": "test-v1"},
        search_policy={
            "max_iterations": 1,
            "max_candidates_per_iteration": 10,
            "beam_width": 5,
            "allowed_operations": ["MOVE_REACTION"],
            "policy_version": "test-v1",
        },
        calibration_selection_policy={
            "max_candidates_per_generation": 1,
            "max_modules_per_candidate": None,
            "score_threshold": None,
            "rank_threshold": None,
            "only_if_could_change_ordering": False,
            "total_calibration_run_budget": 10,
            "policy_version": "test-v1",
        },
        flat_orchestration_policy={
            "max_rounds": 1,
            "max_total_candidates": 100,
            "improvement_epsilon": "0",
            "require_human_review": False,
            "policy_version": "test-v1",
        },
        recursion_policy={
            "max_depth": 2,
            "min_reactions_per_module": 1,
            "max_total_hierarchy_nodes": 20,
            "max_total_functional_evaluation_budget": 0,
            "max_total_calibration_budget": 10,
            "min_improvement_to_accept_child": "0",
            "require_human_review": False,
            "policy_version": "test-v1",
        },
        input_artifact_references={},
    )


def _stub_repo(tmp_path, monkeypatch):
    repo_dir = tmp_path / "harness"
    (repo_dir / "scripts").mkdir(parents=True)
    (repo_dir / ".venv" / "bin").mkdir(parents=True)
    venv_python = repo_dir / ".venv" / "bin" / "python3"
    venv_python.write_text("")
    entrypoint = repo_dir / "scripts" / "run_workbench_hierarchical_request.py"
    entrypoint.write_text("")

    monkeypatch.setattr(hierarchical_harness_client, "HARNESS_REPO_DIR", repo_dir)
    monkeypatch.setattr(hierarchical_harness_client, "HARNESS_VENV_PYTHON", venv_python)
    monkeypatch.setattr(hierarchical_harness_client, "HARNESS_ENTRYPOINT", entrypoint)


def test_harness_is_available_reports_missing_repo(monkeypatch, tmp_path):
    monkeypatch.setattr(
        hierarchical_harness_client, "HARNESS_REPO_DIR", tmp_path / "does-not-exist"
    )
    error = hierarchical_harness_client.harness_is_available()
    assert error is not None
    assert error.code == "HARNESS_REPO_NOT_FOUND"


def test_invoke_reports_missing_repo_without_invoking_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(
        hierarchical_harness_client, "HARNESS_REPO_DIR", tmp_path / "does-not-exist"
    )

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called when the harness is unavailable")

    monkeypatch.setattr(hierarchical_harness_client.subprocess, "run", _fail_if_called)

    result, error = hierarchical_harness_client.invoke_hierarchical_harness(_request())
    assert result is None
    assert error.code == "HARNESS_REPO_NOT_FOUND"


def test_invoke_reports_timeout(monkeypatch, tmp_path):
    _stub_repo(tmp_path, monkeypatch)

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="run_workbench_hierarchical_request.py", timeout=1.0)

    monkeypatch.setattr(hierarchical_harness_client.subprocess, "run", _raise_timeout)

    result, error = hierarchical_harness_client.invoke_hierarchical_harness(_request())
    assert result is None
    assert error.code == "HARNESS_SUBPROCESS_TIMEOUT"


def test_invoke_reports_missing_output_file(monkeypatch, tmp_path):
    _stub_repo(tmp_path, monkeypatch)

    def _no_op_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(hierarchical_harness_client.subprocess, "run", _no_op_run)

    result, error = hierarchical_harness_client.invoke_hierarchical_harness(_request())
    assert result is None
    assert error.code == "HARNESS_OUTPUT_MISSING"


def test_invoke_reports_invalid_output_json(monkeypatch, tmp_path):
    _stub_repo(tmp_path, monkeypatch)

    def _write_garbage(*args, **kwargs):
        output_index = args[0].index("--output") + 1
        with open(args[0][output_index], "w") as f:
            f.write("not valid json")
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

    monkeypatch.setattr(hierarchical_harness_client.subprocess, "run", _write_garbage)

    result, error = hierarchical_harness_client.invoke_hierarchical_harness(_request())
    assert result is None
    assert error.code == "HARNESS_OUTPUT_INVALID"


def test_invoke_parses_a_valid_result(monkeypatch, tmp_path):
    _stub_repo(tmp_path, monkeypatch)

    valid_result = {
        "contract_version": CONTRACT_VERSION,
        "run_id": "test-run",
        "status": "SUCCEEDED",
        "root_model_id": "m1",
        "nodes": [],
        "total_nodes_created": 1,
        "total_functional_evaluations_used": 0,
        "total_calibration_runs_used": 0,
        "requires_user_review": False,
        "pending_review_modules": [],
        "recursion_policy_version": "hierarchical-recursion-v1",
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:00:05+00:00",
        "error": None,
        "summary": "ok",
        "warnings": [],
        "replayed": False,
    }

    def _write_valid_result(*args, **kwargs):
        output_index = args[0].index("--output") + 1
        with open(args[0][output_index], "w") as f:
            json.dump(valid_result, f)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(hierarchical_harness_client.subprocess, "run", _write_valid_result)

    result, error = hierarchical_harness_client.invoke_hierarchical_harness(_request())
    assert error is None
    assert result.run_id == "test-run"
    assert result.status.value == "SUCCEEDED"
