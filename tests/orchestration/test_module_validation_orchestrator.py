"""Tests for ``app.orchestration.module_validation_orchestrator`` (Module-Level Agent5
Validation and Experimental Design increment).

One real, end-to-end test drives the actual sibling ``agent-integration-harness`` repository's
module-validation canonical entrypoint as a genuine subprocess chain (Workbench -> Harness ->
real Agent 2 materialization -> real Agent 5), continuing directly from a real Agent2->Agent3
->Agent4 calibration (via ``module_calibration_orchestrator.request_module_calibration``
itself, not a hand-crafted stand-in) -- confirming Agent 5 actually used the correct
module-specific calibrated parameter and independent observations. Every other test mocks
``invoke_module_validation`` to exercise the Workbench's own validation/persistence/snapshot
logic without a real subprocess.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest

from app.contracts.module_validation import CONTRACT_VERSION, ModuleValidationResult
from app.models.enums import ModuleBoundaryTreatmentType, ModuleExecutionKind, RunStage, RunStatus
from app.orchestration import module_calibration_orchestrator, module_validation_orchestrator
from app.orchestration.module_boundary_orchestrator import submit_boundary_decision
from app.orchestration.module_validation_harness_client import HARNESS_REPO_DIR
from app.orchestration.module_validation_harness_client import (
    harness_is_available as validation_harness_is_available,
)
from app.orchestration.module_validation_orchestrator import ModuleValidationValidationError
from app.persistence.dataset_reference import persist_dataset_reference
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model_module import materialize_accepted_modules
from app.persistence.module_boundary_port import (
    list_boundary_ports_for_module,
    persist_candidate_boundary_ports,
)
from app.persistence.module_execution_snapshot import get_snapshot_for_run, read_snapshot_payload
from app.persistence.run_record import complete_run, create_run_record, start_run
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.database

_HARNESS_FIXTURES = HARNESS_REPO_DIR / "tests" / "fixtures"
_HARNESS_UNAVAILABLE = validation_harness_is_available()

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


_AGENT4_REPORT = {
    "report_id": "a4-1",
    "calibration": {
        "status": "SUCCESS",
        "parameter_estimates": [{"target_id": "k1", "fitted_value": 0.5}],
    },
}


def _make_succeeded_calibration_run(
    db_session, module, *, project_id, subproject_id, boundary_initial_value="1"
):
    """A hand-built, already-SUCCEEDED Agent4 ``RunRecord`` standing in for a real
    ``request_module_calibration`` call -- paired with a real ``ModuleExecutionSnapshot``
    (``execution_kind=CALIBRATION``) carrying the pinned ``attach_payload``/
    ``module_ports_payload`` fields that increment now requires, so that
    ``request_module_validation``'s own default pinned-reconstruction path has real snapshot
    data to read back, exactly as a genuine calibration run would leave behind."""
    from app.orchestration.module_boundary_orchestrator import build_module_ports_payload
    from app.persistence.model_module import build_attach_payload
    from app.persistence.module_execution_snapshot import (
        compute_module_artifact_hash,
        create_snapshot,
    )

    run_record = create_run_record(
        subproject_id=subproject_id,
        stage=RunStage.AGENT4,
        session=db_session,
        model_id=module.root_model_id,
    )
    run_record.model_module_id = module.id
    db_session.flush()
    start_run(run_record_id=run_record.id, session=db_session)

    attach_payload = build_attach_payload(module)
    module_ports_payload = build_module_ports_payload(module, db_session)
    for port in module_ports_payload:
        port["initial_value"] = boundary_initial_value
    attach_payload["module_ports"] = module_ports_payload
    module_artifact_hash = compute_module_artifact_hash(
        {"attach_payload": attach_payload, "module_ports": module_ports_payload}
    )
    create_snapshot(
        model_module_id=module.id,
        run_record_id=run_record.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        module_artifact_hash=module_artifact_hash,
        snapshot_payload={
            "boundary_ports": [
                {
                    "port_id": p["port_id"],
                    "species_id": p["species_id"],
                    "direction": p["direction"],
                    "treatment_type": "EXTERNALLY_CONTROLLED",
                    "resolution_status": "RESOLVED",
                    "initial_value": p["initial_value"],
                    "unit": p["unit"],
                    "value_source": None,
                    "decided_by": "test-user",
                    "decided_at": None,
                }
                for p in module_ports_payload
            ],
            "calibration_config": {},
            "dataset_references": None,
            "contract_versions": {},
            "attach_payload": attach_payload,
            "module_ports_payload": module_ports_payload,
        },
        session=db_session,
    )

    return complete_run(
        run_record_id=run_record.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        artifact_reference=json.dumps(
            {
                "module_id": "modA",
                "modularization_id": "cand-root",
                "agent4_report": _AGENT4_REPORT,
            }
        ),
    )


def _valid_validation_request() -> dict:
    return {
        "request_id": "val-req-1",
        "validation_observations": {
            "observation_set_id": "set-1",
            "observations": [
                {
                    "observation_id": "obs-1",
                    "target_species_id": "s1",
                    "kind": "TIME_SERIES",
                    "time_points": [1.0, 2.0],
                    "values": [1.0, 2.0],
                }
            ],
        },
    }


def _succeeding_result(request) -> tuple[ModuleValidationResult, None]:
    return (
        ModuleValidationResult(
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
            agent5_report={
                "report_id": "a5-1",
                "overall_status": "SUCCESS",
                "calibrated_parameter_ids_checked": ["k1"],
                "validation": {"validation_run_id": "vr-1", "simulated": True},
            },
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:05+00:00",
            error=None,
            summary="validated",
        ),
        None,
    )


# --- gating -----------------------------------------------------------------------------------


def test_request_module_validation_raises_for_a_view_only_module(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )
    with pytest.raises(ValueError, match="VIEW_ONLY"):
        module_validation_orchestrator.request_module_validation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=calib_run.id,
            validation_request=_valid_validation_request(),
            session=db_session,
        )


def test_request_module_validation_raises_for_unknown_module(db_session):
    import uuid

    project_id, subproject_id = _make_ids(db_session)
    with pytest.raises(ValueError, match="no ModelModule"):
        module_validation_orchestrator.request_module_validation(
            model_module_id=uuid.uuid4(),
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=uuid.uuid4(),
            validation_request=_valid_validation_request(),
            session=db_session,
        )


def test_request_module_validation_raises_for_missing_calibration_run(db_session):
    import uuid

    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    with pytest.raises(ValueError, match="not a SUCCEEDED Agent4"):
        module_validation_orchestrator.request_module_validation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=uuid.uuid4(),
            validation_request=_valid_validation_request(),
            session=db_session,
        )


def test_request_module_validation_raises_for_calibration_run_of_a_different_module(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run_a, module_a = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _run_b, module_b = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module_a)
    calib_run_for_b = _make_succeeded_calibration_run(
        db_session, module_b, project_id=project_id, subproject_id=subproject_id
    )
    with pytest.raises(ValueError, match="not a SUCCEEDED Agent4"):
        module_validation_orchestrator.request_module_validation(
            model_module_id=module_a.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=calib_run_for_b.id,
            validation_request=_valid_validation_request(),
            session=db_session,
        )


def test_request_module_validation_raises_for_failed_calibration_run(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    run_record = create_run_record(
        subproject_id=subproject_id,
        stage=RunStage.AGENT4,
        session=db_session,
        model_id=module.root_model_id,
    )
    run_record.model_module_id = module.id
    db_session.flush()
    start_run(run_record_id=run_record.id, session=db_session)
    failed_run = complete_run(
        run_record_id=run_record.id,
        status=RunStatus.FAILED,
        session=db_session,
        error_summary="calibration failed",
    )
    with pytest.raises(ValueError, match="not a SUCCEEDED Agent4"):
        module_validation_orchestrator.request_module_validation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=failed_run.id,
            validation_request=_valid_validation_request(),
            session=db_session,
        )


# --- validation: incomplete/unsupported requests are rejected explicitly ---------------------


def test_request_module_validation_rejects_empty_observations(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )
    bad = {
        **_valid_validation_request(),
        "validation_observations": {"observation_set_id": "x", "observations": []},
    }
    with pytest.raises(ModuleValidationValidationError, match="at least one independent"):
        module_validation_orchestrator.request_module_validation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=calib_run.id,
            validation_request=bad,
            session=db_session,
        )


def test_request_module_validation_rejects_unknown_observation_species(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )
    bad = _valid_validation_request()
    bad["validation_observations"]["observations"][0]["target_species_id"] = "not-a-real-species"
    with pytest.raises(ModuleValidationValidationError, match="not-a-real-species"):
        module_validation_orchestrator.request_module_validation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=calib_run.id,
            validation_request=bad,
            session=db_session,
        )


def test_request_module_validation_rejects_mismatched_time_points_and_values(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )
    bad = _valid_validation_request()
    bad["validation_observations"]["observations"][0]["values"] = [1.0]
    with pytest.raises(ModuleValidationValidationError, match="mismatched"):
        module_validation_orchestrator.request_module_validation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=calib_run.id,
            validation_request=bad,
            session=db_session,
        )


def test_request_module_validation_rejects_unknown_dataset_reference(db_session):
    import uuid

    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )
    with pytest.raises(ModuleValidationValidationError, match="no DatasetReference"):
        module_validation_orchestrator.request_module_validation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=calib_run.id,
            validation_request=_valid_validation_request(),
            dataset_reference_ids=[uuid.uuid4()],
            session=db_session,
        )


def test_request_module_validation_rejects_a_dataset_already_used_for_calibration(
    db_session, monkeypatch
):
    """Task instructions §2: validation data must be independent of calibration data -- a
    dataset reference already recorded as calibration input for this module is rejected."""
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    dataset_result = persist_dataset_reference(
        project_id=project_id,
        name="shared-dataset",
        dataset_type="experimental_observation",
        artifact_reference="s3://bucket/shared.csv",
        session=db_session,
    )
    monkeypatch.setattr(
        module_calibration_orchestrator,
        "invoke_module_calibration",
        lambda request: _make_calibration_mock_result(request),
    )
    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request={
            "request_id": "calib-shared",
            "targets": [{"target_kind": "PARAMETER", "target_id": "k1", "bounds": None}],
            "observations": {
                "observation_set_id": "s",
                "observations": [
                    {
                        "observation_id": "o",
                        "target_species_id": "s1",
                        "kind": "TIME_SERIES",
                        "partition": "TRAIN",
                        "time_points": [1.0],
                        "values": [1.0],
                    }
                ],
            },
        },
        dataset_reference_ids=[dataset_result.entity_id],
        session=db_session,
    )
    assert calib_run.status is RunStatus.SUCCEEDED

    with pytest.raises(ModuleValidationValidationError, match="already used as calibration input"):
        module_validation_orchestrator.request_module_validation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=calib_run.id,
            validation_request=_valid_validation_request(),
            dataset_reference_ids=[dataset_result.entity_id],
            session=db_session,
        )


def _make_calibration_mock_result(request):
    from app.contracts.module_calibration import CONTRACT_VERSION as CALIB_CONTRACT_VERSION
    from app.contracts.module_calibration import ModuleCalibrationResult

    return (
        ModuleCalibrationResult(
            contract_version=CALIB_CONTRACT_VERSION,
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
            agent3_report={"report_id": "r1"},
            agent4_report=_AGENT4_REPORT,
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:05+00:00",
            error=None,
            summary="calibrated",
        ),
        None,
    )


# --- happy path (mocked harness): correct handoff, snapshot, persistence ---------------------


def test_request_module_validation_invokes_with_correct_module_and_links_result(
    db_session, monkeypatch
):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )

    captured = {}

    def _fake_invoke(request):
        captured["request"] = request
        return _succeeding_result(request)

    monkeypatch.setattr(module_validation_orchestrator, "invoke_module_validation", _fake_invoke)

    val_run = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=_valid_validation_request(),
        session=db_session,
    )

    assert captured["request"].module_id == "modA"
    assert captured["request"].agent4_report == _AGENT4_REPORT
    assert captured["request"].validation_request == _valid_validation_request()

    assert val_run.status is RunStatus.SUCCEEDED
    assert val_run.stage is RunStage.AGENT5
    assert val_run.model_module_id == module.id

    result_data = json.loads(val_run.artifact_reference)
    assert result_data["module_id"] == "modA"
    assert result_data["calibration_run_record_id"] == str(calib_run.id)
    assert result_data["agent5_report"]["overall_status"] == "SUCCESS"


def test_request_module_validation_creates_immutable_snapshot(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )
    monkeypatch.setattr(
        module_validation_orchestrator, "invoke_module_validation", _succeeding_result
    )

    val_run = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=_valid_validation_request(),
        session=db_session,
    )

    snapshot = get_snapshot_for_run(db_session, val_run.id)
    assert snapshot is not None
    assert snapshot.model_module_id == module.id
    assert snapshot.execution_kind is ModuleExecutionKind.VALIDATION

    payload = read_snapshot_payload(snapshot)
    assert payload["calibration_run_record_id"] == str(calib_run.id)
    assert payload["calibrated_parameters"] == [{"target_id": "k1", "fitted_value": 0.5}]
    assert payload["validation_config"] == _valid_validation_request()
    assert payload["boundary_ports"][0]["species_id"] == "s1"
    assert payload["module_handoff_summary"]["species_count"] == 1

    calibration_snapshot = get_snapshot_for_run(db_session, calib_run.id)
    assert payload["pinned_to_calibration_snapshot"] is True
    assert payload["calibration_snapshot_id"] == str(calibration_snapshot.id)
    assert payload["pinned_module_artifact_hash"] == calibration_snapshot.module_artifact_hash
    assert snapshot.module_artifact_hash == calibration_snapshot.module_artifact_hash


# --- Boundary-Condition Pinning increment: pinned reconstruction -----------------------------


def test_validation_uses_pinned_boundary_value_not_current_module_state(db_session, monkeypatch):
    """Task instructions §1/§2/§6: calibration ran under boundary value A; the module's own
    boundary decision is then changed to B; a validation request for that calibration must
    still be sent to the harness with A, never the module's current B."""
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
        decided_by="test-user",
    )
    calib_run = _make_succeeded_calibration_run(
        db_session,
        module,
        project_id=project_id,
        subproject_id=subproject_id,
        boundary_initial_value="1",
    )

    # The module's own boundary decision is revised AFTER calibration -- B, not A.
    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("999"),
        decided_by="someone-else",
    )

    captured = {}

    def _fake_invoke(request):
        captured["request"] = request
        return _succeeding_result(request)

    monkeypatch.setattr(module_validation_orchestrator, "invoke_module_validation", _fake_invoke)

    module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=_valid_validation_request(),
        session=db_session,
    )

    (sent_port,) = captured["request"].attach_payload["module_ports"]
    assert sent_port["initial_value"] == "1"  # the calibration-time value A, never "999"


