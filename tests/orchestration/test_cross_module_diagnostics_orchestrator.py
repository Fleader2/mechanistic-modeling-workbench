"""Tests for ``app.orchestration.cross_module_diagnostics_orchestrator`` (Cross-Module
Consistency and Reconciliation Diagnostics increment).

One realistic, end-to-end test drives two real, independently-executed module-level results
(a real Agent2->Agent3->Agent4 calibration of one sibling module, a real Agent2->Agent3
simulation of the other, each with deliberately conflicting boundary treatments for the one
real, structurally-shared species) through the sibling ``agent-integration-harness``
repository, then runs the consistency sweep purely in-process (no agent/harness call of its
own -- task instructions §7), verifying the detected finding traces back to the exact real
source records that produced it. Every other test uses hand-built ``RunRecord``/
``ModuleBoundaryPort`` rows to exercise the comparison logic itself without a real subprocess.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest

from app.models.enums import ModuleBoundaryTreatmentType, RunStage, RunStatus
from app.orchestration import (
    cross_module_diagnostics_orchestrator,
    model_module_orchestrator,
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
from app.persistence.model_module import list_model_modules_for_run, materialize_accepted_modules
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


def _make_parent_child_modules(db_session, *, project_id, subproject_id):
    """root -> modA (further split) -> modA1 (modA's own child)."""
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
        run_record_id=run.id, nodes=[_root_node(), modA_node, modA1_node], session=db_session
    )
    modules = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    by_module_id = {m.module_id: m for m in modules}
    run = complete_run(
        run_record_id=run.id,
        status=RunStatus.SUCCEEDED,
        session=db_session,
        artifact_reference=json.dumps({"stage1_synthetic_source": "/tmp/fake_agent1_view.json"}),
    )
    return run, by_module_id["modA"], by_module_id["modA1"]


def _resolve_boundary(db_session, module, *, species_id, direction="INPUT", value="1", unit=None):
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": species_id, "direction": direction}],
        session=db_session,
    )
    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal(value),
        unit=unit,
        decided_by="test-user",
    )
    return port


def _leave_unresolved(db_session, module, *, species_id, direction="INPUT"):
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": species_id, "direction": direction}],
        session=db_session,
    )
    return port


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


def _make_validation_run(db_session, module, *, overall_status):
    run_record = create_run_record(
        subproject_id=make_subproject_id(db_session, project_id=make_project_id(db_session)),
        stage=RunStage.AGENT5,
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
                "calibration_run_record_id": None,
                "agent5_report": {"overall_status": overall_status},
            }
        ),
    )


def _findings_by_category(findings, category):
    return [f for f in findings if f.category.value == category]


# --- sibling boundary mismatch -----------------------------------------------------------------


def test_sibling_boundary_mismatch_is_detected(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_boundary(db_session, modA, species_id="X", value="5")
    _resolve_boundary(db_session, modB, species_id="X", value="999")

    diagnostic_run = cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    findings = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)
    conflicts = _findings_by_category(findings, "SHARED_BOUNDARY_SPECIES_CONFLICT")
    assert len(conflicts) == 1
    assert conflicts[0].severity.value == "ERROR"
    assert diagnostic_run.finding_count == len(findings)


# --- parent/child boundary mismatch -------------------------------------------------------------


def test_parent_child_boundary_mismatch_is_detected(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modA1 = _make_parent_child_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_boundary(db_session, modA, species_id="Y", value="1")
    _resolve_boundary(db_session, modA1, species_id="Y", value="2")

    cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    findings = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)
    conflicts = _findings_by_category(findings, "PARENT_CHILD_BOUNDARY_INCONSISTENCY")
    assert len(conflicts) == 1
    assert conflicts[0].severity.value == "ERROR"


# --- compatible case: no false positive ---------------------------------------------------------


def test_compatible_boundary_values_produce_no_finding(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_boundary(db_session, modA, species_id="X", value="5", unit="mM")
    _resolve_boundary(db_session, modB, species_id="X", value="5", unit="mM")

    cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    findings = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)
    assert findings == []


def test_distinct_species_produce_no_finding(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_boundary(db_session, modA, species_id="X1", value="5")
    _resolve_boundary(db_session, modB, species_id="X2", value="999")

    cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    findings = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)
    assert findings == []


# --- parameter conflict ---------------------------------------------------------------------


def test_parameter_conflict_is_detected(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_calibration_run(db_session, modA, target_id="k_shared", fitted_value=0.5)
    _make_calibration_run(db_session, modB, target_id="k_shared", fitted_value=0.9)

    cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    findings = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)
    conflicts = _findings_by_category(findings, "PARAMETER_ASSUMPTION_CONFLICT")
    assert len(conflicts) == 1
    assert conflicts[0].severity.value == "ERROR"


