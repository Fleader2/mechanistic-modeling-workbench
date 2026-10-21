"""Tests the documented, safe stuck-run recovery procedure (``scripts
.recover_stuck_module_set_runs``) end-to-end against real, independently-committing sessions --
the same durability discipline as ``tests/api/test_module_set_execution_durability.py``'s own
``TestWorkerCrashRecoveryIsDisclosedNotAutomatic``, which proves the *problem* this recovers
from. Every assertion here re-queries through a brand-new session after the acting call
returns, so recovery's own writes cannot hide behind a shared test transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.models.enums import RunStatus
from app.orchestration.module_set_execution_orchestrator import (
    _complete_run_unless_already_terminalized,
)
from app.persistence.module_set_execution import claim_next_pending_module_set_run
from scripts.recover_stuck_module_set_runs import (
    RECOVERY_ERROR_SUMMARY,
    find_stuck_runs,
)
from scripts.recover_stuck_module_set_runs import (
    main as recovery_main,
)
from tests.api.test_module_set_durability import real_client, real_session_app  # noqa: F401
from tests.api.test_module_set_execution_durability import (
    _fake_boundary_derivation_success,
    _query_scalar,
    _save_new_set,
    _seed_saved_member,
)
from tests.conftest import reset_test_database


@pytest.fixture(autouse=True)
def _clean_database_before_and_after(
    alembic_config: Config, migrated_engine: Engine
) -> None:
    del migrated_engine
    reset_test_database(alembic_config)
    yield
    reset_test_database(alembic_config)


def _submit_and_claim_one_run(
    migrated_engine: Engine, real_client, module_set_execution_orchestrator, monkeypatch  # noqa: F811
) -> tuple[str, str]:
    """Seeds a saved member, derives/decides its boundary review, submits a simulation, and
    claims it (``PENDING`` -> ``RUNNING``) without ever processing it -- the exact state a
    killed worker leaves behind. Returns (run_id, member_base_url)."""
    project_id, subproject_id, run_record_id, _module_id = _seed_saved_member(migrated_engine)
    saved = _save_new_set(real_client, project_id, subproject_id, run_record_id)
    member_id = saved["members"][0]["id"]
    member_base = (
        f"/api/v1/projects/{project_id}/subprojects/{subproject_id}/module-sets/"
        f"{saved['module_set_id']}/versions/1/members/{member_id}"
    )

    monkeypatch.setattr(
        module_set_execution_orchestrator,
        "invoke_module_boundary_derivation",
        _fake_boundary_derivation_success([{"species_id": "AcCoA", "direction": "OUTPUT"}]),
    )
    real_client.post(f"{member_base}/boundary-review/derive")
    port_id = _query_scalar(
        migrated_engine,
        "SELECT p.id FROM module_set_member_boundary_port p "
        "JOIN module_set_member_review r ON r.id = p.review_id "
        "WHERE r.module_set_member_id = :member_id AND p.species_id = 'AcCoA'",
        member_id=member_id,
    )
    real_client.post(
        f"{member_base}/boundary-review/ports/{port_id}/decision",
        json={
            "expected_review_version": 0,
            "treatment_type": "EXTERNALLY_CONTROLLED",
            "initial_value": "1.0",
            "unit": "mM",
        },
    )
    submitted = real_client.post(
        f"{member_base}/simulations", json={"expected_review_version": 1}
    ).json()
    run_id = submitted["id"]

    claim_session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    try:
        claimed = claim_next_pending_module_set_run(claim_session)
        assert claimed is not None
        assert str(claimed.id) == run_id
    finally:
        claim_session.close()

    return run_id, member_base


def _backdate_started_at(migrated_engine: Engine, run_id: str, age_seconds: float) -> None:
    session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    try:
        session.execute(
            text("UPDATE run_record SET started_at = :started_at WHERE id = :id"),
            {
                "started_at": datetime.now(UTC) - timedelta(seconds=age_seconds),
                "id": run_id,
            },
        )
        session.commit()
    finally:
        session.close()


class TestFindStuckRuns:
    def test_only_returns_runs_older_than_the_threshold(
        self, migrated_engine: Engine, real_client, monkeypatch  # noqa: F811
    ) -> None:
        from app.orchestration import module_set_execution_orchestrator

        stuck_run_id, _ = _submit_and_claim_one_run(
            migrated_engine, real_client, module_set_execution_orchestrator, monkeypatch
        )
        _backdate_started_at(migrated_engine, stuck_run_id, age_seconds=1000)

        fresh_run_id, _ = _submit_and_claim_one_run(
            migrated_engine, real_client, module_set_execution_orchestrator, monkeypatch
        )
        # fresh_run_id's started_at is "now" -- well inside the 900s default threshold.

        session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
        try:
            stuck = find_stuck_runs(session, max_age_seconds=900.0)
        finally:
            session.close()

        stuck_ids = {str(run.id) for run in stuck}
        assert stuck_ids == {stuck_run_id}
        assert fresh_run_id not in stuck_ids


class TestRecoveryCli:
    def test_dry_run_lists_without_mutating_anything(
        self, migrated_engine: Engine, real_client, monkeypatch, capsys  # noqa: F811
    ) -> None:
        from app.orchestration import module_set_execution_orchestrator

        run_id, _ = _submit_and_claim_one_run(
            migrated_engine, real_client, module_set_execution_orchestrator, monkeypatch
        )
        _backdate_started_at(migrated_engine, run_id, age_seconds=1000)

        monkeypatch.setattr("sys.argv", ["recover_stuck_module_set_runs.py"])
        exit_code = recovery_main()
        assert exit_code == 0

        printed = capsys.readouterr().out
        assert run_id in printed
        assert "dry-run only" in printed

        status_value = _query_scalar(
            migrated_engine, "SELECT status FROM run_record WHERE id = :id", id=run_id
        )
        assert status_value == "RUNNING"

    def test_confirm_marks_the_stuck_run_failed_durably_and_unblocks_resubmission(
        self, migrated_engine: Engine, real_client, monkeypatch  # noqa: F811
    ) -> None:
        from app.orchestration import module_set_execution_orchestrator

        run_id, member_base = _submit_and_claim_one_run(
            migrated_engine, real_client, module_set_execution_orchestrator, monkeypatch
        )
        _backdate_started_at(migrated_engine, run_id, age_seconds=1000)

        # Before recovery: resubmitting is correctly blocked by the duplicate-active-run guard.
        blocked = real_client.post(
            f"{member_base}/simulations", json={"expected_review_version": 1}
        )
        assert blocked.status_code == 409

        monkeypatch.setattr("sys.argv", ["recover_stuck_module_set_runs.py", "--confirm"])
        exit_code = recovery_main()
        assert exit_code == 0

        with Session(bind=migrated_engine, autoflush=False, expire_on_commit=False) as session:
            status_value, error_summary = session.execute(
                text("SELECT status, error_summary FROM run_record WHERE id = :id"), {"id": run_id}
            ).one()
        assert status_value == "FAILED"
        assert error_summary == RECOVERY_ERROR_SUMMARY

        # After recovery: the recovered run is no longer "active", so a fresh, legitimate
        # resubmission for the same member succeeds -- never a duplicate harness execution,
        # since recovery itself never called the harness at all.
        resubmitted = real_client.post(
            f"{member_base}/simulations", json={"expected_review_version": 1}
        )
        assert resubmitted.status_code == 201
        assert resubmitted.json()["id"] != run_id

        runs = real_client.get(f"{member_base}/simulations").json()
        assert {run["id"] for run in runs} == {run_id, resubmitted.json()["id"]}

    def test_a_fresh_running_run_is_left_untouched_even_when_confirmed(
        self, migrated_engine: Engine, real_client, monkeypatch  # noqa: F811
    ) -> None:
        from app.orchestration import module_set_execution_orchestrator

        run_id, _ = _submit_and_claim_one_run(
            migrated_engine, real_client, module_set_execution_orchestrator, monkeypatch
        )
        # No backdating -- this run is genuinely fresh.

        monkeypatch.setattr("sys.argv", ["recover_stuck_module_set_runs.py", "--confirm"])
        exit_code = recovery_main()
        assert exit_code == 0

        status_value = _query_scalar(
            migrated_engine, "SELECT status FROM run_record WHERE id = :id", id=run_id
        )
        assert status_value == "RUNNING"


class TestCompleteRunUnlessAlreadyTerminalized:
    """Direct tests of the race-safety helper every ``process_one_pending_run`` completion now
    goes through -- proves a worker that was not actually dead, finishing mid-flight on a run
    recovery already force-failed, can never overwrite that recovery with a conflicting result.
    """

    def test_completes_normally_when_the_run_is_still_running(
        self, migrated_engine: Engine, real_client, monkeypatch  # noqa: F811
    ) -> None:
        from app.orchestration import module_set_execution_orchestrator

        run_id, _ = _submit_and_claim_one_run(
            migrated_engine, real_client, module_set_execution_orchestrator, monkeypatch
        )
        session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
        try:
            result = _complete_run_unless_already_terminalized(
                run_id, session, status=RunStatus.SUCCEEDED, result_summary="genuinely finished"
            )
            session.commit()
            assert result.status is RunStatus.SUCCEEDED
            assert result.result_summary == "genuinely finished"
        finally:
            session.close()

    def test_discards_its_own_result_instead_of_overwriting_a_run_already_terminalized(
        self, migrated_engine: Engine, real_client, monkeypatch  # noqa: F811
    ) -> None:
        from app.orchestration import module_set_execution_orchestrator

        run_id, _ = _submit_and_claim_one_run(
            migrated_engine, real_client, module_set_execution_orchestrator, monkeypatch
        )
        _backdate_started_at(migrated_engine, run_id, age_seconds=1000)

        # Recovery wins the race first.
        monkeypatch.setattr("sys.argv", ["recover_stuck_module_set_runs.py", "--confirm"])
        recovery_main()

        # The "not actually dead" worker's own harness call finishes afterward and tries to
        # write a conflicting SUCCEEDED result -- it must be discarded, not written over
        # recovery's FAILED.
        session = Session(bind=migrated_engine, autoflush=False, expire_on_commit=False)
        try:
            result = _complete_run_unless_already_terminalized(
                run_id,
                session,
                status=RunStatus.SUCCEEDED,
                result_summary="late result from a worker that was not actually dead",
            )
            session.commit()
            assert result.status is RunStatus.FAILED
            assert result.error_summary == RECOVERY_ERROR_SUMMARY
            assert result.result_summary != "late result from a worker that was not actually dead"
        finally:
            session.close()

        # And durably so, from a third, fully independent session.
        with Session(bind=migrated_engine, autoflush=False, expire_on_commit=False) as session:
            status_value, result_summary = session.execute(
                text("SELECT status, result_summary FROM run_record WHERE id = :id"), {"id": run_id}
            ).one()
        assert status_value == "FAILED"
        assert result_summary != "late result from a worker that was not actually dead"