def test_validation_with_pinning_disabled_uses_current_module_state(db_session, monkeypatch):
    """The ``pin_to_calibration_snapshot=False`` escape hatch (task instructions: "unless an
    explicit future workflow intentionally requests otherwise") -- the unchanged-current-state
    case must still work, and the resulting snapshot discloses that pinning was not used."""
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
        decided_by="test-user",
    )
    calib_run = _make_succeeded_calibration_run(
        db_session,
        module,
        project_id=project_id,
        subproject_id=subproject_id,
        boundary_initial_value="1",
    )
    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("999"),
        decided_by="someone-else",
    )

    captured = {}

    def _fake_invoke(request):
        captured["request"] = request
        return _succeeding_result(request)

    monkeypatch.setattr(module_validation_orchestrator, "invoke_module_validation", _fake_invoke)

    val_run = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=_valid_validation_request(),
        session=db_session,
        pin_to_calibration_snapshot=False,
    )

    (sent_port,) = captured["request"].attach_payload["module_ports"]
    assert sent_port["initial_value"] == "999"  # the module's own current state, not pinned

    payload = read_snapshot_payload(get_snapshot_for_run(db_session, val_run.id))
    assert payload["pinned_to_calibration_snapshot"] is False
    assert payload["pinned_module_artifact_hash"] is None
    assert payload["calibration_snapshot_id"] is None


