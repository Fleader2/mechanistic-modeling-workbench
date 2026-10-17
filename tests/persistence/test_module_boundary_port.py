"""Tests for ``app.persistence.module_boundary_port``."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import (
    ModuleBoundaryResolutionStatus,
    ModuleBoundaryTreatmentType,
    ModulePortDirection,
    RunStage,
)
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model_module import materialize_accepted_modules
from app.persistence.module_boundary_port import (
    get_boundary_port,
    list_boundary_ports_for_module,
    persist_candidate_boundary_ports,
    submit_boundary_decision,
)
from app.persistence.run_record import create_run_record, start_run
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


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


def _make_module(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    create_hierarchy_nodes(
        run_record_id=run.id, nodes=[_root_node(), _modA_node()], session=db_session
    )
    (module,) = materialize_accepted_modules(run_record_id=run.id, session=db_session)
    return module


def test_persist_candidate_boundary_ports_creates_unresolved_rows(db_session):
    module = _make_module(db_session)
    created = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[
            {"species_id": "s1", "direction": "INPUT"},
            {"species_id": "s2", "direction": "OUTPUT"},
        ],
        session=db_session,
    )
    assert len(created) == 2
    assert {c.species_id for c in created} == {"s1", "s2"}
    assert all(c.treatment_type is ModuleBoundaryTreatmentType.UNRESOLVED for c in created)
    assert all(
        c.resolution_status is ModuleBoundaryResolutionStatus.PENDING_REVIEW for c in created
    )
    assert all(c.derived_automatically is True for c in created)


def test_persist_candidate_boundary_ports_is_idempotent(db_session):
    module = _make_module(db_session)
    candidates = [{"species_id": "s1", "direction": "INPUT"}]
    first = persist_candidate_boundary_ports(
        model_module_id=module.id, candidates=candidates, session=db_session
    )
    assert len(first) == 1

    second = persist_candidate_boundary_ports(
        model_module_id=module.id, candidates=candidates, session=db_session
    )
    assert second == []
    assert len(list_boundary_ports_for_module(db_session, module.id)) == 1


def test_persist_candidate_boundary_ports_never_overwrites_a_manual_decision(db_session):
    module = _make_module(db_session)
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "s1", "direction": "INPUT"}],
        session=db_session,
    )
    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("5"),
        decided_by="test-user",
    )

    # Re-derivation reports the identical candidate again -- must not touch the now-resolved row.
    second = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "s1", "direction": "INPUT"}],
        session=db_session,
    )
    assert second == []

    reloaded = get_boundary_port(db_session, port.id)
    assert reloaded.treatment_type is ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED
    assert reloaded.resolution_status is ModuleBoundaryResolutionStatus.RESOLVED
    assert reloaded.initial_value == Decimal("5")
    assert reloaded.derived_automatically is False


def test_submit_boundary_decision_externally_controlled(db_session):
    module = _make_module(db_session)
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "s1", "direction": "INPUT"}],
        session=db_session,
    )
    resolved = submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("2.5"),
        unit="mM",
        value_source="USER_SUPPLIED",
        decided_by="alice",
        notes="matches observed extracellular concentration",
    )
    assert resolved.treatment_type is ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED
    assert resolved.initial_value == Decimal("2.5")
    assert resolved.unit == "mM"
    assert resolved.decided_by == "alice"
    assert resolved.decided_at is not None


def test_submit_boundary_decision_prescribed_input(db_session):
    module = _make_module(db_session)
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "s1", "direction": "INPUT"}],
        session=db_session,
    )
    resolved = submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.PRESCRIBED_INPUT,
        session=db_session,
        initial_value=Decimal("0.1"),
        unit="mM/s",
        value_source="DERIVED_FROM_PARENT_FLUX",
    )
    assert resolved.treatment_type is ModuleBoundaryTreatmentType.PRESCRIBED_INPUT
    assert resolved.resolution_status is ModuleBoundaryResolutionStatus.RESOLVED


def test_submit_boundary_decision_dynamic_coupling_never_takes_a_value(db_session):
    module = _make_module(db_session)
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "s1", "direction": "INPUT_OUTPUT"}],
        session=db_session,
    )
    with pytest.raises(ValueError, match="only meaningful"):
        submit_boundary_decision(
            port_id=port.id,
            treatment_type=ModuleBoundaryTreatmentType.DYNAMIC_COUPLING,
            session=db_session,
            initial_value=Decimal("1"),
        )

    resolved = submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.DYNAMIC_COUPLING,
        session=db_session,
    )
    assert resolved.treatment_type is ModuleBoundaryTreatmentType.DYNAMIC_COUPLING
    assert resolved.initial_value is None
    assert resolved.resolution_status is ModuleBoundaryResolutionStatus.RESOLVED


def test_submit_boundary_decision_cannot_resolve_to_unresolved(db_session):
    module = _make_module(db_session)
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "s1", "direction": "INPUT"}],
        session=db_session,
    )
    with pytest.raises(ValueError, match="cannot resolve"):
        submit_boundary_decision(
            port_id=port.id,
            treatment_type=ModuleBoundaryTreatmentType.UNRESOLVED,
            session=db_session,
        )


def test_submit_boundary_decision_raises_for_unknown_port(db_session):
    import uuid

    with pytest.raises(ValueError, match="no ModuleBoundaryPort"):
        submit_boundary_decision(
            port_id=uuid.uuid4(),
            treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
            session=db_session,
        )


def test_list_boundary_ports_for_module_is_scoped(db_session):
    module1 = _make_module(db_session)
    module2 = _make_module(db_session)
    persist_candidate_boundary_ports(
        model_module_id=module1.id,
        candidates=[{"species_id": "s1", "direction": "INPUT"}],
        session=db_session,
    )
    persist_candidate_boundary_ports(
        model_module_id=module2.id,
        candidates=[{"species_id": "s2", "direction": "OUTPUT"}],
        session=db_session,
    )
    ports1 = list_boundary_ports_for_module(db_session, module1.id)
    assert len(ports1) == 1
    assert ports1[0].species_id == "s1"


def test_input_output_direction_is_a_distinct_port_from_input(db_session):
    module = _make_module(db_session)
    created = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[
            {"species_id": "s1", "direction": "INPUT"},
            {"species_id": "s1", "direction": "INPUT_OUTPUT"},
        ],
        session=db_session,
    )
    assert len(created) == 2
    assert {c.direction for c in created} == {
        ModulePortDirection.INPUT,
        ModulePortDirection.INPUT_OUTPUT,
    }


def test_fresh_session_reload_preserves_decision(db_session):
    module = _make_module(db_session)
    (port,) = persist_candidate_boundary_ports(
        model_module_id=module.id,
        candidates=[{"species_id": "s1", "direction": "INPUT"}],
        session=db_session,
    )
    submit_boundary_decision(
        port_id=port.id,
        treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        session=db_session,
        initial_value=Decimal("3"),
        decided_by="bob",
    )
    db_session.expire_all()

    reloaded = get_boundary_port(db_session, port.id)
    assert reloaded.treatment_type is ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED
    assert reloaded.initial_value == Decimal("3")
    assert reloaded.decided_by == "bob"