def test_different_parameters_produce_no_false_positive(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_calibration_run(db_session, modA, target_id="k_modA_only", fitted_value=0.5)
    _make_calibration_run(db_session, modB, target_id="k_modB_only", fitted_value=0.9)

    cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    findings = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)
    assert _findings_by_category(findings, "PARAMETER_ASSUMPTION_CONFLICT") == []


# --- incompatible / missing units -------------------------------------------------------------


def test_incompatible_units_are_detected(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_boundary(db_session, modA, species_id="Z", value="5", unit="mM")
    _resolve_boundary(db_session, modB, species_id="Z", value="5", unit="mol/L")

    cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    findings = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)
    unit_findings = _findings_by_category(findings, "UNIT_INCOMPATIBILITY")
    assert len(unit_findings) == 1
    assert unit_findings[0].severity.value == "WARNING"


def test_missing_unit_on_one_side_is_detected(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_boundary(db_session, modA, species_id="Z", value="5", unit="mM")
    _resolve_boundary(db_session, modB, species_id="Z", value="5", unit=None)

    cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    findings = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)
    unit_findings = _findings_by_category(findings, "UNIT_INCOMPATIBILITY")
    assert len(unit_findings) == 1
    assert unit_findings[0].severity.value == "INFO"


# --- conflicting validation outcomes -----------------------------------------------------------


def test_conflicting_validation_outcomes_are_detected(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _make_validation_run(db_session, modA, overall_status="SUCCESS")
    _make_validation_run(db_session, modB, overall_status="OVERFIT_WARNING")

    cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    findings = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)
    conflicts = _findings_by_category(findings, "CONFLICTING_CALIBRATION_OR_VALIDATION_OUTCOME")
    assert len(conflicts) == 1
    assert conflicts[0].severity.value == "WARNING"


# --- unresolved comparison due to insufficient evidence -----------------------------------------


def test_unresolved_boundary_produces_unresolved_finding_not_silently_skipped(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_boundary(db_session, modA, species_id="W", value="1")
    _leave_unresolved(db_session, modB, species_id="W")

    cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    findings = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)
    unresolved = _findings_by_category(findings, "INSUFFICIENT_EVIDENCE_FOR_COMPARISON")
    assert len(unresolved) == 1
    assert unresolved[0].severity.value == "UNRESOLVED"


# --- provenance completeness --------------------------------------------------------------------


def test_finding_evidence_is_fully_traceable(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    port_a = _resolve_boundary(db_session, modA, species_id="X", value="5")
    port_b = _resolve_boundary(db_session, modB, species_id="X", value="999")

    cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    (finding,) = _findings_by_category(
        cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id),
        "SHARED_BOUNDARY_SPECIES_CONFLICT",
    )
    detail = cross_module_diagnostics_orchestrator.get_finding_evidence(db_session, finding.id)
    assert set(detail["affected_model_module_ids"]) == {str(modA.id), str(modB.id)}
    assert detail["evidence"]["module_a"]["port"]["port_id"] == port_a.port_id
    assert detail["evidence"]["module_b"]["port"]["port_id"] == port_b.port_id


# --- idempotent rerun; changed source state produces a new version ------------------------------


def test_run_diagnostics_is_idempotent(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_boundary(db_session, modA, species_id="X", value="5")
    _resolve_boundary(db_session, modB, species_id="X", value="999")

    first = cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    second = cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    assert second.id == first.id
    assert second.version == 1


def test_changed_boundary_value_produces_a_new_diagnostic_version(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    port_a = _resolve_boundary(db_session, modA, species_id="X", value="5")
    _resolve_boundary(db_session, modB, species_id="X", value="999")

    v1 = cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    assert v1.finding_count == 1

    # The conflict is resolved by changing modA's own value to match modB's.
    submit_boundary_decision(
        port_id=port_a.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("999"),
        decided_by="someone-else",
    )

    v2 = cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    assert v2.id != v1.id
    assert v2.version == 2
    assert v2.finding_count == 0

    # The old version's own findings are preserved, never mutated.
    from app.persistence.cross_module_diagnostic import list_findings_for_run

    assert len(list_findings_for_run(db_session, v1.id)) == 1


# --- human review annotation survives reload ----------------------------------------------------


def test_review_annotation_survives_fresh_session_reload(db_session):
    project_id, subproject_id = _make_ids(db_session)
    run, modA, modB = _make_two_sibling_modules(
        db_session, project_id=project_id, subproject_id=subproject_id
    )
    _resolve_boundary(db_session, modA, species_id="X", value="5")
    _resolve_boundary(db_session, modB, species_id="X", value="999")
    cross_module_diagnostics_orchestrator.run_diagnostics(
        hierarchy_run_record_id=run.id, session=db_session
    )
    (finding,) = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)

    cross_module_diagnostics_orchestrator.review_finding(
        finding_id=finding.id,
        session=db_session,
        review_note="acceptable: modB's own feed is independently buffered",
        reviewed_by="pi",
    )
    finding_id = finding.id

    db_session.expire_all()

    from app.persistence.cross_module_diagnostic import get_finding

    reloaded = get_finding(db_session, finding_id)
    assert reloaded.review_status.value == "REVIEWED"
    assert reloaded.reviewed_by == "pi"
    assert "buffered" in reloaded.review_note
    # The review never alters the finding's own detection content.
    assert reloaded.severity.value == "ERROR"


def test_run_diagnostics_raises_for_unknown_hierarchy_run(db_session):
    import uuid

    with pytest.raises(ValueError, match="no RunRecord"):
        cross_module_diagnostics_orchestrator.run_diagnostics(
            hierarchy_run_record_id=uuid.uuid4(), session=db_session
        )


# --- real, end-to-end realistic integration test -------------------------------------------------


def _two_module_split_run_with_dynamics(db_session, *, project_id, subproject_id, modB_s3_value):
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
    modA_db, modB_db = sorted(
        list_model_modules_for_run(db_session, run.id), key=lambda m: m.module_id
    )

    # modA: real boundary resolution -- S1 fixed input, S3 fixed output at 0.
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

    # modB: real boundary resolution -- S3 fixed input at a (possibly conflicting) value.
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
        initial_value=Decimal(modB_s3_value),
        decided_by="test-reviewer",
    )
    return run, modA_db, modB_db