def test_request_module_validation_rejects_calibration_run_with_no_snapshot(db_session):
    """Task instructions §5: missing calibration snapshot data must fail clearly, never
    silently fall back to the module's current state."""
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    run_record = create_run_record(
        subproject_id=subproject_id,
        stage=RunStage.AGENT4,
        session=db_session,
        model_id=module.root_model_id,
    )
    run_record.model_module_id = module.id
    db_session.flush()
    start_run(run_record_id=run_record.id, session=db_session)
    calib_run_no_snapshot = complete_run(
        run_record_id=run_record.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        artifact_reference=json.dumps(
            {"module_id": "modA", "modularization_id": "cand-root", "agent4_report": _AGENT4_REPORT}
        ),
    )

    with pytest.raises(ModuleValidationValidationError, match="has no ModuleExecutionSnapshot"):
        module_validation_orchestrator.request_module_validation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=calib_run_no_snapshot.id,
            validation_request=_valid_validation_request(),
            session=db_session,
        )


def test_request_module_validation_rejects_calibration_snapshot_missing_pinned_fields(
    db_session,
):
    """A calibration snapshot predating this increment's own additive ``attach_payload``/
    ``module_ports_payload`` fields (simulated here directly) must also fail clearly."""
    from app.persistence.module_execution_snapshot import (
        compute_module_artifact_hash,
        create_snapshot,
    )

    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    run_record = create_run_record(
        subproject_id=subproject_id,
        stage=RunStage.AGENT4,
        session=db_session,
        model_id=module.root_model_id,
    )
    run_record.model_module_id = module.id
    db_session.flush()
    start_run(run_record_id=run_record.id, session=db_session)
    create_snapshot(
        model_module_id=module.id,
        run_record_id=run_record.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        module_artifact_hash=compute_module_artifact_hash({"legacy": True}),
        snapshot_payload={
            "boundary_ports": [],
            "calibration_config": {},
            "dataset_references": None,
        },
        session=db_session,
    )
    legacy_calib_run = complete_run(
        run_record_id=run_record.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        artifact_reference=json.dumps(
            {"module_id": "modA", "modularization_id": "cand-root", "agent4_report": _AGENT4_REPORT}
        ),
    )

    with pytest.raises(
        ModuleValidationValidationError, match="does not carry a pinned attach_payload"
    ):
        module_validation_orchestrator.request_module_validation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            calibration_run_record_id=legacy_calib_run.id,
            validation_request=_valid_validation_request(),
            session=db_session,
        )


