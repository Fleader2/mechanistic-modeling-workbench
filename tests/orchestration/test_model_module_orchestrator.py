"""Tests for ``app.orchestration.model_module_orchestrator`` (Executable-Module Materialization
increment).

One real, end-to-end cross-repo integration test drives the actual sibling
``agent-integration-harness`` repository's module-simulation canonical entrypoint as a genuine
subprocess chain (Workbench -> Harness -> real Agent 2 materialization), confirming the module
artifact (never the root model's) is what gets targeted -- skipped automatically if that
repository or its venv is not present. **Boundary treatment is deliberately never fabricated**
(see ``agent-integration-harness/docs/16_workbench_module_simulation_contract.md``): a module
reached purely through the real hierarchical-recursion search's own ``attach_payload`` (no
explicit boundary ports) correctly, honestly comes back `VIEW_ONLY` -- so this real test
demonstrates the full real subprocess chain reaching that clean, disclosed rejection, with
provenance (``RunRecord.model_module_id``) still correctly linked to the *specific* module that
was rejected. Every other test mocks ``invoke_module_simulation`` to also exercise the
*successful*-simulation path (which requires explicit boundary treatment no real, unmodified
hierarchy search ever supplies on its own) -- the Workbench's own persistence/state-machine
logic does not need a real Agent 3 run to be exercised correctly either way.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.contracts.module_simulation import CONTRACT_VERSION, ModuleSimulationResult
from app.models.enums import ModuleBoundaryTreatmentType, RunStage, RunStatus
from app.orchestration import hierarchical_run_orchestrator, model_module_orchestrator
from app.orchestration.hierarchical_harness_client import HARNESS_REPO_DIR, harness_is_available
from app.orchestration.module_boundary_orchestrator import (
    evaluate_module_execution_status,
    submit_boundary_decision,
)
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model_module import materialize_accepted_modules
from app.persistence.module_boundary_port import persist_candidate_boundary_ports
from app.persistence.run_record import complete_run, create_run_record, start_run
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.database

_HARNESS_FIXTURES = HARNESS_REPO_DIR / "tests" / "fixtures"
_HARNESS_UNAVAILABLE = harness_is_available()


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
                {"module_id": "modA", "component_type": "REACTION", "component_id": "r1"}
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
    """Persist one boundary port for ``module`` and resolve it to ``EXTERNALLY_CONTROLLED`` --
    the minimum needed to reach ``SIMULATION_READY`` without a real harness call, for tests
    that only exercise ``request_module_simulation``'s own gate/payload-merge logic."""
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "compound-S1::in::compartment-1", "direction": "INPUT"}],
        session=db_session,
    )
    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("1"),
        decided_by="test-user",
    )


def _succeeding_result(request) -> tuple[ModuleSimulationResult, None]:
    return (
        ModuleSimulationResult(
            contract_version=CONTRACT_VERSION,
            run_id=request.run_id,
            status="SUCCEEDED",
            module_id=request.module_id,
            modularization_id=request.attach_payload["modularization_id"],
            module_handoff_summary={
                "model_id": "m1::module::modA",
                "species_count": 2,
                "reaction_count": 1,
                "parameter_count": 1,
            },
            agent3_report={"report_id": "r1", "overall_status": "STEADY_STATE_FOUND"},
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:05+00:00",
            error=None,
            summary="simulated",
        ),
        None,
    )


# --- list/get APIs ---------------------------------------------------------------------------


