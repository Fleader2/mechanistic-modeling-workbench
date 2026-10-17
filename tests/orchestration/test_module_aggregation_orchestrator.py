"""Tests for ``app.orchestration.module_aggregation_orchestrator`` (Hierarchical Aggregation
of Module-Level Agent3/4/5 Results increment).

One realistic, end-to-end test drives two real, independently-executed module-level results
(a real Agent2->Agent3->Agent4 calibration of one sibling module, a real Agent2->Agent3
simulation of the other) through the sibling ``agent-integration-harness`` repository, then
builds aggregates purely in-process (no agent/harness call of its own -- aggregation belongs
entirely to the Workbench, task instructions §8), verifying every reported summary item is
traceable to its real source ``RunRecord``/``ModuleExecutionSnapshot``. Every other test uses
hand-built ``RunRecord``s to exercise the aggregation logic itself without a real subprocess.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest

from app.models.enums import (
    ModuleAggregateCompleteness,
    ModuleBoundaryTreatmentType,
    ModuleExecutionKind,
    RunStage,
    RunStatus,
)
from app.orchestration import (
    model_module_orchestrator,
    module_aggregation_orchestrator,
    module_calibration_orchestrator,
)
from app.orchestration.module_boundary_orchestrator import (
    derive_boundary_ports,
    submit_boundary_decision,
)
from app.orchestration.module_calibration_harness_client import HARNESS_REPO_DIR
from app.orchestration.module_calibration_harness_client import (
    harness_is_available as calibration_harness_is_available,
)
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model_module import materialize_accepted_modules
from app.persistence.module_boundary_port import persist_candidate_boundary_ports
from app.persistence.run_record import complete_run, create_run_record, start_run
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.database

_HARNESS_FIXTURES = HARNESS_REPO_DIR / "tests" / "fixtures"
_HARNESS_UNAVAILABLE = calibration_harness_is_available()


def _make_ids(db_session):
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    return project_id, subproject_id


# --- hierarchy-building helpers ---------------------------------------------------------------


def _root_node(**overrides) -> dict:
    data = {
        "node_id": "node::depth0::root::000000",
        "depth": 0,
        "parent_modularization_id": None,
        "parent_module_id": None,
        "child_submodel_id": "m1",
        "child_modularization_id": "cand-root",
        "child_module_ids": ["modA", "modB"],
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


def _leaf_node(
    *, node_id, parent_module_id, parent_modularization_id="cand-root", **overrides
) -> dict:
    data = {
        "node_id": node_id,
        "depth": 1,
        "parent_modularization_id": parent_modularization_id,
        "parent_module_id": parent_module_id,
        "child_submodel_id": f"m1::submodel::{parent_module_id}",
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
            "modularization_id": parent_modularization_id,
            "module_ids": [parent_module_id],
            "memberships": [
                {
                    "module_id": parent_module_id,
                    "component_type": "REACTION",
                    "component_id": f"r-{parent_module_id}",
                }
            ],
        },
    }
    data.update(overrides)
    return data


def _make_two_sibling_modules(db_session, *, project_id, subproject_id):
    """root -> modA, modB (both depth=1 leaves, siblings)."""
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    create_hierarchy_nodes(
        run_record_id=run.id,
        nodes=[
            _root_node(),
            _leaf_node(node_id="node::depth1::modA::000001", parent_module_id="modA"),
            _leaf_node(node_id="node::depth1::modB::000002", parent_module_id="modB"),
        ],
        session=db_session,
    )
    modA, modB = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    run = complete_run(
        run_record_id=run.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        artifact_reference=json.dumps({"stage1_synthetic_source": "/tmp/fake_agent1_view.json"}),
    )
    return run, modA, modB


def _make_three_level_hierarchy(db_session, *, project_id, subproject_id):
    """root -> modA (further split), modB (leaf); modA -> modA1 (leaf, modA's own child)."""
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    modA_node = _leaf_node(
        node_id="node::depth1::modA::000001",
        parent_module_id="modA",
        child_modularization_id="cand-modA",
        child_module_ids=["modA1"],
        accepted=True,
        reason="accepted",
        branch_stopping_reason=None,
    )
    modA1_node = {
        "node_id": "node::depth2::modA1::000003",
        "depth": 2,
        "parent_modularization_id": "cand-modA",
        "parent_module_id": "modA1",
        "child_submodel_id": "m1::submodel::modA::submodel::modA1",
        "child_modularization_id": None,
        "child_module_ids": [],
        "accepted": False,
        "reason": "x",
        "baseline_score": "0.1",
        "child_score": None,
        "branch_stopping_reason": "NO_VALID_CHILD_DECOMPOSITION",
        "recursive_search_stopping_reason": "SEARCH_EXHAUSTED",
        "recursive_search_rounds": 1,
        "recursive_search_policy_version": "test-v1",
        "attach_payload": {
            "modularization_id": "cand-modA",
            "module_ids": ["modA1"],
            "memberships": [
                {"module_id": "modA1", "component_type": "REACTION", "component_id": "r-modA1"}
            ],
        },
    }
    create_hierarchy_nodes(
        run_record_id=run.id,
        nodes=[
            _root_node(),
            modA_node,
            _leaf_node(node_id="node::depth1::modB::000002", parent_module_id="modB"),
            modA1_node,
        ],
        session=db_session,
    )
    modules = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    by_module_id = {m.module_id: m for m in modules}
    run = complete_run(
        run_record_id=run.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        artifact_reference=json.dumps({"stage1_synthetic_source": "/tmp/fake_agent1_view.json"}),
    )
    return run, by_module_id["modA"], by_module_id["modB"], by_module_id["modA1"]


def _make_simulation_run(
    db_session, module, *, status=RunStatus.SUCCEEDED, overall_status="STEADY_STATE_FOUND"
):
    run_record = create_run_record(
        subproject_id=make_subproject_id(db_session, project_id=make_project_id(db_session)),
        stage=RunStage.AGENT3,
        session=db_session,
        model_id=module.root_model_id,
    )
    run_record.model_module_id = module.id
    db_session.flush()
    start_run(run_record_id=run_record.id, session=db_session)
    if status is RunStatus.SUCCEEDED:
        return complete_run(
            run_record_id=run_record.id,
            status=RunStatus.SUCCEEDED,
            session=db_session,
            artifact_reference=json.dumps(
                {
                    "module_id": module.module_id,
                    "modularization_id": "cand-root",
                    "module_handoff_summary": {"reaction_count": 1},
                    "agent3_report": {"overall_status": overall_status},
                }
            ),
        )
    return complete_run(
        run_record_id=run_record.id,
        status=RunStatus.FAILED,
        session=db_session,
        error_summary="simulated infrastructure failure",
    )


def _make_calibration_run(db_session, module, *, target_id, fitted_value):
    run_record = create_run_record(
        subproject_id=make_subproject_id(db_session, project_id=make_project_id(db_session)),
        stage=RunStage.AGENT4,
        session=db_session,
        model_id=module.root_model_id,
    )
    run_record.model_module_id = module.id
    db_session.flush()
    start_run(run_record_id=run_record.id, session=db_session)
    return complete_run(
        run_record_id=run_record.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        artifact_reference=json.dumps(
            {
                "module_id": module.module_id,
                "modularization_id": "cand-root",
                "agent4_report": {
                    "calibration": {
                        "status": "SUCCESS",
                        "objective_before": 10.0,
                        "objective_after": 0.1,
                        "parameter_estimates": [
                            {
                                "target_id": target_id,
                                "fitted_value": fitted_value,
                                "standard_error": 0.01,
                            }
                        ],
                    }
                },
            }
        ),
    )


# --- aggregation from multiple child modules; complete status --------------------------------


def test_root_aggregate_from_multiple_complete_children(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_simulation_run(db_session, modA)
    _make_simulation_run(db_session, modB)

    root_aggregate = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    assert root_aggregate.completeness_status is ModuleAggregateCompleteness.COMPLETE

    payload = module_aggregation_orchestrator.read_aggregate_summary(root_aggregate)
    assert payload["target_model_module_id"] is None
    assert {c["module_id"] for c in payload["children"]} == {"modA", "modB"}
    assert payload["missing_or_failed_children"] == []


# --- mixed success/failure/missing child results; partial status -----------------------------


def test_root_aggregate_with_mixed_results_is_partial(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, _modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_simulation_run(db_session, modA)
    # modB: no simulation run at all -- genuinely missing.

    root_aggregate = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    assert root_aggregate.completeness_status is ModuleAggregateCompleteness.PARTIAL

    payload = module_aggregation_orchestrator.read_aggregate_summary(root_aggregate)
    assert payload["missing_or_failed_children"] == ["modB"]


def test_root_aggregate_with_a_failed_child_is_partial_not_complete(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_simulation_run(db_session, modA)
    _make_simulation_run(db_session, modB, status=RunStatus.FAILED)

    root_aggregate = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    assert root_aggregate.completeness_status is ModuleAggregateCompleteness.PARTIAL
    payload = module_aggregation_orchestrator.read_aggregate_summary(root_aggregate)
    modB_child = next(c for c in payload["children"] if c["module_id"] == "modB")
    assert modB_child["completeness_status"] == "EMPTY"


def test_root_aggregate_with_no_children_run_at_all_is_empty(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, _modA, _modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )

    root_aggregate = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    assert root_aggregate.completeness_status is ModuleAggregateCompleteness.EMPTY


# --- recursive parent -> root roll-up ---------------------------------------------------------


def test_recursive_three_level_roll_up(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB, modA1 = _make_three_level_hierarchy(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    # modA itself has no direct simulation run; only its own child modA1 does.
    _make_simulation_run(db_session, modA1)
    _make_simulation_run(db_session, modB)

    # Building the ROOT aggregate directly must recursively build modA's own aggregate (which
    # rolls up modA1) without the caller ever building it by hand first.
    root_aggregate = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    assert root_aggregate.completeness_status is ModuleAggregateCompleteness.COMPLETE

    modA_aggregate = module_aggregation_orchestrator.get_latest_module_aggregate(
        db_session, modA.id, ModuleExecutionKind.SIMULATION
    )
    assert modA_aggregate is not None
    assert modA_aggregate.completeness_status is ModuleAggregateCompleteness.COMPLETE
    modA_payload = module_aggregation_orchestrator.read_aggregate_summary(modA_aggregate)
    assert modA_payload["own_result"] is None  # modA itself was never directly run
    assert modA_payload["children"][0]["module_id"] == "modA1"

    root_payload = module_aggregation_orchestrator.read_aggregate_summary(root_aggregate)
    modA_in_root = next(c for c in root_payload["children"] if c["module_id"] == "modA")
    assert modA_in_root["aggregate_id"] == str(modA_aggregate.id)


def test_own_result_plus_an_empty_child_is_partial_not_empty(db_session):
    """A regression guard for a real bug caught while designing this increment: a module whose
    own direct result succeeded must never be downgraded to EMPTY just because its own child
    has no data -- it must be PARTIAL (real evidence exists, but the picture is incomplete)."""
    project_id, subproject_id = _make_ids(db_session)
    _run, modA, _modB, _modA1 = _make_three_level_hierarchy(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_simulation_run(db_session, modA)  # modA's own direct result succeeds
    # modA1 (modA's own child) never run -- EMPTY.

    modA_aggregate = module_aggregation_orchestrator.build_module_aggregate(
        model_module_id=modA.id, execution_kind=ModuleExecutionKind.SIMULATION, session=db_session
    )
    assert modA_aggregate.completeness_status is ModuleAggregateCompleteness.PARTIAL


# --- aggregate separately by kind; never collapse unlike result types ------------------------


def test_execution_kinds_are_aggregated_independently(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_simulation_run(db_session, modA)
    _make_simulation_run(db_session, modB)
    _make_calibration_run(db_session, modA, target_id="k1", fitted_value=0.5)
    # modB never calibrated.

    sim_root = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    calib_root = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        session=db_session,
    )
    assert sim_root.completeness_status is ModuleAggregateCompleteness.COMPLETE
    assert calib_root.completeness_status is ModuleAggregateCompleteness.PARTIAL
    assert sim_root.id != calib_root.id


# --- incompatible parameter/observable handling: never averaged ------------------------------


def test_incompatible_parameters_are_listed_separately_never_merged(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_calibration_run(db_session, modA, target_id="k_modA_only", fitted_value=0.5)
    _make_calibration_run(db_session, modB, target_id="k_modB_only", fitted_value=99.0)

    root_aggregate = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.CALIBRATION,
        session=db_session,
    )
    assert root_aggregate.completeness_status is ModuleAggregateCompleteness.COMPLETE
    payload = module_aggregation_orchestrator.read_aggregate_summary(root_aggregate)

    # The root's own payload never contains a blended/averaged parameter value at all -- each
    # child's own fitted parameter is only ever visible by descending into that child's own
    # aggregate, tagged by its own module_id, never merged into a shared number here.
    assert "parameter_estimates" not in payload
    modA_aggregate = module_aggregation_orchestrator.get_latest_module_aggregate(
        db_session, modA.id, ModuleExecutionKind.CALIBRATION
    )
    modB_aggregate = module_aggregation_orchestrator.get_latest_module_aggregate(
        db_session, modB.id, ModuleExecutionKind.CALIBRATION
    )
    modA_estimates = module_aggregation_orchestrator.read_aggregate_summary(modA_aggregate)[
        "own_result"
    ]["parameter_estimates"]
    modB_estimates = module_aggregation_orchestrator.read_aggregate_summary(modB_aggregate)[
        "own_result"
    ]["parameter_estimates"]
    assert modA_estimates == [
        {"target_id": "k_modA_only", "fitted_value": 0.5, "standard_error": 0.01}
    ]
    assert modB_estimates == [
        {"target_id": "k_modB_only", "fitted_value": 99.0, "standard_error": 0.01}
    ]


# --- provenance completeness -------------------------------------------------------------------


def test_provenance_is_fully_traceable(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    sim_A = _make_simulation_run(db_session, modA)
    sim_B = _make_simulation_run(db_session, modB)

    root_aggregate = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    provenance = module_aggregation_orchestrator.get_aggregate_provenance(
        db_session, root_aggregate
    )

    assert set(provenance["run_record_ids"]) == {str(sim_A.id), str(sim_B.id)}
    assert set(provenance["model_module_ids"]) == {str(modA.id), str(modB.id)}
    assert str(root_aggregate.id) in provenance["aggregate_ids"]
    assert len(provenance["aggregate_ids"]) == 3  # root + modA + modB


# --- idempotent rebuild; new child run produces a new version --------------------------------


def test_build_module_aggregate_is_idempotent(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_simulation_run(db_session, modA)
    _make_simulation_run(db_session, modB)

    first = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    second = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    assert second.id == first.id
    assert second.version == 1

    versions = module_aggregation_orchestrator.list_module_aggregate_versions(
        db_session, modA.id, ModuleExecutionKind.SIMULATION
    )
    assert len(versions) == 1


def test_a_new_child_run_produces_a_new_aggregate_version(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_simulation_run(db_session, modA)
    # modB missing at first.

    v1 = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    assert v1.completeness_status is ModuleAggregateCompleteness.PARTIAL
    v1_payload = module_aggregation_orchestrator.read_aggregate_summary(v1)

    # modB now gets a real result.
    _make_simulation_run(db_session, modB)

    v2 = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    assert v2.id != v1.id
    assert v2.version == 2
    assert v2.completeness_status is ModuleAggregateCompleteness.COMPLETE

    # The old version is never mutated.
    assert module_aggregation_orchestrator.read_aggregate_summary(v1) == v1_payload


# --- fresh DB/session reload -------------------------------------------------------------------


def test_fresh_session_reload_preserves_aggregate(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_simulation_run(db_session, modA)
    _make_simulation_run(db_session, modB)

    aggregate = module_aggregation_orchestrator.build_root_aggregate(
        hierarchy_run_record_id=run.id,
        execution_kind=ModuleExecutionKind.SIMULATION,
        session=db_session,
    )
    aggregate_id = aggregate.id

    db_session.expire_all()

    reloaded = module_aggregation_orchestrator.get_latest_root_aggregate(
        db_session, run.id, ModuleExecutionKind.SIMULATION
    )
    assert reloaded.id == aggregate_id
    assert module_aggregation_orchestrator.read_aggregate_summary(reloaded)["children"]


# --- no regression in existing module flows (smoke-level; full suite covers the rest) --------


def test_build_module_aggregate_raises_for_unknown_module(db_session):
    import uuid

    with pytest.raises(ValueError, match="no ModelModule"):
        module_aggregation_orchestrator.build_module_aggregate(
            model_module_id=uuid.uuid4(),
            execution_kind=ModuleExecutionKind.SIMULATION,
            session=db_session,
        )


def test_build_root_aggregate_raises_for_unknown_hierarchy_run(db_session):
    import uuid

    with pytest.raises(ValueError, match="no RunRecord"):
        module_aggregation_orchestrator.build_root_aggregate(
            hierarchy_run_record_id=uuid.uuid4(),
            execution_kind=ModuleExecutionKind.SIMULATION,
            session=db_session,
        )


# --- real, end-to-end realistic integration test -----------------------------------------------


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

    shared_attach_payload = {
        "modularization_id": "cand-root",
        "module_ids": ["modA", "modB"],
        "memberships": memberships,
    }
    create_hierarchy_nodes(
        run_record_id=run.id,
        nodes=[
            _root_node(child_module_ids=["modA", "modB"]),
            _leaf_node(
                node_id="node::depth1::modA::000001",
                parent_module_id="modA",
                attach_payload=shared_attach_payload,
            ),
            _leaf_node(
                node_id="node::depth1::modB::000002",
                parent_module_id="modB",
                attach_payload=shared_attach_payload,
            ),
        ],
        session=db_session,
    )
    materialize_accepted_modules(run_record_id=run.id, session=db_session)
    run = complete_run(
        run_record_id=run.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        artifact_reference=json.dumps(
            {"stage1_synthetic_source": str(_HARNESS_FIXTURES / "synthetic_agent1_view.json")}
        ),
    )
    return run


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_aggregation_smoke_from_two_independently_executed_modules(db_session):
    """The one required realistic integration test: a real hierarchy with two persisted
    modules, each independently given a real module-level Agent3/Agent4 result (a real
    calibration for modA, a real simulation for modB -- genuinely different execution kinds,
    so the SIMULATION and CALIBRATION root aggregates are each real, distinct, correctly-
    PARTIAL roll-ups), then a parent (module-level) aggregate and a root aggregate are built
    purely in-process -- verifying every reported summary item is traceable to its real source
    RunRecord/ModuleExecutionSnapshot.
    """
    project_id, subproject_id = _make_ids(db_session)
    run = _two_module_split_run_with_dynamics(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    # modB is the second sibling materialized by the same hierarchy run, reusing the identical
    # hand-split fixture already proven throughout this family of increments.
    from app.persistence.model_module import list_model_modules_for_run

    modA_db, modB_db = sorted(
        list_model_modules_for_run(db_session, run.id), key=lambda m: m.module_id
    )
    assert {modA_db.module_id, modB_db.module_id} == {"modA", "modB"}

    # Resolve modA's own boundaries and calibrate it for real.
    (s1_port,) = persist_candidate_boundary_ports(
        model_module_id=modA_db.id,
        candidates=[{"species_id": "compound-S1::in::compartment-1", "direction": "INPUT"}],
        session=db_session,
    )
    submit_boundary_decision(
        port_id=s1_port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("10"),
        decided_by="test-reviewer",
    )
    (s3_port_A,) = derive_boundary_ports(
        model_module_id=modA_db.id,
        project_id=project_id,
        subproject_id=subproject_id,
        session=db_session,
    )
    submit_boundary_decision(
        port_id=s3_port_A.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("0"),
        decided_by="test-reviewer",
    )

    _K1, _S1_FIXED, _TRUE_K2 = 1.0, 10.0, 0.5
    train_t = [1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 16.0, 20.0]
    train_v = [(_K1 * _S1_FIXED / _TRUE_K2) * (1 - math.exp(-_TRUE_K2 * t)) for t in train_t]
    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=modA_db.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request={
            "request_id": "agg-smoke-calib-req",
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

    # Resolve modB's own boundary and simulate it for real.
    (s3_port_B,) = derive_boundary_ports(
        model_module_id=modB_db.id,
        project_id=project_id,
        subproject_id=subproject_id,
        session=db_session,
    )
    submit_boundary_decision(
        port_id=s3_port_B.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("0"),
        decided_by="test-reviewer",
    )
    sim_run = model_module_orchestrator.request_module_simulation(
        model_module_id=modB_db.id,
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
    )
    assert sim_run.status is RunStatus.SUCCEEDED, sim_run.error_summary

    try:
        calib_root = module_aggregation_orchestrator.build_root_aggregate(
            hierarchy_run_record_id=run.id,
            execution_kind=ModuleExecutionKind.CALIBRATION,
            session=db_session,
        )
        sim_root = module_aggregation_orchestrator.build_root_aggregate(
            hierarchy_run_record_id=run.id,
            execution_kind=ModuleExecutionKind.SIMULATION,
            session=db_session,
        )
        # Different execution kinds, never collapsed into one score: modA calibrated but
        # never simulated, modB simulated but never calibrated -- both roll-ups are correctly
        # PARTIAL, for different, non-overlapping reasons.
        assert calib_root.completeness_status is ModuleAggregateCompleteness.PARTIAL
        assert sim_root.completeness_status is ModuleAggregateCompleteness.PARTIAL

        calib_provenance = module_aggregation_orchestrator.get_aggregate_provenance(
            db_session, calib_root
        )
        assert str(calib_run.id) in calib_provenance["run_record_ids"]
        assert len(calib_provenance["execution_snapshot_ids"]) == 1  # calibration always snapshots

        sim_provenance = module_aggregation_orchestrator.get_aggregate_provenance(
            db_session, sim_root
        )
        assert str(sim_run.id) in sim_provenance["run_record_ids"]

        modA_calib_aggregate = module_aggregation_orchestrator.get_latest_module_aggregate(
            db_session, modA_db.id, ModuleExecutionKind.CALIBRATION
        )
        modA_payload = module_aggregation_orchestrator.read_aggregate_summary(modA_calib_aggregate)
        assert modA_payload["own_result"]["run_record_id"] == str(calib_run.id)
        fitted = {
            p["target_id"]: p["fitted_value"]
            for p in modA_payload["own_result"]["parameter_estimates"]
        }
        assert fitted["k_reaction-2_protein-2"] == pytest.approx(_TRUE_K2, rel=0.05)
    finally:
        import shutil

        for run_id in (calib_run.id, sim_run.id):
            run_dir = HARNESS_REPO_DIR / "artifacts" / "runs" / str(run_id)
            if run_dir.is_dir():
                shutil.rmtree(run_dir)