def test_pinned_validation_fresh_session_reload_preserves_pinned_behavior(db_session, monkeypatch):
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
    calib_run = _make_succeeded_calibration_run(
        db_session,
        module,
        project_id=project_id,
        subproject_id=subproject_id,
        boundary_initial_value="1",
    )
    monkeypatch.setattr(
        module_validation_orchestrator, "invoke_module_validation", _succeeding_result
    )
    val_run = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=_valid_validation_request(),
        session=db_session,
    )
    run_id = val_run.id
    calibration_snapshot_id = get_snapshot_for_run(db_session, calib_run.id).id

    db_session.expire_all()

    reloaded_payload = read_snapshot_payload(get_snapshot_for_run(db_session, run_id))
    assert reloaded_payload["pinned_to_calibration_snapshot"] is True
    assert reloaded_payload["calibration_snapshot_id"] == str(calibration_snapshot_id)
    assert reloaded_payload["boundary_ports"][0]["initial_value"] == "1"


# --- immutability: a later boundary/calibration change never touches a historical snapshot ---


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
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )
    monkeypatch.setattr(
        module_validation_orchestrator, "invoke_module_validation", _succeeding_result
    )
    val_run = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=_valid_validation_request(),
        session=db_session,
    )
    snapshot_id = get_snapshot_for_run(db_session, val_run.id).id

    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("999"),
        decided_by="someone-else",
    )

    reloaded_snapshot = get_snapshot_for_run(db_session, val_run.id)
    assert reloaded_snapshot.id == snapshot_id
    payload = read_snapshot_payload(reloaded_snapshot)
    assert payload["boundary_ports"][0]["initial_value"] == "1"  # never "999"


