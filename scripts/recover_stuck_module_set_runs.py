"""Manual recovery for module-set simulation runs left stuck ``RUNNING`` by a dead worker
(Module-Set Edited-Module Materialization increment, Phase B).

``scripts/module_set_simulation_worker.py`` has no lease/heartbeat/timeout mechanism: if the
worker process is killed outright (SIGKILL, crash, machine restart) while it holds a run
``RUNNING``, that run stays durably ``RUNNING`` forever with nothing left making progress on
it -- a disclosed limitation, not an oversight (see docs/24_module_set_execution_increment.md).
This script is the documented, *tested* safe procedure for recovering from that, without ever
causing a duplicate harness execution or leaving a permanently misleading ``RUNNING`` state.

**Why a simple age threshold is safe here, specifically.** The worker's own harness client
(``module_set_simulation_harness_client``) already bounds every real in-flight call to 600
seconds via its own subprocess timeout -- a run whose owning worker process is still alive
either finishes within that window or itself transitions the run to ``FAILED`` on timeout. So
a run still ``RUNNING`` well past that window is not "maybe still working, maybe not": its
owning worker process is gone. The default ``--max-age-seconds`` (900) is that 600s client
timeout plus a deliberate safety margin, not a guess.

**Why recovery can never cause a duplicate execution.** This script never calls the harness --
it only flips a ``RunRecord``'s own status in the database (reusing ``complete_run``, the
identical function the worker itself uses, with its own identical "must currently be RUNNING"
precondition). The one race this leaves -- a worker that was not actually dead, still mid-flight
on a run this script just force-failed as presumed-crashed -- is closed on the worker's own side
(``_complete_run_unless_already_terminalized`` in ``app.orchestration
.module_set_execution_orchestrator``): when that worker's harness call eventually returns, it
re-checks the row's current status before writing, sees it is no longer ``RUNNING``, and
discards its own result rather than overwriting what this script already wrote. Exactly one of
the two writers -- whichever gets there first -- ever terminalizes the run; the other's result is
silently dropped, never conflictingly written. A false-positive recovery (the worker was in fact
about to succeed) therefore costs a discarded result, never a duplicate or corrupted one -- which
is why this script is read-only (dry-run) unless ``--confirm`` is passed, and always prints
exactly which runs it is about to act on first.

**Why this never leaves a permanently misleading state.** Every candidate this script acts on
is moved to the terminal ``FAILED`` status with an explanatory ``error_summary`` -- never left
``RUNNING``, and never silently deleted. The scientist sees a real, accounted-for failure (not
a result that is still "in progress" forever), and -- because ``FAILED`` is no longer an
*active* status -- ``submit_module_set_simulation``'s own duplicate-active-run guard no longer
blocks a fresh, legitimate resubmission for the same module-set member.

Usage::

    python scripts/recover_stuck_module_set_runs.py [--max-age-seconds 900]
    python scripts/recover_stuck_module_set_runs.py --confirm [--max-age-seconds 900]

Without ``--confirm``: lists every candidate (run id, module-set member id, started_at, age in
seconds) and writes nothing. With ``--confirm``: does the same listing, then transitions each
one to ``FAILED``, each in its own committed transaction (one candidate's failure to recover --
e.g. a concurrent legitimate completion -- never blocks recovering the others).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import get_sessionmaker  # noqa: E402
from app.models.enums import RunStatus  # noqa: E402
from app.models.run_record import RunRecord  # noqa: E402
from app.orchestration.module_set_execution_orchestrator import (  # noqa: E402
    _complete_run_unless_already_terminalized,
)

#: The worker's own harness client bounds any real in-flight call to 600s -- see this module's
#: own docstring for why a run RUNNING well past that means its owning worker is gone, not
#: "maybe still working."
DEFAULT_MAX_AGE_SECONDS = 900.0

RECOVERY_ERROR_SUMMARY = (
    "recovered: run exceeded the worker's own harness-call timeout without completing "
    "(its owning worker process is presumed dead -- crashed, killed, or the machine "
    "restarted); marked FAILED by scripts/recover_stuck_module_set_runs.py. Resubmit a new "
    "simulation for this module-set member to retry."
)


def find_stuck_runs(session, *, max_age_seconds: float) -> list[RunRecord]:
    """Every module-set-scoped run still ``RUNNING`` whose ``started_at`` is more than
    ``max_age_seconds`` in the past -- oldest first. Read-only."""
    now = datetime.now(UTC)
    candidates = session.execute(
        select(RunRecord)
        .where(
            RunRecord.module_set_member_id.is_not(None),
            RunRecord.status == RunStatus.RUNNING,
        )
        .order_by(RunRecord.started_at.asc())
    ).scalars()
    stuck = []
    for run in candidates:
        assert run.started_at is not None  # RUNNING always sets started_at
        age_seconds = (now - run.started_at).total_seconds()
        if age_seconds > max_age_seconds:
            stuck.append(run)
    return stuck


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-age-seconds",
        type=float,
        default=DEFAULT_MAX_AGE_SECONDS,
        help=f"Only act on runs RUNNING longer than this (default: {DEFAULT_MAX_AGE_SECONDS}).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually mark the listed runs FAILED. Without this flag, only lists them.",
    )
    args = parser.parse_args()

    session = get_sessionmaker()()
    try:
        stuck = find_stuck_runs(session, max_age_seconds=args.max_age_seconds)
        if not stuck:
            print(f"no RUNNING module-set run is older than {args.max_age_seconds}s; nothing to do")
            return 0

        now = datetime.now(UTC)
        for run in stuck:
            age_seconds = (now - run.started_at).total_seconds()
            print(
                f"run={run.id} module_set_member={run.module_set_member_id} "
                f"started_at={run.started_at.isoformat()} age_seconds={age_seconds:.0f}"
            )

        if not args.confirm:
            print(
                f"\n{len(stuck)} stuck run(s) listed above, dry-run only -- "
                "re-run with --confirm to mark them FAILED"
            )
            return 0

        recovered = 0
        for run in stuck:
            result = _complete_run_unless_already_terminalized(
                run.id,
                session,
                status=RunStatus.FAILED,
                error_summary=RECOVERY_ERROR_SUMMARY,
            )
            session.commit()
            if result.status is RunStatus.FAILED and result.error_summary == RECOVERY_ERROR_SUMMARY:
                recovered += 1
                print(f"run={run.id}: marked FAILED")
            else:
                print(f"run={run.id}: already {result.status.value} -- left as-is, not overwritten")
        print(f"\nrecovered {recovered}/{len(stuck)} stuck run(s)")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
