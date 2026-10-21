"""Background worker for module-set-scoped simulation runs (Module-Set Edited-Module
Materialization increment, Phase B).

Every other harness call in this codebase runs synchronously, inline within the HTTP request
that triggers it -- the first increment in this project's history to need a real background
job, per this increment's own explicit instruction ("do not hold an HTTP request open for the
full computation"). This is the smallest reliable *local* solution that satisfies it: a plain
polling loop, run as a separate process, with its own fresh database session per iteration
(never the same session an API request used, and never held open across iterations).

Usage::

    python scripts/module_set_simulation_worker.py [--interval SECONDS] [--once]

``--once`` processes at most one pending run and exits -- used by tests and by the live-
verification walkthrough, so a run completes deterministically without needing a persistent
background process. Without it, the worker polls forever until interrupted (SIGINT/SIGTERM),
finishing whatever run it is currently processing before exiting -- a run already claimed
(``RUNNING``) when the process is killed outright (``SIGKILL``, a crash, a machine restart)
is **not** automatically recovered: it stays durably ``RUNNING`` with no worker left making
progress on it. This is a disclosed limitation of "smallest reliable local solution," not an
oversight -- see docs/24_module_set_execution_increment.md's own "Restart/interruption
behavior" section for exactly what recovering a stuck run requires today (an operator
re-queues it by hand; no automatic lease/heartbeat/timeout mechanism exists in this
increment).
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
from app.orchestration.module_set_execution_orchestrator import (  # noqa: E402
    process_one_pending_run,
)
from app.persistence.module_set_execution import claim_next_pending_module_set_run  # noqa: E402

_shutdown_requested = False


def _handle_shutdown_signal(signum: int, frame: object) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    print(
        f"module_set_simulation_worker: received signal {signum}, "
        "finishing current run then exiting"
    )


def run_one_iteration() -> bool:
    """Claim and fully process at most one pending run, using its own fresh session --
    **independent worker database session**, never shared with any other iteration or any API
    request. Returns ``True`` if a run was actually claimed and processed, ``False`` if none
    was waiting."""
    claim_session = get_sessionmaker()()
    try:
        run = claim_next_pending_module_set_run(claim_session)
    finally:
        claim_session.close()

    if run is None:
        return False

    process_session = get_sessionmaker()()
    try:
        # Re-fetch `run` in this fresh session -- the claim above already committed the
        # PENDING -> RUNNING transition, so this session sees it durably.
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
        print(f"module_set_simulation_worker: processed_one_run={processed}")
        return 0

    print(f"module_set_simulation_worker: polling every {args.interval}s (Ctrl-C to stop)")
    while not _shutdown_requested:
        processed = run_one_iteration()
        if _shutdown_requested:
            break
        if not processed:
            time.sleep(args.interval)
    print("module_set_simulation_worker: shut down cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