def test_fresh_session_reload_preserves_snapshot_and_result(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )
    monkeypatch.setattr(
        module_validation_orchestrator, "invoke_module_validation", _succeeding_result
    )
    val_run = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=_valid_validation_request(),
        session=db_session,
    )
    run_id = val_run.id

    db_session.expire_all()

    snapshot = get_snapshot_for_run(db_session, run_id)
    assert snapshot is not None
    assert read_snapshot_payload(snapshot)["validation_config"]["request_id"] == "val-req-1"


# --- multiple validation runs never overwrite earlier results --------------------------------


def test_multiple_validation_runs_each_get_their_own_record_and_snapshot(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )
    monkeypatch.setattr(
        module_validation_orchestrator, "invoke_module_validation", _succeeding_result
    )

    request_a = _valid_validation_request()
    request_a["request_id"] = "val-req-a"
    request_b = _valid_validation_request()
    request_b["request_id"] = "val-req-b"

    run_a = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=request_a,
        session=db_session,
    )
    run_b = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=request_b,
        session=db_session,
    )

    assert run_a.id != run_b.id
    runs = module_validation_orchestrator.list_validation_runs(db_session, module.id)
    assert {r.id for r in runs} == {run_a.id, run_b.id}

    payload_a = read_snapshot_payload(get_snapshot_for_run(db_session, run_a.id))
    payload_b = read_snapshot_payload(get_snapshot_for_run(db_session, run_b.id))
    assert payload_a["validation_config"]["request_id"] == "val-req-a"
    assert payload_b["validation_config"]["request_id"] == "val-req-b"


