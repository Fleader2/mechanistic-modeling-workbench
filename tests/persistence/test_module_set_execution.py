"""Tests for the Module-Set Edited-Module Materialization increment, Phase B's own persistence
layer: boundary-review candidate/decision management, readiness evaluation, simulation
submission, and the background worker's own claim mechanism. Pure database logic -- no harness
call happens anywhere in this file (see ``tests/orchestration/
test_module_set_execution_orchestrator.py`` for the harness-facing, mocked layer, and
``tests/api/test_module_set_execution.py`` for the full API surface).
"""

from __future__ import annotations

import json

import pytest

from app.models.enums import ModuleBoundaryTreatmentType, RunStatus
from app.persistence.module_set import create_draft_from_run, save_draft
from app.persistence.module_set_execution import (
    ModuleSetMemberNotReadyError,
    ModuleSetMemberReviewStaleError,
    ModuleSetMemberSimulationAlreadyActiveError,
    build_resolved_module_ports_payload,
    claim_next_pending_module_set_run,
    evaluate_readiness,
    get_execution_snapshot_for_run,
    get_or_create_review,
    list_boundary_ports_for_review,
    list_runs_for_module_set_member,
    persist_candidate_boundary_ports,
    submit_boundary_decision,
    submit_module_set_simulation,
)
from tests.persistence.conftest import make_subproject_id, make_succeeded_hierarchical_run


def _saved_member(db_session, *, reaction_ids_per_leaf=None):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(
        db_session,
        subproject_id=subproject_id,
        leaf_count=2,
        reaction_ids_per_leaf=reaction_ids_per_leaf or [["rA1", "rA2"], ["rB1"]],
    )
    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )
    version = save_draft(session=db_session, draft_id=draft.id, mode="new_set", set_name="Set")
    member = version.members[0]
    return subproject_id, member


class TestGetOrCreateReview:
    def test_creates_a_review_at_version_zero(self, db_session):
        _subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        assert review.review_version == 0
        assert review.derived_at is None

    def test_is_idempotent(self, db_session):
        _subproject_id, member = _saved_member(db_session)
        review1 = get_or_create_review(db_session, member.id)
        review2 = get_or_create_review(db_session, member.id)
        assert review1.id == review2.id


class TestPersistCandidateBoundaryPorts:
    def test_creates_new_ports_and_sets_derived_at(self, db_session):
        _subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        created = persist_candidate_boundary_ports(
            review_id=review.id,
            candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
            session=db_session,
        )
        assert len(created) == 1
        assert review.derived_at is not None

    def test_a_second_call_never_overwrites_an_existing_decision(self, db_session):
        _subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        (port,) = persist_candidate_boundary_ports(
            review_id=review.id,
            candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
            session=db_session,
        )
        submit_boundary_decision(
            port_id=port.id,
            treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
            expected_review_version=review.review_version,
            session=db_session,
            initial_value="1.0",
            unit="mM",
        )
        created_again = persist_candidate_boundary_ports(
            review_id=review.id,
            candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
            session=db_session,
        )
        assert created_again == []
        ports = list_boundary_ports_for_review(db_session, review.id)
        assert ports[0].treatment_type is ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED


