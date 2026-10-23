"""Background worker for whole-model scenario-evaluation runs (Whole-Model Experimental-
Scenario Evaluation increment).

Mirrors ``scripts/module_set_simulation_worker.py``'s own identical structure and discipline
exactly, pointed at this genuinely separate run kind -- the same disclosed limitation applies
(a run already claimed, ``RUNNING``, when this process is killed outright is not automatically
recovered).

Usage::

    python scripts/calibration_scenario_evaluation_worker.py [--interval SECONDS] [--once]
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from app.db.session import get_sessionmaker  # noqa: E402
from app.orchestration.calibration_scenario_evaluation_orchestrator import (  # noqa: E402
    process_one_pending_run,
)
from app.persistence.calibration_scenario_evaluation import (  # noqa: E402
    claim_next_pending_scenario_evaluation_run,
)

_shutdown_requested = False


def _handle_shutdown_signal(signum: int, frame: object) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    print(
        f"calibration_scenario_evaluation_worker: received signal {signum}, "
        "finishing current run then exiting"
    )


def run_one_iteration() -> bool:
    """Claim and fully process at most one pending run, using its own fresh session --
    independent worker database session, never shared with any other iteration or any API
    request. Returns ``True`` if a run was actually claimed and processed, ``False`` if none
    was waiting."""
    claim_session = get_sessionmaker()()
    try:
        run = claim_next_pending_scenario_evaluation_run(claim_session)
    finally:
        claim_session.close()

    if run is None:
        return False

    process_session = get_sessionmaker()()
    try:
        from app.models.run_record import RunRecord

        run_in_this_session = process_session.get(RunRecord, run.id)
        assert run_in_this_session is not None
        process_one_pending_run(run_in_this_session, process_session)
        process_session.commit()
    except Exception:
        process_session.rollback()
        raise
    finally:
        process_session.close()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds to wait between polls when no run was waiting (default: 5.0).",
    )
    parser.add_argument(
        "--once", action="store_true", help="Process at most one pending run, then exit."
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    if args.once:
        processed = run_one_iteration()
        print(f"calibration_scenario_evaluation_worker: processed_one_run={processed}")
        return 0

    print(
        f"calibration_scenario_evaluation_worker: polling every {args.interval}s (Ctrl-C to stop)"
    )
    while not _shutdown_requested:
        processed = run_one_iteration()
        if _shutdown_requested:
            break
        if not processed:
            time.sleep(args.interval)
    print("calibration_scenario_evaluation_worker: shut down cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