# --- idempotent replay / failure recovery -----------------------------------------------------


def test_request_module_validation_is_idempotently_replayed(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )

    call_count = {"n": 0}

    def _fake_invoke(request):
        call_count["n"] += 1
        return _succeeding_result(request)

    monkeypatch.setattr(module_validation_orchestrator, "invoke_module_validation", _fake_invoke)

    first = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=_valid_validation_request(),
        session=db_session,
    )
    assert call_count["n"] == 1

    replayed = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=_valid_validation_request(),
        session=db_session,
        run_record_id=first.id,
    )
    assert replayed.id == first.id
    assert call_count["n"] == 1  # the harness was never invoked a second time


def test_request_module_validation_reports_client_error_as_failed_but_still_snapshots(
    db_session, monkeypatch
):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    calib_run = _make_succeeded_calibration_run(
        db_session, module, project_id=project_id, subproject_id=subproject_id
    )

    from app.orchestration.module_validation_harness_client import (
        ModuleValidationHarnessClientError,
    )

    def _fake_invoke(request):
        return None, ModuleValidationHarnessClientError(
            code="HARNESS_REPO_NOT_FOUND", message="not found"
        )

    monkeypatch.setattr(module_validation_orchestrator, "invoke_module_validation", _fake_invoke)

    val_run = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request=_valid_validation_request(),
        session=db_session,
    )
    assert val_run.status is RunStatus.FAILED
    assert "HARNESS_REPO_NOT_FOUND" in val_run.error_summary

    snapshot = get_snapshot_for_run(db_session, val_run.id)
    assert snapshot is not None
    assert "module_handoff_summary" not in read_snapshot_payload(snapshot)


# --- whole-model / Agent3/4 module execution remain unaffected --------------------------------


def test_whole_model_run_record_without_model_module_id_is_still_a_plain_full_pipeline_row(
    db_session,
):
    _project_id, subproject_id = _make_ids(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.AGENT5, session=db_session)
    assert run.model_module_id is None


# --- real, end-to-end subprocess integration --------------------------------------------------