class TestSubmitBoundaryDecision:
    def test_resolves_the_port_and_advances_review_version(self, db_session):
        _subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        (port,) = persist_candidate_boundary_ports(
            review_id=review.id,
            candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
            session=db_session,
        )
        submit_boundary_decision(
            port_id=port.id,
            treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
            expected_review_version=0,
            session=db_session,
            initial_value="1.5",
            unit="mM",
            decided_by="Morgan Lee",
        )
        assert review.review_version == 1
        assert port.resolution_status.value == "RESOLVED"
        assert port.decided_by == "Morgan Lee"

    def test_rejects_unresolved_as_a_target_treatment(self, db_session):
        _subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        (port,) = persist_candidate_boundary_ports(
            review_id=review.id,
            candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
            session=db_session,
        )
        with pytest.raises(ValueError, match="UNRESOLVED"):
            submit_boundary_decision(
                port_id=port.id,
                treatment_type=ModuleBoundaryTreatmentType.UNRESOLVED,
                expected_review_version=0,
                session=db_session,
            )

    def test_rejects_a_stale_review_version(self, db_session):
        _subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        (port,) = persist_candidate_boundary_ports(
            review_id=review.id,
            candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
            session=db_session,
        )
        submit_boundary_decision(
            port_id=port.id,
            treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
            expected_review_version=0,
            session=db_session,
            initial_value="1.0",
            unit="mM",
        )
        with pytest.raises(ModuleSetMemberReviewStaleError) as exc_info:
            submit_boundary_decision(
                port_id=port.id,
                treatment_type=ModuleBoundaryTreatmentType.PRESCRIBED_INPUT,
                expected_review_version=0,
                session=db_session,
            )
        assert exc_info.value.review.review_version == 1


class TestEvaluateReadiness:
    def test_no_ports_derived_is_blocking(self, db_session):
        _subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        findings = evaluate_readiness(db_session, review.id)
        assert findings and findings[0].code == "NO_BOUNDARY_PORTS_DERIVED"

    def test_an_unresolved_port_is_blocking(self, db_session):
        _subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        persist_candidate_boundary_ports(
            review_id=review.id,
            candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
            session=db_session,
        )
        findings = evaluate_readiness(db_session, review.id)
        assert findings and findings[0].code == "UNRESOLVED_BOUNDARY_PORT"

    def test_every_port_resolved_is_ready(self, db_session):
        _subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        (port,) = persist_candidate_boundary_ports(
            review_id=review.id,
            candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
            session=db_session,
        )
        submit_boundary_decision(
            port_id=port.id,
            treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
            expected_review_version=0,
            session=db_session,
            initial_value="1.0",
            unit="mM",
        )
        assert evaluate_readiness(db_session, review.id) == []


class TestBuildResolvedModulePortsPayload:
    def test_includes_module_id_in_the_exact_shape_the_harness_requires(self, db_session):
        """Regression test for a bug caught only by this increment's own live verification,
        never by a mocked unit test: the harness's own ``run_agent2_rematerialize_module.py``
        requires ``module_id`` on every ``module_ports`` entry (``ModulePort(module_id=...)``),
        identically to ``build_module_ports_payload``'s established shape -- a real subprocess
        call raised ``KeyError: 'module_id'`` the first time this payload reached it for real."""
        _subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        (port,) = persist_candidate_boundary_ports(
            review_id=review.id,
            candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
            session=db_session,
        )
        submit_boundary_decision(
            port_id=port.id,
            treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
            expected_review_version=0,
            session=db_session,
            initial_value="1.0",
            unit="mM",
        )

        payload = build_resolved_module_ports_payload(
            db_session, review.id, module_id=member.model_module.module_id
        )

        assert len(payload) == 1
        assert payload[0]["module_id"] == member.model_module.module_id
        assert set(payload[0].keys()) == {
            "port_id",
            "module_id",
            "species_id",
            "direction",
            "externally_controlled",
            "initial_value",
            "unit",
        }


