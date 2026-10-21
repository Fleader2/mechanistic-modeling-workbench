"""Tests for the Module-Set Edited-Module Materialization increment, Phase B's own
orchestration layer -- mirroring ``tests/orchestration/test_model_module_orchestrator.py``'s
own established convention: every harness client function is mocked via ``monkeypatch`` here
(fast, no real subprocess); real, end-to-end subprocess behavior is proven once, separately, at
the Harness repository's own test level (``agent-integration-harness/tests/harness/
test_workbench_module_set_simulation_contract.py``) and again in this increment's own live
browser verification.
"""

from __future__ import annotations

import json

from app.contracts.module_boundary_derivation import (
    ModuleBoundaryDerivationResult,
)
from app.contracts.module_set_simulation import ModuleSetSimulationError, ModuleSetSimulationResult
from app.models.enums import ModuleBoundaryTreatmentType, RunStatus
from app.orchestration import module_set_execution_orchestrator
from app.persistence.module_set import create_draft_from_run, save_draft
from app.persistence.module_set_execution import (
    get_or_create_review,
    persist_candidate_boundary_ports,
    submit_boundary_decision,
    submit_module_set_simulation,
)
from tests.persistence.conftest import make_subproject_id, make_succeeded_hierarchical_run


def _saved_member(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(
        db_session,
        subproject_id=subproject_id,
        leaf_count=1,
        reaction_ids_per_leaf=[["rA1", "rA2"]],
    )
    # `make_succeeded_hierarchical_run` never records a stage-1 input (no orchestrator test
    # needed one before this increment) -- set it directly so `resolve_stage1_inputs` (which
    # every module-set-execution orchestrator function relies on) has something to resolve.
    run.artifact_reference = json.dumps({"stage1_synthetic_source": "/tmp/fake_agent1_view.json"})
    db_session.flush()
    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )
    version = save_draft(session=db_session, draft_id=draft.id, mode="new_set", set_name="Set")
    return subproject_id, version.members[0]


class TestDeriveBoundaryCandidates:
    def test_builds_a_reaction_only_attach_payload_and_persists_candidates(
        self, db_session, monkeypatch
    ):
        project_id = make_subproject_id(db_session)  # any UUID stands in for project_id here
        subproject_id, member = _saved_member(db_session)
        captured = {}

        def _fake_invoke(request):
            captured["request"] = request
            return (
                ModuleBoundaryDerivationResult(
                    contract_version=request.contract_version,
                    run_id=request.run_id,
                    status="SUCCEEDED",
                    module_id=request.module_id,
                    candidates=({"species_id": "AcCoA", "direction": "OUTPUT"},),
                    started_at="t0",
                    completed_at="t1",
                    error=None,
                    summary="ok",
                ),
                None,
            )

        monkeypatch.setattr(
            module_set_execution_orchestrator, "invoke_module_boundary_derivation", _fake_invoke
        )

        created = module_set_execution_orchestrator.derive_boundary_candidates(
            module_set_member=member,
            project_id=project_id,
            subproject_id=subproject_id,
            session=db_session,
        )

        assert len(created) == 1
        assert created[0].species_id == "AcCoA"
        attach = captured["request"].attach_payload
        assert all(m["component_type"] == "REACTION" for m in attach["memberships"])
        assert sorted(m["component_id"] for m in attach["memberships"]) == ["rA1", "rA2"]

    def test_raises_on_harness_client_error(self, db_session, monkeypatch):
        project_id = make_subproject_id(db_session)
        subproject_id, member = _saved_member(db_session)

        class _Err:
            code = "HARNESS_SUBPROCESS_TIMEOUT"
            message = "timed out"

        monkeypatch.setattr(
            module_set_execution_orchestrator,
            "invoke_module_boundary_derivation",
            lambda request: (None, _Err()),
        )

        import pytest

        with pytest.raises(
            module_set_execution_orchestrator.ModuleSetMemberBoundaryDerivationError
        ):
            module_set_execution_orchestrator.derive_boundary_candidates(
                module_set_member=member,
                project_id=project_id,
                subproject_id=subproject_id,
                session=db_session,
            )


class TestProcessOnePendingRun:
    def _ready_run(self, db_session):
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
        run.status = RunStatus.RUNNING
        db_session.flush()
        return run

    def test_a_successful_simulation_completes_the_run_with_the_agent3_report(
        self, db_session, monkeypatch
    ):
        run = self._ready_run(db_session)

        def _fake_invoke(request):
            return (
                ModuleSetSimulationResult(
                    contract_version=request.contract_version,
                    run_id=request.run_id,
                    status="SUCCEEDED",
                    module_id=request.module_id,
                    module_handoff_summary={"reaction_count": 2},
                    lineage={"retained_reaction_ids": ["rA1", "rA2"]},
                    agent3_report={"overall_status": "STEADY_STATE_FOUND"},
                    started_at="t0",
                    completed_at="t1",
                    error=None,
                    summary="ok",
                ),
                None,
            )

        monkeypatch.setattr(
            module_set_execution_orchestrator, "invoke_module_set_simulation", _fake_invoke
        )

        completed = module_set_execution_orchestrator.process_one_pending_run(run, db_session)
        assert completed.status is RunStatus.SUCCEEDED
        result_data = json.loads(completed.artifact_reference)
        assert result_data["agent3_report"]["overall_status"] == "STEADY_STATE_FOUND"
        assert result_data["lineage"]["retained_reaction_ids"] == ["rA1", "rA2"]

    def test_a_harness_reported_failure_completes_the_run_as_failed(self, db_session, monkeypatch):
        run = self._ready_run(db_session)

        def _fake_invoke(request):
            return (
                ModuleSetSimulationResult(
                    contract_version=request.contract_version,
                    run_id=request.run_id,
                    status="FAILED",
                    module_id=request.module_id,
                    module_handoff_summary=None,
                    lineage=None,
                    agent3_report=None,
                    started_at="t0",
                    completed_at="t1",
                    error=ModuleSetSimulationError(
                        code="MODULE_SET_SIMULATION_FAILED", message="no eligible artifact"
                    ),
                    summary="failed",
                ),
                None,
            )

        monkeypatch.setattr(
            module_set_execution_orchestrator, "invoke_module_set_simulation", _fake_invoke
        )

        completed = module_set_execution_orchestrator.process_one_pending_run(run, db_session)
        assert completed.status is RunStatus.FAILED
        assert completed.error_summary == "no eligible artifact"

    def test_a_client_error_completes_the_run_as_failed_never_retried_silently(
        self, db_session, monkeypatch
    ):
        run = self._ready_run(db_session)

        class _Err:
            code = "HARNESS_SUBPROCESS_TIMEOUT"
            message = "timed out"

        monkeypatch.setattr(
            module_set_execution_orchestrator,
            "invoke_module_set_simulation",
            lambda request: (None, _Err()),
        )

        completed = module_set_execution_orchestrator.process_one_pending_run(run, db_session)
        assert completed.status is RunStatus.FAILED
        assert "HARNESS_SUBPROCESS_TIMEOUT" in completed.error_summary