def _two_module_split_run_with_dynamics(db_session, *, project_id, subproject_id):
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
    complete_run(
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
def test_real_full_validation_smoke_uses_correct_calibrated_parameter_and_independent_data(
    db_session,
):
    """The one required full real smoke path: Workbench -> calibrated ModelModule -> immutable
    validation snapshot -> Harness -> real Agent5 subprocess -> persisted validation results
    and experimental-design recommendations, verifying that Agent 5 actually used the correct
    module-specific calibrated parameter and independent observations."""
    project_id, subproject_id = _make_ids(db_session)
    module = _two_module_split_run_with_dynamics(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    assert module.execution_status.value == "SIMULATION_READY"

    train_t = [1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 16.0, 20.0]
    train_v = [(_K1 * _S1_FIXED / _TRUE_K2) * (1 - math.exp(-_TRUE_K2 * t)) for t in train_t]
    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request={
            "request_id": "real-smoke-calib-req",
            "targets": [
                {
                    "target_kind": "PARAMETER",
                    "target_id": "k_reaction-2_protein-2",
                    "bounds": {"lower": 0.001, "upper": 5.0},
                }
            ],
            "observations": {
                "observation_set_id": "modA-s2-train",
                "observations": [
                    {
                        "observation_id": "obs-train",
                        "target_species_id": "compound-S2::in::compartment-1",
                        "kind": "TIME_SERIES",
                        "partition": "TRAIN",
                        "time_points": train_t,
                        "values": train_v,
                    }
                ],
            },
        },
        session=db_session,
    )
    assert calib_run.status is RunStatus.SUCCEEDED, calib_run.error_summary

    val_t = [3.0, 10.0, 18.0]
    val_v = [(_K1 * _S1_FIXED / _TRUE_K2) * (1 - math.exp(-_TRUE_K2 * t)) for t in val_t]
    val_run = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request={
            "request_id": "real-smoke-val-req",
            "validation_observations": {
                "observation_set_id": "modA-s2-held-out",
                "observations": [
                    {
                        "observation_id": "obs-val",
                        "target_species_id": "compound-S2::in::compartment-1",
                        "kind": "TIME_SERIES",
                        "time_points": val_t,
                        "values": val_v,
                    }
                ],
            },
        },
        session=db_session,
    )
    try:
        assert val_run.status is RunStatus.SUCCEEDED, val_run.error_summary
        result_data = json.loads(val_run.artifact_reference)
        agent5_report = result_data["agent5_report"]
        assert agent5_report["overall_status"] == "SUCCESS"
        assert "k_reaction-2_protein-2" in agent5_report["calibrated_parameter_ids_checked"]
        (residual_summary,) = agent5_report["validation"]["validation_residuals"]
        assert residual_summary["sum_squared_residual"] < 0.01

        snapshot = get_snapshot_for_run(db_session, val_run.id)
        assert snapshot.execution_kind is ModuleExecutionKind.VALIDATION
        payload = read_snapshot_payload(snapshot)
        assert payload["calibration_run_record_id"] == str(calib_run.id)
        fitted = {p["target_id"]: p["fitted_value"] for p in payload["calibrated_parameters"]}
        assert fitted["k_reaction-2_protein-2"] == pytest.approx(_TRUE_K2, rel=0.05)
        assert payload["module_handoff_summary"]["reaction_count"] == 2
    finally:
        import shutil

        for run_id in (calib_run.id, val_run.id):
            run_dir = HARNESS_REPO_DIR / "artifacts" / "runs" / str(run_id)
            if run_dir.is_dir():
                shutil.rmtree(run_dir)


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_pinning_smoke_validation_still_uses_calibration_time_boundary_value(db_session):
    """The one required real subprocess test for this increment: calibrate module with
    boundary value A -> change the persisted module boundary to B -> validate the selected
    calibration -> the materialized Antimony text Agent 5 actually receives still declares A,
    never B (task instructions: real subprocess integration test).

    Reads the harness's own on-disk materialized handoff artifact directly (the only place the
    actually-used boundary value is visible as a real Antimony ``const`` declaration -- the
    Workbench's own persisted snapshot/result never echo the raw Antimony text, only summaries/
    structured arrays), exactly mirroring the technique the Boundary-Condition Semantics
    increment's own original real smoke test already established.
    """
    project_id, subproject_id = _make_ids(db_session)
    module = _two_module_split_run_with_dynamics(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    assert module.execution_status.value == "SIMULATION_READY"

    (s1_port,) = [
        p
        for p in list_boundary_ports_for_module(db_session, module.id)
        if p.species_id == "compound-S1::in::compartment-1"
    ]
    assert s1_port.initial_value == Decimal(str(_S1_FIXED))  # boundary value A, set at setup

    train_t = [1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 16.0, 20.0]
    train_v = [(_K1 * _S1_FIXED / _TRUE_K2) * (1 - math.exp(-_TRUE_K2 * t)) for t in train_t]
    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request={
            "request_id": "real-pinning-calib-req",
            "targets": [
                {
                    "target_kind": "PARAMETER",
                    "target_id": "k_reaction-2_protein-2",
                    "bounds": {"lower": 0.001, "upper": 5.0},
                }
            ],
            "observations": {
                "observation_set_id": "modA-s2-train",
                "observations": [
                    {
                        "observation_id": "obs-train",
                        "target_species_id": "compound-S2::in::compartment-1",
                        "kind": "TIME_SERIES",
                        "partition": "TRAIN",
                        "time_points": train_t,
                        "values": train_v,
                    }
                ],
            },
        },
        session=db_session,
    )
    assert calib_run.status is RunStatus.SUCCEEDED, calib_run.error_summary

    # The module's own persisted boundary is changed to B *after* calibration.
    _BOUNDARY_B = "777"
    submit_boundary_decision(
        port_id=s1_port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal(_BOUNDARY_B),
        decided_by="someone-else",
    )
    db_session.refresh(module)
    assert module.execution_status.value == "SIMULATION_READY"  # still ready, just a new value

    val_t = [3.0, 10.0, 18.0]
    val_v = [(_K1 * _S1_FIXED / _TRUE_K2) * (1 - math.exp(-_TRUE_K2 * t)) for t in val_t]
    val_run = module_validation_orchestrator.request_module_validation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_run_record_id=calib_run.id,
        validation_request={
            "request_id": "real-pinning-val-req",
            "validation_observations": {
                "observation_set_id": "modA-s2-held-out",
                "observations": [
                    {
                        "observation_id": "obs-val",
                        "target_species_id": "compound-S2::in::compartment-1",
                        "kind": "TIME_SERIES",
                        "time_points": val_t,
                        "values": val_v,
                    }
                ],
            },
        },
        session=db_session,
    )
    try:
        assert val_run.status is RunStatus.SUCCEEDED, val_run.error_summary

        # Provenance: the validation snapshot references the calibration run and its own
        # snapshot, and its own pinned hash matches the calibration's recorded hash exactly.
        calibration_snapshot = get_snapshot_for_run(db_session, calib_run.id)
        validation_snapshot = get_snapshot_for_run(db_session, val_run.id)
        validation_payload = read_snapshot_payload(validation_snapshot)
        assert validation_payload["pinned_to_calibration_snapshot"] is True
        assert validation_payload["calibration_run_record_id"] == str(calib_run.id)
        assert validation_payload["calibration_snapshot_id"] == str(calibration_snapshot.id)
        assert validation_payload["pinned_module_artifact_hash"] == (
            calibration_snapshot.module_artifact_hash
        )
        assert validation_snapshot.module_artifact_hash == calibration_snapshot.module_artifact_hash

        # The real proof: read the harness's own on-disk materialized handoff directly, and
        # confirm the Antimony text Agent 5 actually received still declares A, never B.
        handoff_path = (
            HARNESS_REPO_DIR
            / "artifacts"
            / "runs"
            / str(val_run.id)
            / f"module_simulation_handoff_{val_run.id}.json"
        )
        handoff = json.loads(handoff_path.read_text())
        s1_symbol = handoff["antimony_symbol_map"]["species"]["compound-S1::in::compartment-1"]
        antimony_text = handoff["antimony_text"]
        assert f"const {s1_symbol};" in antimony_text
        assert f"{s1_symbol} = {int(_S1_FIXED)};" in antimony_text  # A (10), pinned
        assert f"{s1_symbol} = {_BOUNDARY_B};" not in antimony_text  # never B (777)
    finally:
        import shutil

        for run_id in (calib_run.id, val_run.id):
            run_dir = HARNESS_REPO_DIR / "artifacts" / "runs" / str(run_id)
            if run_dir.is_dir():
                shutil.rmtree(run_dir)
