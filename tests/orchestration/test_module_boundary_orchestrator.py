"""Tests for ``app.orchestration.module_boundary_orchestrator`` (Boundary-Condition Semantics
increment).

One real, end-to-end test drives the actual sibling ``agent-integration-harness`` repository's
module-boundary-derivation canonical entrypoint as a genuine subprocess chain (Workbench ->
Harness -> real Agent 2 topology scan) -- skipped automatically if that repository or its venv
is not present. Every other test mocks ``invoke_module_boundary_derivation`` to exercise the
Workbench's own persistence/execution-status logic without a real subprocess.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.contracts.module_boundary_derivation import (
    CONTRACT_VERSION,
    ModuleBoundaryDerivationResult,
)
from app.models.enums import (
    ModelModuleExecutionStatus,
    ModuleBoundaryTreatmentType,
    RunStage,
    RunStatus,
)
from app.orchestration import model_module_orchestrator, module_boundary_orchestrator
from app.orchestration.module_boundary_derivation_harness_client import HARNESS_REPO_DIR
from app.orchestration.module_boundary_derivation_harness_client import (
    harness_is_available as boundary_harness_is_available,
)
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model_module import materialize_accepted_modules
from app.persistence.module_boundary_port import list_boundary_ports_for_module
from app.persistence.run_record import complete_run, create_run_record, start_run
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.database

_HARNESS_FIXTURES = HARNESS_REPO_DIR / "tests" / "fixtures"
_HARNESS_UNAVAILABLE = boundary_harness_is_available()


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


def _derivation_result(request, candidates) -> tuple[ModuleBoundaryDerivationResult, None]:
    return (
        ModuleBoundaryDerivationResult(
            contract_version=CONTRACT_VERSION,
            run_id=request.run_id,
            status="SUCCEEDED",
            module_id=request.module_id,
            candidates=tuple(candidates),
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:01+00:00",
            error=None,
            summary=f"{len(candidates)} candidate boundary species found",
        ),
        None,
    )


# --- derive_boundary_ports: automatic boundary detection (mocked harness) --------------------


def test_derive_boundary_ports_creates_unresolved_rows_and_sets_requires_review(
    db_session, monkeypatch
):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )

    def _fake_invoke(request):
        return _derivation_result(
            request,
            [
                {"species_id": "compound-S1::in::compartment-1", "direction": "INPUT"},
                {"species_id": "compound-S2::in::compartment-1", "direction": "OUTPUT"},
            ],
        )

    monkeypatch.setattr(
        module_boundary_orchestrator, "invoke_module_boundary_derivation", _fake_invoke
    )

    created = module_boundary_orchestrator.derive_boundary_ports(
        model_module_id=module.id,
        project_id=project_id,
        subproject_id=subproject_id,
        session=db_session,
    )
    assert len(created) == 2
    assert all(c.treatment_type is ModuleBoundaryTreatmentType.UNRESOLVED for c in created)

    db_session.refresh(module)
    assert module.execution_status is ModelModuleExecutionStatus.REQUIRES_BOUNDARY_REVIEW


def test_derive_boundary_ports_with_zero_candidates_is_not_an_error(db_session, monkeypatch):
    """A module with no cross-boundary species is a genuine, successful result -- never raised
    as ``ModuleBoundaryDerivationError``. Its own execution status stays ``VIEW_ONLY`` (no
    ports exist to resolve)."""
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )

    monkeypatch.setattr(
        module_boundary_orchestrator,
        "invoke_module_boundary_derivation",
        lambda request: _derivation_result(request, []),
    )

    created = module_boundary_orchestrator.derive_boundary_ports(
        model_module_id=module.id,
        project_id=project_id,
        subproject_id=subproject_id,
        session=db_session,
    )
    assert created == []
    db_session.refresh(module)
    assert module.execution_status is ModelModuleExecutionStatus.VIEW_ONLY


def test_derive_boundary_ports_raises_on_harness_client_error(db_session, monkeypatch):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )

    from app.orchestration.module_boundary_derivation_harness_client import (
        ModuleBoundaryDerivationHarnessClientError,
    )

    monkeypatch.setattr(
        module_boundary_orchestrator,
        "invoke_module_boundary_derivation",
        lambda request: (
            None,
            ModuleBoundaryDerivationHarnessClientError(
                code="HARNESS_REPO_NOT_FOUND", message="not found"
            ),
        ),
    )

    with pytest.raises(module_boundary_orchestrator.ModuleBoundaryDerivationError):
        module_boundary_orchestrator.derive_boundary_ports(
            model_module_id=module.id,
            project_id=project_id,
            subproject_id=subproject_id,
            session=db_session,
        )


# --- re-derivation is idempotent and never overwrites a manual decision ----------------------


def test_re_derivation_does_not_duplicate_ports_or_overwrite_a_manual_decision(
    db_session, monkeypatch
):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    candidates = [{"species_id": "compound-S1::in::compartment-1", "direction": "INPUT"}]
    monkeypatch.setattr(
        module_boundary_orchestrator,
        "invoke_module_boundary_derivation",
        lambda request: _derivation_result(request, candidates),
    )

    (port,) = module_boundary_orchestrator.derive_boundary_ports(
        model_module_id=module.id,
        project_id=project_id,
        subproject_id=subproject_id,
        session=db_session,
    )
    module_boundary_orchestrator.submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("5"),
        decided_by="alice",
    )

    second = module_boundary_orchestrator.derive_boundary_ports(
        model_module_id=module.id,
        project_id=project_id,
        subproject_id=subproject_id,
        session=db_session,
    )
    assert second == []

    ports = list_boundary_ports_for_module(db_session, module.id)
    assert len(ports) == 1
    assert ports[0].treatment_type is ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED
    assert ports[0].initial_value == Decimal("5")

    db_session.refresh(module)
    assert module.execution_status is ModelModuleExecutionStatus.SIMULATION_READY


# --- submit_boundary_decision: treatment classes and status transitions ----------------------


def _one_port(
    db_session, module, *, species_id="compound-S1::in::compartment-1", direction="INPUT"
):
    from app.persistence.module_boundary_port import persist_candidate_boundary_ports

    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": species_id, "direction": direction}],
        session=db_session,
    )
    return port


def test_submit_boundary_decision_externally_controlled_makes_module_simulation_ready(
    db_session,
):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    port = _one_port(db_session, module)

    module_boundary_orchestrator.submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("2"),
        decided_by="bob",
    )
    db_session.refresh(module)
    assert module.execution_status is ModelModuleExecutionStatus.SIMULATION_READY


def test_submit_boundary_decision_prescribed_input_makes_module_simulation_ready(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    port = _one_port(db_session, module)

    module_boundary_orchestrator.submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.PRESCRIBED_INPUT,
        session=db_session,
        initial_value=Decimal("0.5"),
    )
    db_session.refresh(module)
    assert module.execution_status is ModelModuleExecutionStatus.SIMULATION_READY


def test_submit_boundary_decision_dynamic_coupling_keeps_module_non_standalone(db_session):
    """A dynamic-coupling port is genuinely resolved (``resolution_status=RESOLVED``) but is
    never standalone-capable -- the module stays ``REQUIRES_BOUNDARY_REVIEW``, never
    ``SIMULATION_READY``, satisfying the task's own "dynamic coupling remains non-standalone"
    requirement."""
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    port = _one_port(db_session, module)

    resolved = module_boundary_orchestrator.submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.DYNAMIC_COUPLING,
        session=db_session,
    )
    assert resolved.initial_value is None
    db_session.refresh(module)
    assert module.execution_status is ModelModuleExecutionStatus.REQUIRES_BOUNDARY_REVIEW


def test_module_status_transitions_view_only_to_review_to_ready(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    assert module.execution_status is ModelModuleExecutionStatus.VIEW_ONLY

    port = _one_port(db_session, module)
    module_boundary_orchestrator.evaluate_module_execution_status(module, db_session)
    assert module.execution_status is ModelModuleExecutionStatus.REQUIRES_BOUNDARY_REVIEW

    module_boundary_orchestrator.submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("1"),
    )
    assert module.execution_status is ModelModuleExecutionStatus.SIMULATION_READY


def test_a_mix_of_resolved_and_unresolved_ports_stays_requires_review(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    resolved_port = _one_port(db_session, module, species_id="compound-S1::in::compartment-1")
    _one_port(db_session, module, species_id="compound-S2::in::compartment-1")

    module_boundary_orchestrator.submit_boundary_decision(
        port_id=resolved_port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("1"),
    )
    assert module.execution_status is ModelModuleExecutionStatus.REQUIRES_BOUNDARY_REVIEW


# --- fresh DB/session reload -------------------------------------------------------------------


def test_fresh_session_reload_preserves_decision_and_execution_status(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    port = _one_port(db_session, module)
    module_boundary_orchestrator.submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("3"),
        decided_by="carol",
    )
    module_id, port_id = module.id, port.id

    db_session.expire_all()

    reloaded_module = model_module_orchestrator.get_model_module_with_provenance(
        db_session, module_id
    )
    assert reloaded_module.execution_status is ModelModuleExecutionStatus.SIMULATION_READY

    reloaded_port = module_boundary_orchestrator.get_boundary_port_with_provenance(
        db_session, port_id
    )
    assert reloaded_port.treatment_type is ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED
    assert reloaded_port.initial_value == Decimal("3")
    assert reloaded_port.decided_by == "carol"


# --- build_module_ports_payload ------------------------------------------------------------


def test_build_module_ports_payload_includes_only_standalone_capable_ports(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_run_with_module(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    controlled = _one_port(db_session, module, species_id="compound-S1::in::compartment-1")
    coupled = _one_port(db_session, module, species_id="compound-S2::in::compartment-1")

    module_boundary_orchestrator.submit_boundary_decision(
        port_id=controlled.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("1.5"),
        unit="mM",
    )
    module_boundary_orchestrator.submit_boundary_decision(
        port_id=coupled.id,
        treatment_type=ModuleBoundaryTreatmentType.DYNAMIC_COUPLING,
        session=db_session,
    )

    payload = module_boundary_orchestrator.build_module_ports_payload(module, db_session)
    assert len(payload) == 1
    assert payload[0]["species_id"] == "compound-S1::in::compartment-1"
    assert payload[0]["externally_controlled"] is True
    assert payload[0]["initial_value"] == "1.5"
    assert payload[0]["unit"] == "mM"


# --- real, end-to-end subprocess integration --------------------------------------------------


def _make_two_module_split_run(db_session, *, project_id, subproject_id):
    """A real, hand-split two-module attach_payload of the synthetic fixture's own three
    reactions (reaction-1, reaction-2 -> modA; reaction-3 -> modB) -- the identical fixture
    used throughout the harness's own module-simulation/boundary-derivation tests. S3 is
    produced inside modA by reaction-2 and consumed outside it by modB's own reaction-3 --
    the one real, structural boundary species this split produces."""
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
    return run, module


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_derive_boundary_ports_finds_the_correct_crossing_species(db_session):
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_two_module_split_run(
        db_session, project_id=project_id, subproject_id=subproject_id
    )

    created = module_boundary_orchestrator.derive_boundary_ports(
        model_module_id=module.id,
        project_id=project_id,
        subproject_id=subproject_id,
        session=db_session,
    )
    assert [(c.species_id, c.direction.value) for c in created] == [
        ("compound-S3::in::compartment-1", "OUTPUT")
    ]
    db_session.refresh(module)
    assert module.execution_status is ModelModuleExecutionStatus.REQUIRES_BOUNDARY_REVIEW


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_full_boundary_resolution_to_simulation_smoke(db_session, monkeypatch):
    """The one required full real smoke path (task instructions): hierarchy module ->
    persisted boundary ports (real harness derivation subprocess) -> user resolution
    (``submit_boundary_decision``, ``EXTERNALLY_CONTROLLED`` with an explicit value) ->
    ``SIMULATION_READY`` -> real Harness -> real Agent 2 module materialization (now carrying
    the resolved ``module_ports``) -> real Agent 3 simulation -- with a direct inspection of
    the materialized Antimony text (read from the harness's own on-disk artifact, the one
    place the resolved value is actually visible: Agent 3's own report never echoes a constant
    boundary species' value, since it is not part of the simulated ODE state) confirming the
    human-supplied value of 2.5 is exactly what Agent 2 declared for the resolved boundary
    species -- never a fabricated or default value.
    """
    project_id, subproject_id = _make_ids(db_session)
    _run, module = _make_two_module_split_run(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    assert module.execution_status is ModelModuleExecutionStatus.VIEW_ONLY

    (candidate,) = module_boundary_orchestrator.derive_boundary_ports(
        model_module_id=module.id,
        project_id=project_id,
        subproject_id=subproject_id,
        session=db_session,
    )
    assert candidate.species_id == "compound-S3::in::compartment-1"
    db_session.refresh(module)
    assert module.execution_status is ModelModuleExecutionStatus.REQUIRES_BOUNDARY_REVIEW

    module_boundary_orchestrator.submit_boundary_decision(
        port_id=candidate.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("2.5"),
        unit="mM",
        value_source="USER_SUPPLIED",
        decided_by="test-reviewer",
        notes="stands in for an observed extracellular concentration",
    )
    db_session.refresh(module)
    assert module.execution_status is ModelModuleExecutionStatus.SIMULATION_READY

    sim_run = model_module_orchestrator.request_module_simulation(
        model_module_id=module.id,
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
    )
    try:
        assert sim_run.status is RunStatus.SUCCEEDED, sim_run.error_summary
        result_data = json.loads(sim_run.artifact_reference)
        assert result_data["agent3_report"]["overall_status"] == "SUCCESS"
        # modA has 2 of the whole root model's 3 reactions/parameters -- confirms Agent 3
        # simulated the module's own scoped artifact, never the root's.
        summary = result_data["module_handoff_summary"]
        assert summary["reaction_count"] == 2
        assert summary["parameter_count"] == 2

        handoff_path = (
            HARNESS_REPO_DIR
            / "artifacts"
            / "runs"
            / str(sim_run.id)
            / f"module_simulation_handoff_{sim_run.id}.json"
        )
        handoff = json.loads(handoff_path.read_text())
        s3_symbol = handoff["antimony_symbol_map"]["species"]["compound-S3::in::compartment-1"]
        antimony_text = handoff["antimony_text"]
        assert f"const {s3_symbol};" in antimony_text
        assert f"{s3_symbol} = 2.5;" in antimony_text
    finally:
        import shutil

        run_dir = HARNESS_REPO_DIR / "artifacts" / "runs" / str(sim_run.id)
        if run_dir.is_dir():
            shutil.rmtree(run_dir)