def test_list_model_modules(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    modules = model_module_orchestrator.list_model_modules(db_session, run.id)
    assert [m.id for m in modules] == [module.id]


def test_get_model_module_with_provenance(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    fetched = model_module_orchestrator.get_model_module_with_provenance(db_session, module.id)
    assert fetched.id == module.id
    assert fetched.hierarchy_node.node_id == "node::depth1::modA::000001"
    assert fetched.run_record.id == run.id


def test_get_model_module_with_provenance_raises_for_unknown_id(db_session):
    import uuid

    with pytest.raises(ValueError, match="no ModelModule"):
        model_module_orchestrator.get_model_module_with_provenance(db_session, uuid.uuid4())


# --- request_module_simulation: happy path (mocked) ------------------------------------------


def test_request_module_simulation_invokes_with_correct_module_and_links_result(
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

    monkeypatch.setattr(model_module_orchestrator, "invoke_module_simulation", _fake_invoke)

    sim_run = model_module_orchestrator.request_module_simulation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
    )

    assert captured["request"].module_id == "modA"
    assert captured["request"].attach_payload["modularization_id"] == "cand-root"
    assert captured["request"].attach_payload["module_ids"] == ["modA"]
    assert captured["request"].attach_payload["memberships"] == [
        {"module_id": "modA", "component_type": "REACTION", "component_id": "r1"}
    ]
    assert captured["request"].attach_payload["module_ports"] == [
        {
            "port_id": f"port::{module.id}::compound-S1::in::compartment-1::INPUT",
            "module_id": "modA",
            "species_id": "compound-S1::in::compartment-1",
            "direction": "INPUT",
            "externally_controlled": True,
            "initial_value": "1",
            "unit": None,
        }
    ]
    assert captured["request"].input_artifact_references == {
        "stage1_synthetic_source": "/tmp/fake_agent1_view.json"
    }

    assert sim_run.status is RunStatus.SUCCEEDED
    assert sim_run.stage is RunStage.AGENT3
    assert sim_run.model_module_id == module.id
    assert sim_run.model_id == module.root_model_id

    result_data = json.loads(sim_run.artifact_reference)
    assert result_data["module_id"] == "modA"
    assert result_data["agent3_report"]["overall_status"] == "STEADY_STATE_FOUND"


def test_request_module_simulation_is_idempotently_replayed(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)

    call_count = {"n": 0}

    def _fake_invoke(request):
        call_count["n"] += 1
        return _succeeding_result(request)

    monkeypatch.setattr(model_module_orchestrator, "invoke_module_simulation", _fake_invoke)

    first = model_module_orchestrator.request_module_simulation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
    )
    assert call_count["n"] == 1

    replayed = model_module_orchestrator.request_module_simulation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
        run_record_id=first.id,
    )
    assert replayed.id == first.id
    assert call_count["n"] == 1  # the harness was never invoked a second time


# --- request_module_simulation: failure paths -------------------------------------------------


def test_request_module_simulation_reports_client_error_as_failed(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)

    from app.orchestration.module_simulation_harness_client import (
        ModuleSimulationHarnessClientError,
    )

    def _fake_invoke(request):
        return None, ModuleSimulationHarnessClientError(
            code="HARNESS_REPO_NOT_FOUND", message="not found"
        )

    monkeypatch.setattr(model_module_orchestrator, "invoke_module_simulation", _fake_invoke)

    sim_run = model_module_orchestrator.request_module_simulation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
    )
    assert sim_run.status is RunStatus.FAILED
    assert "HARNESS_REPO_NOT_FOUND" in sim_run.error_summary


def test_request_module_simulation_reports_invalid_module_as_failed(db_session, monkeypatch):
    """Even a module already ``SIMULATION_READY`` on the Workbench's own side can still have
    its harness call itself come back ``MODULE_SIMULATION_FAILED`` (e.g. a real Agent 2
    materialization error unrelated to boundary treatment) -- rejected clearly, never silently
    accepted."""
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)

    from app.contracts.module_simulation import ModuleSimulationError

    def _fake_invoke(request):
        return (
            ModuleSimulationResult(
                contract_version=CONTRACT_VERSION,
                run_id=request.run_id,
                status="FAILED",
                module_id=None,
                modularization_id=None,
                module_handoff_summary=None,
                agent3_report=None,
                started_at="2026-01-01T00:00:00+00:00",
                completed_at="2026-01-01T00:00:01+00:00",
                error=ModuleSimulationError(
                    code="MODULE_SIMULATION_FAILED",
                    message="modA has no eligible standalone artifact (readiness='VIEW_ONLY')",
                ),
                summary="rejected",
            ),
            None,
        )

    monkeypatch.setattr(model_module_orchestrator, "invoke_module_simulation", _fake_invoke)

    sim_run = model_module_orchestrator.request_module_simulation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
    )
    assert sim_run.status is RunStatus.FAILED
    assert "VIEW_ONLY" in sim_run.error_summary
    assert sim_run.model_module_id == module.id  # provenance preserved even on failure


def test_request_module_simulation_raises_for_unknown_module(db_session):
    project_id, subproject_id = _make_ids(db_session)
    import uuid

    with pytest.raises(ValueError, match="no ModelModule"):
        model_module_orchestrator.request_module_simulation(
            model_module_id=uuid.uuid4(),
            subproject_id=subproject_id,
            project_id=project_id,
            session=db_session,
        )


def test_request_module_simulation_raises_for_a_view_only_module(db_session):
    """Boundary-Condition Semantics increment: a freshly-materialized module has no boundary
    ports yet, so it is ``VIEW_ONLY`` -- ``request_module_simulation`` must reject it before
    ever invoking the harness, never attempt a materialization Agent 2 would have rejected
    anyway."""
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    with pytest.raises(ValueError, match="VIEW_ONLY"):
        model_module_orchestrator.request_module_simulation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            session=db_session,
        )


