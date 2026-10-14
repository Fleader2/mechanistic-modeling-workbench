"""Tests for ``app.orchestration.harness_client``.

Every failure path here is exercised via ``monkeypatch`` against
``subprocess.run`` or the module's own repo-location constants, so these
tests run fast and never depend on the sibling harness repository actually
being present -- the one real subprocess invocation lives in
``tests/orchestration/test_run_orchestrator.py``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from app.contracts.harness import CONTRACT_VERSION, SUPPORTED_ENTRY_STAGE, HarnessInvocationRequest
from app.orchestration import harness_client

pytestmark = pytest.mark.unit


def _request(run_id: str = "test-run") -> HarnessInvocationRequest:
    return HarnessInvocationRequest(
        contract_version=CONTRACT_VERSION,
        run_id=run_id,
        project_id="proj-1",
        subproject_id="sub-1",
        task_type="BUILD_MODEL",
        requested_entry_stage=SUPPORTED_ENTRY_STAGE,
        input_artifact_references={},
    )


def test_harness_is_available_reports_missing_repo(monkeypatch, tmp_path):
    monkeypatch.setattr(harness_client, "HARNESS_REPO_DIR", tmp_path / "does-not-exist")
    error = harness_client.harness_is_available()
    assert error is not None
    assert error.code == "HARNESS_REPO_NOT_FOUND"


def test_invoke_harness_reports_missing_repo_without_invoking_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(harness_client, "HARNESS_REPO_DIR", tmp_path / "does-not-exist")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called when the harness is unavailable")

    monkeypatch.setattr(harness_client.subprocess, "run", _fail_if_called)

    result, error = harness_client.invoke_harness(_request())
    assert result is None
    assert error.code == "HARNESS_REPO_NOT_FOUND"


def test_invoke_harness_reports_timeout(monkeypatch, tmp_path):
    repo_dir = tmp_path / "harness"
    (repo_dir / "scripts").mkdir(parents=True)
    (repo_dir / ".venv" / "bin").mkdir(parents=True)
    venv_python = repo_dir / ".venv" / "bin" / "python3"
    venv_python.write_text("")
    entrypoint = repo_dir / "scripts" / "run_workbench_request.py"
    entrypoint.write_text("")

    monkeypatch.setattr(harness_client, "HARNESS_REPO_DIR", repo_dir)
    monkeypatch.setattr(harness_client, "HARNESS_VENV_PYTHON", venv_python)
    monkeypatch.setattr(harness_client, "HARNESS_ENTRYPOINT", entrypoint)

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="run_workbench_request.py", timeout=1.0)

    monkeypatch.setattr(harness_client.subprocess, "run", _raise_timeout)

    result, error = harness_client.invoke_harness(_request())
    assert result is None
    assert error.code == "HARNESS_SUBPROCESS_TIMEOUT"


def test_invoke_harness_reports_missing_output_file(monkeypatch, tmp_path):
    repo_dir = tmp_path / "harness"
    (repo_dir / "scripts").mkdir(parents=True)
    (repo_dir / ".venv" / "bin").mkdir(parents=True)
    venv_python = repo_dir / ".venv" / "bin" / "python3"
    venv_python.write_text("")
    entrypoint = repo_dir / "scripts" / "run_workbench_request.py"
    entrypoint.write_text("")

    monkeypatch.setattr(harness_client, "HARNESS_REPO_DIR", repo_dir)
    monkeypatch.setattr(harness_client, "HARNESS_VENV_PYTHON", venv_python)
    monkeypatch.setattr(harness_client, "HARNESS_ENTRYPOINT", entrypoint)

    def _no_op_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(harness_client.subprocess, "run", _no_op_run)

    result, error = harness_client.invoke_harness(_request())
    assert result is None
    assert error.code == "HARNESS_OUTPUT_MISSING"


def test_invoke_harness_reports_invalid_output_json(monkeypatch, tmp_path):
    repo_dir = tmp_path / "harness"
    (repo_dir / "scripts").mkdir(parents=True)
    (repo_dir / ".venv" / "bin").mkdir(parents=True)
    venv_python = repo_dir / ".venv" / "bin" / "python3"
    venv_python.write_text("")
    entrypoint = repo_dir / "scripts" / "run_workbench_request.py"
    entrypoint.write_text("")

    monkeypatch.setattr(harness_client, "HARNESS_REPO_DIR", repo_dir)
    monkeypatch.setattr(harness_client, "HARNESS_VENV_PYTHON", venv_python)
    monkeypatch.setattr(harness_client, "HARNESS_ENTRYPOINT", entrypoint)

    def _write_garbage(*args, **kwargs):
        output_index = args[0].index("--output") + 1
        with open(args[0][output_index], "w") as f:
            f.write("not valid json")
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

    monkeypatch.setattr(harness_client.subprocess, "run", _write_garbage)

    result, error = harness_client.invoke_harness(_request())
    assert result is None
    assert error.code == "HARNESS_OUTPUT_INVALID"


def test_invoke_harness_parses_a_valid_result(monkeypatch, tmp_path):
    repo_dir = tmp_path / "harness"
    (repo_dir / "scripts").mkdir(parents=True)
    (repo_dir / ".venv" / "bin").mkdir(parents=True)
    venv_python = repo_dir / ".venv" / "bin" / "python3"
    venv_python.write_text("")
    entrypoint = repo_dir / "scripts" / "run_workbench_request.py"
    entrypoint.write_text("")

    monkeypatch.setattr(harness_client, "HARNESS_REPO_DIR", repo_dir)
    monkeypatch.setattr(harness_client, "HARNESS_VENV_PYTHON", venv_python)
    monkeypatch.setattr(harness_client, "HARNESS_ENTRYPOINT", entrypoint)

    valid_result = {
        "contract_version": CONTRACT_VERSION,
        "run_id": "test-run",
        "status": "SUCCEEDED",
        "stages_executed": ["agent1_curation"],
        "output_artifact_references": {"agent1_curation": "/tmp/stage1.json"},
        "model_artifact_reference": None,
        "agent_contract_versions": {"agent1_curation": "1.5"},
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

    monkeypatch.setattr(harness_client.subprocess, "run", _write_valid_result)

    result, error = harness_client.invoke_harness(_request())
    assert error is None
    assert result.run_id == "test-run"
    assert result.status.value == "SUCCEEDED"
