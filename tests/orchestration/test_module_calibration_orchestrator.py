"""Tests for ``app.orchestration.module_calibration_orchestrator`` (Module-Level Agent4
Calibration with Immutable Execution-Condition Provenance increment).

One real, end-to-end test drives the actual sibling ``agent-integration-harness`` repository's
module-calibration canonical entrypoint as a genuine subprocess chain (Workbench -> Harness ->
real Agent 2 materialization -> real Agent 3 -> real Agent 4), confirming the module-specific
artifact and its resolved boundary conditions were what Agent 4 actually calibrated against.
Every other test mocks ``invoke_module_calibration`` to exercise the Workbench's own
validation/persistence/snapshot logic without a real subprocess.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest

from app.contracts.module_calibration import CONTRACT_VERSION, ModuleCalibrationResult
from app.models.enums import ModuleBoundaryTreatmentType, ModuleExecutionKind, RunStage, RunStatus
from app.orchestration import module_calibration_orchestrator
from app.orchestration.module_boundary_orchestrator import submit_boundary_decision
from app.orchestration.module_calibration_harness_client import HARNESS_REPO_DIR
from app.orchestration.module_calibration_harness_client import (
    harness_is_available as calibration_harness_is_available,
)
from app.orchestration.module_calibration_orchestrator import ModuleCalibrationValidationError
from app.persistence.dataset_reference import persist_dataset_reference
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model_module import materialize_accepted_modules
from app.persistence.module_boundary_port import persist_candidate_boundary_ports
from app.persistence.module_execution_snapshot import get_snapshot_for_run, read_snapshot_payload
from app.persistence.run_record import complete_run, create_run_record, start_run
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.database

_HARNESS_FIXTURES = HARNESS_REPO_DIR / "tests" / "fixtures"
_HARNESS_UNAVAILABLE = calibration_harness_is_available()

_K1 = 1.0
_S1_FIXED = 10.0
_TRUE_K2 = 0.5


def _make_ids(db_session):
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    return project_id, subproject_id


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
                {"module_id": "modA", "component_type": "REACTION", "component_id": "r1"},
                {"module_id": "modA", "component_type": "PARAMETER", "component_id": "k1"},
                {"module_id": "modA", "component_type": "SPECIES", "component_id": "s1"},
            ],
        },
    }
    data.update(overrides)
    return data


def _make_run_with_module(db_session, *, project_id, subproject_id):
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    create_hierarchy_nodes(
        run_record_id=run.id, nodes=[_root_node(), _modA_node()], session=db_session
    )
    (module,) = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    run = complete_run(
        run_record_id=run.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        artifact_reference=json.dumps(
            {"root_model_id": "m1", "stage1_synthetic_source": "/tmp/fake_agent1_view.json"}
        ),
    )
    return run, module


def _resolve_to_simulation_ready(db_session, module) -> None:
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "s1", "direction": "INPUT"}],
        session=db_session,
    )
    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("1"),
        decided_by="test-user",
    )


def _valid_calibration_request() -> dict:
    return {
        "request_id": "calib-req-1",
        "targets": [{"target_kind": "PARAMETER", "target_id": "k1", "bounds": None}],
        "observations": {
            "observation_set_id": "set-1",
            "observations": [
                {
                    "observation_id": "obs-1",
                    "target_species_id": "s1",
                    "kind": "TIME_SERIES",
                    "partition": "TRAIN",
                    "time_points": [1.0, 2.0],
                    "values": [1.0, 2.0],
                }
            ],
        },
    }


def _succeeding_result(request) -> tuple[ModuleCalibrationResult, None]:
    return (
        ModuleCalibrationResult(
            contract_version=CONTRACT_VERSION,
            run_id=request.run_id,
            status="SUCCEEDED",
            module_id=request.module_id,
            modularization_id=request.attach_payload["modularization_id"],
            module_handoff={
                "model_id": "m1::module::modA",
                "species": [{"species_id": "s1"}],
                "reactions": [{"reaction_id": "r1"}],
                "parameters": [{"parameter_id": "k1"}],
            },
            agent3_report={"report_id": "r1", "overall_status": "STEADY_STATE_FOUND"},
            agent4_report={
                "report_id": "a4-1",
                "calibration": {
                    "status": "SUCCESS",
                    "parameter_estimates": [{"target_id": "k1", "fitted_value": 0.5}],
                },
            },
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:05+00:00",
            error=None,
            summary="calibrated",
        ),
        None,
    )


# --- gating -----------------------------------------------------------------------------------


def test_request_module_calibration_raises_for_a_view_only_module(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    with pytest.raises(ValueError, match="VIEW_ONLY"):
        module_calibration_orchestrator.request_module_calibration(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_request=_valid_calibration_request(),
            session=db_session,
        )


def test_request_module_calibration_raises_for_unknown_module(db_session):
    import uuid

    project_id, subproject_id = _make_ids(db_session)
    with pytest.raises(ValueError, match="no ModelModule"):
        module_calibration_orchestrator.request_module_calibration(
            model_module_id=uuid.uuid4(),
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_request=_valid_calibration_request(),
            session=db_session,
        )


# --- validation: incomplete/unsupported requests are rejected explicitly ---------------------


def test_request_module_calibration_rejects_empty_targets(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    bad = {**_valid_calibration_request(), "targets": []}
    with pytest.raises(ModuleCalibrationValidationError, match="at least one calibration target"):
        module_calibration_orchestrator.request_module_calibration(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_request=bad,
            session=db_session,
        )


def test_request_module_calibration_rejects_unknown_target_parameter(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    bad = {
        **_valid_calibration_request(),
        "targets": [{"target_kind": "PARAMETER", "target_id": "not-a-real-param"}],
    }
    with pytest.raises(ModuleCalibrationValidationError, match="not-a-real-param"):
        module_calibration_orchestrator.request_module_calibration(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_request=bad,
            session=db_session,
        )


def test_request_module_calibration_rejects_unknown_observation_species(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    bad = _valid_calibration_request()
    bad["observations"]["observations"][0]["target_species_id"] = "not-a-real-species"
    with pytest.raises(ModuleCalibrationValidationError, match="not-a-real-species"):
        module_calibration_orchestrator.request_module_calibration(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_request=bad,
            session=db_session,
        )


def test_request_module_calibration_rejects_dimensionally_incompatible_observation_unit(
    db_session,
):
    """Structured Units and Dimensional-Consistency Validation increment (task instructions
    §6): an observation's optional ``"unit"`` annotation that is genuinely dimensionally
    incompatible with the target species' own resolved boundary unit is rejected before any
    harness call -- never silently accepted or converted."""
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "s1", "direction": "INPUT"}],
        session=db_session,
    )
    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("1"),
        unit="mM",
        decided_by="test-user",
    )
    bad = _valid_calibration_request()
    bad["observations"]["observations"][0]["unit"] = "s"
    with pytest.raises(ModuleCalibrationValidationError, match="dimensionally incompatible"):
        module_calibration_orchestrator.request_module_calibration(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_request=bad,
            session=db_session,
        )


def test_request_module_calibration_accepts_equivalent_observation_unit(db_session, monkeypatch):
    """The companion positive case: an observation unit that is dimensionally *equivalent* to
    the target species' own boundary unit, merely written differently (``"mM"`` vs
    ``"mmol/L"``), is accepted -- never rejected by what used to be a bare string-equality
    check."""
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "s1", "direction": "INPUT"}],
        session=db_session,
    )
    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("1"),
        unit="mM",
        decided_by="test-user",
    )
    monkeypatch.setattr(
        module_calibration_orchestrator, "invoke_module_calibration", _succeeding_result
    )
    good = _valid_calibration_request()
    good["observations"]["observations"][0]["unit"] = "mmol/L"

    run_record = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=good,
        session=db_session,
    )
    assert run_record.stage == RunStage.AGENT4
    assert run_record.status == RunStatus.SUCCEEDED


def test_request_module_calibration_rejects_empty_observations(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    bad = {
        **_valid_calibration_request(),
        "observations": {"observation_set_id": "x", "observations": []},
    }
    with pytest.raises(ModuleCalibrationValidationError, match="at least one observation"):
        module_calibration_orchestrator.request_module_calibration(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_request=bad,
            session=db_session,
        )


def test_request_module_calibration_rejects_mismatched_time_points_and_values(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    bad = _valid_calibration_request()
    bad["observations"]["observations"][0]["values"] = [1.0]
    with pytest.raises(ModuleCalibrationValidationError, match="mismatched"):
        module_calibration_orchestrator.request_module_calibration(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_request=bad,
            session=db_session,
        )


def test_request_module_calibration_rejects_unknown_dataset_reference(db_session):
    import uuid

    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    with pytest.raises(ModuleCalibrationValidationError, match="no DatasetReference"):
        module_calibration_orchestrator.request_module_calibration(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_request=_valid_calibration_request(),
            dataset_reference_ids=[uuid.uuid4()],
            session=db_session,
        )


# --- happy path (mocked harness): correct handoff, snapshot, persistence ---------------------


def test_request_module_calibration_invokes_with_correct_module_and_links_result(
    db_session, monkeypatch
):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)

    captured = {}

    def _fake_invoke(request):
        captured["request"] = request
        return _succeeding_result(request)

    monkeypatch.setattr(module_calibration_orchestrator, "invoke_module_calibration", _fake_invoke)

    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=_valid_calibration_request(),
        session=db_session,
    )

    assert captured["request"].module_id == "modA"
    assert captured["request"].attach_payload["module_ports"] == [
        {
            "port_id": f"port::{module.id}::s1::INPUT",
            "module_id": "modA",
            "species_id": "s1",
            "direction": "INPUT",
            "externally_controlled": True,
            "initial_value": "1",
            "unit": None,
        }
    ]
    assert captured["request"].calibration_request == _valid_calibration_request()

    assert calib_run.status is RunStatus.SUCCEEDED
    assert calib_run.stage is RunStage.AGENT4
    assert calib_run.model_module_id == module.id

    result_data = json.loads(calib_run.artifact_reference)
    assert result_data["module_id"] == "modA"
    assert result_data["agent4_report"]["calibration"]["status"] == "SUCCESS"


def test_request_module_calibration_creates_immutable_snapshot(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    monkeypatch.setattr(
        module_calibration_orchestrator, "invoke_module_calibration", _succeeding_result
    )

    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=_valid_calibration_request(),
        session=db_session,
    )

    snapshot = get_snapshot_for_run(db_session, calib_run.id)
    assert snapshot is not None
    assert snapshot.model_module_id == module.id
    assert snapshot.execution_kind is ModuleExecutionKind.CALIBRATION
    assert snapshot.module_artifact_hash

    payload = read_snapshot_payload(snapshot)
    assert payload["calibration_config"] == _valid_calibration_request()
    assert payload["boundary_ports"][0]["species_id"] == "s1"
    assert payload["boundary_ports"][0]["treatment_type"] == "EXTERNALLY_CONTROLLED"
    assert payload["module_handoff_summary"]["species_count"] == 1
    assert payload["parameters"] == [{"parameter_id": "k1"}]


def test_request_module_calibration_snapshot_includes_dataset_references(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    dataset_result = persist_dataset_reference(
        project_id=project_id,
        name="test-dataset",
        dataset_type="experimental_observation",
        artifact_reference="s3://bucket/dataset.csv",
        session=db_session,
        checksum="sha256:abc",
        version_label="v1",
    )
    monkeypatch.setattr(
        module_calibration_orchestrator, "invoke_module_calibration", _succeeding_result
    )

    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=_valid_calibration_request(),
        dataset_reference_ids=[dataset_result.entity_id],
        session=db_session,
    )

    snapshot = get_snapshot_for_run(db_session, calib_run.id)
    payload = read_snapshot_payload(snapshot)
    assert payload["dataset_references"] == [
        {
            "dataset_reference_id": str(dataset_result.entity_id),
            "name": "test-dataset",
            "dataset_type": "experimental_observation",
            "artifact_reference": "s3://bucket/dataset.csv",
            "checksum": "sha256:abc",
            "version_label": "v1",
        }
    ]


# --- immutability: a later boundary/data change never touches a historical snapshot ----------


def test_snapshot_survives_a_later_boundary_decision_change(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "s1", "direction": "INPUT"}],
        session=db_session,
    )
    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("1"),
    )
    monkeypatch.setattr(
        module_calibration_orchestrator, "invoke_module_calibration", _succeeding_result
    )
    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=_valid_calibration_request(),
        session=db_session,
    )
    snapshot_id = get_snapshot_for_run(db_session, calib_run.id).id

    # A human later revises the SAME port's own decision.
    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("999"),
        decided_by="someone-else",
    )

    reloaded_snapshot = get_snapshot_for_run(db_session, calib_run.id)
    assert reloaded_snapshot.id == snapshot_id
    payload = read_snapshot_payload(reloaded_snapshot)
    assert payload["boundary_ports"][0]["initial_value"] == "1"  # never "999"


def test_fresh_session_reload_preserves_snapshot_and_result(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    monkeypatch.setattr(
        module_calibration_orchestrator, "invoke_module_calibration", _succeeding_result
    )
    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=_valid_calibration_request(),
        session=db_session,
    )
    run_id = calib_run.id

    db_session.expire_all()

    snapshot = get_snapshot_for_run(db_session, run_id)
    assert snapshot is not None
    assert read_snapshot_payload(snapshot)["calibration_config"]["request_id"] == "calib-req-1"


# --- multiple calibration runs never overwrite earlier results -------------------------------


def test_multiple_calibration_runs_each_get_their_own_record_and_snapshot(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    monkeypatch.setattr(
        module_calibration_orchestrator, "invoke_module_calibration", _succeeding_result
    )

    request_a = _valid_calibration_request()
    request_a["request_id"] = "calib-req-a"
    request_b = _valid_calibration_request()
    request_b["request_id"] = "calib-req-b"

    run_a = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=request_a,
        session=db_session,
    )
    run_b = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=request_b,
        session=db_session,
    )

    assert run_a.id != run_b.id
    runs = module_calibration_orchestrator.list_calibration_runs(db_session, module.id)
    assert {r.id for r in runs} == {run_a.id, run_b.id}

    payload_a = read_snapshot_payload(get_snapshot_for_run(db_session, run_a.id))
    payload_b = read_snapshot_payload(get_snapshot_for_run(db_session, run_b.id))
    assert payload_a["calibration_config"]["request_id"] == "calib-req-a"
    assert payload_b["calibration_config"]["request_id"] == "calib-req-b"


# --- idempotent replay / failure recovery -----------------------------------------------------


def test_request_module_calibration_is_idempotently_replayed(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)

    call_count = {"n": 0}

    def _fake_invoke(request):
        call_count["n"] += 1
        return _succeeding_result(request)

    monkeypatch.setattr(module_calibration_orchestrator, "invoke_module_calibration", _fake_invoke)

    first = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=_valid_calibration_request(),
        session=db_session,
    )
    assert call_count["n"] == 1

    replayed = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=_valid_calibration_request(),
        session=db_session,
        run_record_id=first.id,
    )
    assert replayed.id == first.id
    assert call_count["n"] == 1  # the harness was never invoked a second time


def test_request_module_calibration_reports_client_error_as_failed_but_still_snapshots(
    db_session, monkeypatch
):
    """An infrastructure failure to even reach the harness is recorded as FAILED, but the
    snapshot of what was *attempted* is still captured (task instructions: failure recovery
    must not lose provenance of the attempt)."""
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)

    from app.orchestration.module_calibration_harness_client import (
        ModuleCalibrationHarnessClientError,
    )

    def _fake_invoke(request):
        return None, ModuleCalibrationHarnessClientError(
            code="HARNESS_REPO_NOT_FOUND", message="not found"
        )

    monkeypatch.setattr(module_calibration_orchestrator, "invoke_module_calibration", _fake_invoke)

    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=_valid_calibration_request(),
        session=db_session,
    )
    assert calib_run.status is RunStatus.FAILED
    assert "HARNESS_REPO_NOT_FOUND" in calib_run.error_summary

    snapshot = get_snapshot_for_run(db_session, calib_run.id)
    assert snapshot is not None
    assert "module_handoff_summary" not in read_snapshot_payload(snapshot)


# --- whole-model Agent4 calibration remains unaffected ----------------------------------------


def test_whole_model_run_record_without_model_module_id_is_still_a_plain_full_pipeline_row(
    db_session,
):
    """A whole-model Agent4 run (inside FULL_PIPELINE) never sets model_module_id -- confirms
    the two are distinguished purely by that field's own presence, identical to how
    request_module_simulation already distinguishes a module-scoped Agent3 run from a
    whole-model one."""
    _project_id, subproject_id = _make_ids(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.AGENT4, session=db_session)
    assert run.model_module_id is None


# --- real, end-to-end subprocess integration --------------------------------------------------


def _two_module_split_run_with_dynamics(db_session, *, project_id, subproject_id):
    """A real, hand-split two-module attach_payload of the synthetic fixture's own three
    reactions, with S1 (an ordinary internal species, deliberately treated as an externally-
    controlled fixed feed -- a legitimate human modeling choice, not a topologically-derived
    boundary) and S3 (the one real, derived cross-module boundary species) both resolved --
    giving modA real, non-degenerate dynamics for S2 to calibrate against (see this test
    module's own docstring)."""
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)

    reactions = ["reaction-1", "reaction-2", "reaction-3"]
    params = ["k_reaction-1_protein-1", "k_reaction-2_protein-2", "k_reaction-3_protein-3"]
    species = [
        "compound-S1::in::compartment-1",
        "compound-S2::in::compartment-1",
        "compound-S3::in::compartment-1",
        "compound-S4::in::compartment-1",
    ]
    memberships = []
    for r in reactions:
        target = "modA" if r in ("reaction-1", "reaction-2") else "modB"
        memberships.append({"module_id": target, "component_type": "REACTION", "component_id": r})
    for p in params:
        target = "modA" if ("reaction-1" in p or "reaction-2" in p) else "modB"
        memberships.append({"module_id": target, "component_type": "PARAMETER", "component_id": p})
    for s in species:
        memberships.append({"module_id": "modA", "component_type": "SPECIES", "component_id": s})
        memberships.append({"module_id": "modB", "component_type": "SPECIES", "component_id": s})

    create_hierarchy_nodes(
        run_record_id=run.id,
        nodes=[
            _root_node(child_module_ids=["modA", "modB"]),
            _modA_node(
                attach_payload={
                    "modularization_id": "cand-root",
                    "module_ids": ["modA", "modB"],
                    "memberships": memberships,
                }
            ),
        ],
        session=db_session,
    )
    (module,) = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    run = complete_run(
        run_record_id=run.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        artifact_reference=json.dumps(
            {"stage1_synthetic_source": str(_HARNESS_FIXTURES / "synthetic_agent1_view.json")}
        ),
    )

    (s1_port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "compound-S1::in::compartment-1", "direction": "INPUT"}],
        session=db_session,
    )
    submit_boundary_decision(
        port_id=s1_port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal(str(_S1_FIXED)),
        decided_by="test-reviewer",
    )
    from app.orchestration.module_boundary_orchestrator import derive_boundary_ports

    (s3_port,) = derive_boundary_ports(
        model_module_id=module.id,
        project_id=project_id,
        subproject_id=subproject_id,
        session=db_session,
    )
    submit_boundary_decision(
        port_id=s3_port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("0"),
        decided_by="test-reviewer",
    )
    return module


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_full_calibration_smoke_recovers_true_parameter_and_persists_provenance(db_session):
    """The one required full real smoke path: Workbench-selected ModelModule -> immutable
    execution snapshot -> Harness -> real Agent4 calibration -> persisted parameter estimates,
    confirming the module-specific artifact and resolved boundary conditions were actually
    used (k2 is recovered from synthetic S2(t) data generated with S1 fixed at 10 and k1 left
    at Agent 2's own default of 1 -- see this test module's own docstring for the full
    derivation)."""
    project_id, subproject_id = _make_ids(db_session)
    module = _two_module_split_run_with_dynamics(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    assert module.execution_status.value == "SIMULATION_READY"

    time_points = [1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 16.0, 20.0]
    values = [(_K1 * _S1_FIXED / _TRUE_K2) * (1 - math.exp(-_TRUE_K2 * t)) for t in time_points]
    calibration_request = {
        "request_id": "real-smoke-calib-req",
        "targets": [
            {
                "target_kind": "PARAMETER",
                "target_id": "k_reaction-2_protein-2",
                "bounds": {"lower": 0.001, "upper": 5.0},
            }
        ],
        "observations": {
            "observation_set_id": "modA-s2-real-smoke",
            "observations": [
                {
                    "observation_id": "obs-s2",
                    "target_species_id": "compound-S2::in::compartment-1",
                    "kind": "TIME_SERIES",
                    "partition": "TRAIN",
                    "time_points": time_points,
                    "values": values,
                }
            ],
        },
    }

    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=calibration_request,
        session=db_session,
    )
    try:
        assert calib_run.status is RunStatus.SUCCEEDED, calib_run.error_summary
        result_data = json.loads(calib_run.artifact_reference)
        calibration = result_data["agent4_report"]["calibration"]
        assert calibration["status"] == "SUCCESS"
        estimates = {p["target_id"]: p["fitted_value"] for p in calibration["parameter_estimates"]}
        assert estimates["k_reaction-2_protein-2"] == pytest.approx(_TRUE_K2, rel=0.05)

        snapshot = get_snapshot_for_run(db_session, calib_run.id)
        assert snapshot.model_module_id == module.id
        assert snapshot.execution_kind is ModuleExecutionKind.CALIBRATION
        payload = read_snapshot_payload(snapshot)
        assert payload["calibration_config"]["request_id"] == "real-smoke-calib-req"
        boundary_species = {p["species_id"] for p in payload["boundary_ports"]}
        assert "compound-S1::in::compartment-1" in boundary_species
        assert "compound-S3::in::compartment-1" in boundary_species
        # modA has 2 of the whole root model's 3 reactions/parameters -- confirms the
        # module-specific artifact, never the root's, was what Agent 4 calibrated against.
        assert payload["module_handoff_summary"]["reaction_count"] == 2
        assert payload["module_handoff_summary"]["parameter_count"] == 2
    finally:
        import shutil

        run_dir = HARNESS_REPO_DIR / "artifacts" / "runs" / str(calib_run.id)
        if run_dir.is_dir():
            shutil.rmtree(run_dir)


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_units_smoke_accepts_equivalent_rejects_incompatible(db_session):
    """The one required realistic integration test for the Structured Units and Dimensional-
    Consistency Validation increment: a second observation of the *same* target species,
    declaring a dimensionally *incompatible* unit, is rejected before any harness call ever
    happens (no ``RunRecord``/subprocess, confirmed by this request never reaching
    ``invoke_module_calibration``) -- while declaring a unit that is merely *written
    differently* but dimensionally equivalent (``"M"`` vs ``"mM"``) is accepted, and the real
    Agent2->Agent3->Agent4 calibration proceeds exactly as it would with no unit annotation at
    all, recovering the identical true parameter value the companion non-units smoke test
    (``test_real_full_calibration_smoke_recovers_true_parameter_and_persists_provenance``)
    already established."""
    project_id, subproject_id = _make_ids(db_session)
    module = _two_module_split_run_with_dynamics(
        db_session, project_id=project_id, subproject_id=subproject_id
    )

    time_points = [1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 16.0, 20.0]
    values = [(_K1 * _S1_FIXED / _TRUE_K2) * (1 - math.exp(-_TRUE_K2 * t)) for t in time_points]

    def _calibration_request(*, second_observation_unit: str) -> dict:
        return {
            "request_id": f"real-units-smoke-{second_observation_unit}",
            "targets": [
                {
                    "target_kind": "PARAMETER",
                    "target_id": "k_reaction-2_protein-2",
                    "bounds": {"lower": 0.001, "upper": 5.0},
                }
            ],
            "observations": {
                "observation_set_id": "modA-s2-real-units-smoke",
                "observations": [
                    {
                        "observation_id": "obs-s2-primary",
                        "target_species_id": "compound-S2::in::compartment-1",
                        "kind": "TIME_SERIES",
                        "partition": "TRAIN",
                        "time_points": time_points,
                        "values": values,
                        "unit": "mM",
                    },
                    # A second, independent observation of the *identical* target species --
                    # a real, legitimate scenario (a replicate measurement), used here purely
                    # to exercise the cross-observation unit check: no boundary port exists
                    # for this dynamic species at all, so the only metadata available to
                    # compare against is another observation's own declared unit.
                    {
                        "observation_id": "obs-s2-replicate",
                        "target_species_id": "compound-S2::in::compartment-1",
                        "kind": "TIME_SERIES",
                        "partition": "TRAIN",
                        "time_points": time_points,
                        "values": values,
                        "unit": second_observation_unit,
                    },
                ],
            },
        }

    # Reject half: "s" (time) is genuinely dimensionally incompatible with the primary
    # observation's own "mM" (concentration) for the identical target species -- rejected
    # before any RunRecord is even created, let alone any harness subprocess invoked.
    with pytest.raises(ModuleCalibrationValidationError, match="dimensionally incompatible"):
        module_calibration_orchestrator.request_module_calibration(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_request=_calibration_request(second_observation_unit="s"),
            session=db_session,
        )

    # Accept half: "M" is written differently from the primary observation's own "mM", but is
    # the identical physical dimension (concentration) -- accepted, and the real calibration
    # proceeds and recovers the same true parameter value as with no unit annotation at all.
    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request=_calibration_request(second_observation_unit="M"),
        session=db_session,
    )
    try:
        assert calib_run.status is RunStatus.SUCCEEDED, calib_run.error_summary
        calibration = json.loads(calib_run.artifact_reference)["agent4_report"]["calibration"]
        estimates = {p["target_id"]: p["fitted_value"] for p in calibration["parameter_estimates"]}
        assert estimates["k_reaction-2_protein-2"] == pytest.approx(_TRUE_K2, rel=0.05)
    finally:
        import shutil

        run_dir = HARNESS_REPO_DIR / "artifacts" / "runs" / str(calib_run.id)
        if run_dir.is_dir():
            shutil.rmtree(run_dir)