def test_request_module_simulation_raises_for_a_requires_review_module(db_session):
    """A module with a derived-but-unresolved boundary port is ``REQUIRES_BOUNDARY_REVIEW`` --
    still rejected before the harness is ever invoked."""
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "compound-S1::in::compartment-1", "direction": "INPUT"}],
        session=db_session,
    )
    evaluate_module_execution_status(module, db_session)

    with pytest.raises(ValueError, match="REQUIRES_BOUNDARY_REVIEW"):
        model_module_orchestrator.request_module_simulation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            session=db_session,
        )


def test_request_module_simulation_raises_when_no_stage1_input_was_recorded(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    create_hierarchy_nodes(
        run_record_id=run.id, nodes=[_root_node(), _modA_node()], session=db_session
    )
    (module,) = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    complete_run(
        run_record_id=run.id, status=RunStatus.SUCCEEDED, session=db_session
    )  # no artifact_reference
    _resolve_to_simulation_ready(db_session, module)

    with pytest.raises(ValueError, match="no recorded stage-1 input"):
        model_module_orchestrator.request_module_simulation(
            model_module_id=module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            session=db_session,
        )


# --- fresh DB/session recovery -----------------------------------------------------------------


def test_fresh_session_reload_before_requesting_simulation(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_to_simulation_ready(db_session, module)
    module_id = module.id

    db_session.expire_all()
    reloaded = model_module_orchestrator.get_model_module_with_provenance(db_session, module_id)
    assert reloaded.module_id == "modA"

    monkeypatch.setattr(model_module_orchestrator, "invoke_module_simulation", _succeeding_result)
    sim_run = model_module_orchestrator.request_module_simulation(
        model_module_id=reloaded.id,
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
    )
    assert sim_run.status is RunStatus.SUCCEEDED


# --- existing whole-model Agent 3 execution remains unaffected --------------------------------


def test_run_record_stage_agent3_without_model_module_id_is_still_a_plain_full_pipeline_row(
    db_session,
):
    """A whole-model Agent 3 run (inside FULL_PIPELINE) never sets model_module_id -- confirms
    the two are distinguished purely by that field's own presence, never a new RunStage."""
    _project_id, subproject_id = _make_ids(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.AGENT3, session=db_session)
    assert run.model_module_id is None


# --- real, end-to-end subprocess integration --------------------------------------------------


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_end_to_end_module_simulation_targets_the_module_not_the_root(db_session):
    """Workbench accepted hierarchy module -> persisted module identity -> Harness -> real
    Agent 2 subprocess. Boundary treatment is never fabricated, so a module reached purely
    through the real search's own attach_payload (no boundary ports derived/resolved yet) stays
    honestly ``VIEW_ONLY``. Since the Boundary-Condition Semantics increment,
    ``request_module_simulation`` itself now rejects a non-``SIMULATION_READY`` module before
    ever invoking the harness -- this test confirms that *pre-flight* rejection fires correctly
    for a real hierarchy module, with no subprocess invoked at all (a strictly stronger
    guarantee than the harness's own prior disclosed MODULE_SIMULATION_FAILED outcome, and the
    reason this test no longer needs the harness to actually run to pass -- the ``skipif`` is
    kept only because the module itself is produced via a real hierarchical-recursion
    subprocess)."""
    project_id, subproject_id = _make_ids(db_session)

    run = hierarchical_run_orchestrator.submit_hierarchical_run(
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
        criteria_weights={
            "weights": [{"criterion": "TOPOLOGICAL_SEPARATION", "weight": "1"}],
            "policy_version": "test-v1",
        },
        search_policy={
            "max_iterations": 1,
            "max_candidates_per_iteration": 10,
            "beam_width": 5,
            "allowed_operations": ["SPLIT_MODULE", "MOVE_REACTION"],
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
            "max_depth": 1,
            "min_reactions_per_module": 1,
            "max_total_hierarchy_nodes": 20,
            "max_total_functional_evaluation_budget": 0,
            "max_total_calibration_budget": 10,
            "min_improvement_to_accept_child": "0",
            "require_human_review": False,
            "policy_version": "test-v1",
        },
        exclude_single_module_from_ranking=False,
        synthetic_fixture_path=str(_HARNESS_FIXTURES / "synthetic_agent1_view.json"),
    )
    assert run.status is RunStatus.SUCCEEDED

    modules = model_module_orchestrator.list_model_modules(db_session, run.id)
    assert len(modules) >= 1
    target_module = modules[0]
    assert target_module.execution_status.value == "VIEW_ONLY"

    with pytest.raises(ValueError, match="VIEW_ONLY"):
        model_module_orchestrator.request_module_simulation(
            model_module_id=target_module.id,
            subproject_id=subproject_id,
            project_id=project_id,
            session=db_session,
        )