@pytest.mark.skipif(_HARNESS_UNAVAILABLE is not None, reason=str(_HARNESS_UNAVAILABLE))
def test_real_diagnostics_smoke_detects_a_real_boundary_conflict(db_session):
    """The one required realistic integration test: two real, persisted sibling modules, each
    independently given a real module-level Agent3/Agent4 result (a real calibration for
    modA, a real simulation for modB), with a deliberate, real boundary-value conflict on the
    one real, structurally-shared species (S3: modA's own OUTPUT fixed at 0, modB's own INPUT
    fixed at 99) -- verifying the sweep, run purely in-process, detects it and that its own
    evidence traces back to the exact real ModuleBoundaryPort/RunRecord values that produced
    it.
    """
    project_id, subproject_id = _make_ids(db_session)
    run, modA_db, modB_db = _two_module_split_run_with_dynamics(
        db_session, project_id=project_id, subproject_id=subproject_id, modB_s3_value="99"
    )

    _K1, _S1_FIXED, _TRUE_K2 = 1.0, 10.0, 0.5
    train_t = [1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 16.0, 20.0]
    train_v = [(_K1 * _S1_FIXED / _TRUE_K2) * (1 - math.exp(-_TRUE_K2 * t)) for t in train_t]
    calib_run = module_calibration_orchestrator.request_module_calibration(
        model_module_id=modA_db.id,
        subproject_id=subproject_id,
        project_id=project_id,
        calibration_request={
            "request_id": "diag-smoke-calib-req",
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

    sim_run = model_module_orchestrator.request_module_simulation(
        model_module_id=modB_db.id,
        subproject_id=subproject_id,
        project_id=project_id,
        session=db_session,
    )
    assert sim_run.status is RunStatus.SUCCEEDED, sim_run.error_summary

    try:
        diagnostic_run = cross_module_diagnostics_orchestrator.run_diagnostics(
            hierarchy_run_record_id=run.id, session=db_session
        )
        findings = cross_module_diagnostics_orchestrator.get_current_findings(db_session, run.id)
        conflicts = _findings_by_category(findings, "SHARED_BOUNDARY_SPECIES_CONFLICT")
        assert len(conflicts) == 1
        assert conflicts[0].severity.value == "ERROR"
        assert diagnostic_run.finding_count == len(findings)

        detail = cross_module_diagnostics_orchestrator.get_finding_evidence(
            db_session, conflicts[0].id
        )
        assert set(detail["affected_model_module_ids"]) == {str(modA_db.id), str(modB_db.id)}
        assert detail["evidence"]["species_id"] == "compound-S3::in::compartment-1"
        values = {
            detail["evidence"]["module_a"]["module_id"]: detail["evidence"]["module_a"]["port"][
                "initial_value"
            ],
            detail["evidence"]["module_b"]["module_id"]: detail["evidence"]["module_b"]["port"][
                "initial_value"
            ],
        }
        assert values == {"modA": "0", "modB": "99"}
    finally:
        import shutil

        for run_id in (calib_run.id, sim_run.id):
            run_dir = HARNESS_REPO_DIR / "artifacts" / "runs" / str(run_id)
            if run_dir.is_dir():
                shutil.rmtree(run_dir)