class TestSubmitModuleSetSimulation:
    def _ready_member(self, db_session):
        subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        (port,) = persist_candidate_boundary_ports(
            review_id=review.id,
            candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
            session=db_session,
        )
        submit_boundary_decision(
            port_id=port.id,
            treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
            expected_review_version=0,
            session=db_session,
            initial_value="1.0",
            unit="mM",
        )
        return subproject_id, member, review

    def test_creates_a_pending_run_and_an_immutable_snapshot(self, db_session):
        subproject_id, member, review = self._ready_member(db_session)
        run = submit_module_set_simulation(
            session=db_session,
            module_set_member=member,
            subproject_id=subproject_id,
            expected_review_version=review.review_version,
            saved_by="Morgan Lee",
        )
        assert run.status is RunStatus.PENDING
        assert run.module_set_member_id == member.id
        snapshot = get_execution_snapshot_for_run(db_session, run.id)
        assert snapshot is not None
        payload = json.loads(snapshot.snapshot_payload)
        assert payload["saved_by"] == "Morgan Lee"
        # `member` was never edited -- `reaction_component_ids` stays NULL by increment 23's
        # own "minimal diff" property, so the snapshot's own pinned selection must be derived
        # from the real ModelModule, never an empty list.
        assert member.reaction_component_ids is None
        assert sorted(payload["reaction_component_ids"]) == ["rA1", "rA2"]

    def test_rejects_when_not_ready(self, db_session):
        subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        with pytest.raises(ModuleSetMemberNotReadyError) as exc_info:
            submit_module_set_simulation(
                session=db_session,
                module_set_member=member,
                subproject_id=subproject_id,
                expected_review_version=review.review_version,
            )
        assert exc_info.value.findings[0].code == "NO_BOUNDARY_PORTS_DERIVED"

    def test_rejects_a_stale_review_version(self, db_session):
        subproject_id, member, review = self._ready_member(db_session)
        with pytest.raises(ModuleSetMemberReviewStaleError):
            submit_module_set_simulation(
                session=db_session,
                module_set_member=member,
                subproject_id=subproject_id,
                expected_review_version=review.review_version + 1,
            )

    def test_rejects_a_duplicate_active_submission(self, db_session):
        subproject_id, member, review = self._ready_member(db_session)
        submit_module_set_simulation(
            session=db_session,
            module_set_member=member,
            subproject_id=subproject_id,
            expected_review_version=review.review_version,
        )
        with pytest.raises(ModuleSetMemberSimulationAlreadyActiveError):
            submit_module_set_simulation(
                session=db_session,
                module_set_member=member,
                subproject_id=subproject_id,
                expected_review_version=review.review_version,
            )

    def test_list_runs_for_member_shows_every_submission_newest_first(self, db_session):
        subproject_id, member, review = self._ready_member(db_session)
        run1 = submit_module_set_simulation(
            session=db_session,
            module_set_member=member,
            subproject_id=subproject_id,
            expected_review_version=review.review_version,
        )
        runs = list_runs_for_module_set_member(db_session, member.id)
        assert [r.id for r in runs] == [run1.id]


class TestClaimNextPendingModuleSetRun:
    def test_claims_a_pending_run_and_transitions_it_to_running(self, db_session):
        subproject_id, member = _saved_member(db_session)
        review = get_or_create_review(db_session, member.id)
        (port,) = persist_candidate_boundary_ports(
            review_id=review.id,
            candidates=[{"species_id": "AcCoA", "direction": "OUTPUT"}],
            session=db_session,
        )
        submit_boundary_decision(
            port_id=port.id,
            treatment_type=ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
            expected_review_version=0,
            session=db_session,
            initial_value="1.0",
            unit="mM",
        )
        run = submit_module_set_simulation(
            session=db_session,
            module_set_member=member,
            subproject_id=subproject_id,
            expected_review_version=1,
        )
        db_session.commit()

        claimed = claim_next_pending_module_set_run(db_session)
        assert claimed is not None
        assert claimed.id == run.id
        assert claimed.status is RunStatus.RUNNING
        assert claimed.started_at is not None

    def test_returns_none_when_nothing_is_pending(self, db_session):
        db_session.commit()
        assert claim_next_pending_module_set_run(db_session) is None

    def test_never_claims_an_ordinary_non_module_set_run(self, db_session):
        from app.models.enums import RunStage
        from app.persistence.run_record import create_run_record

        subproject_id, _member = _saved_member(db_session)
        create_run_record(subproject_id=subproject_id, stage=RunStage.AGENT3, session=db_session)
        db_session.commit()
        assert claim_next_pending_module_set_run(db_session) is None
