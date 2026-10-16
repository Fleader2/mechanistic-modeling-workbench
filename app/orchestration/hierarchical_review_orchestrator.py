"""Hierarchical Review/Resume: the service layer a caller (eventually a UI, for now a script or
test) uses to inspect pending review items, submit decisions, resume a paused hierarchical-
recursion run through the harness, and read back status/final results.

No scientific logic lives here: every decision about which modules to accept/reject and why is
made entirely inside the harness's own ``app.harness.hierarchical_recursion`` package. This
module only moves a ``RunRecord`` through its own state machine, stores the harness's own
checkpoint/node data verbatim, and enforces the Workbench's own review-workflow invariants
(every pending item must be decided before a resume; a consumed checkpoint can never be resumed
again).

**Crash-Safe Resume increment.** ``resume_hierarchical_run`` is a deliberate, disclosed
exception to this repository's general "the caller commits" convention
(``app.db.session.get_session``'s own docstring): it owns two explicit transaction boundaries
of its own, because it is the one operation in this codebase that spans a slow (up to several
minutes), externally-idempotent subprocess call. See ``docs/06_crash_safe_resume.md`` for the
full rationale; in short:

1. Validate, then durably commit a ``HierarchyResumeAttempt`` row as ``IN_PROGRESS`` *before*
   invoking the harness -- so a crash during the subprocess call always leaves a truthful,
   recoverable trail (the attempt, never the checkpoint/run itself) behind.
2. Invoke the harness and persist its result, consume the prior checkpoint, and mark the
   attempt ``SUCCEEDED`` -- all in one second, all-or-nothing transaction, committed only on
   full success. Any failure (the harness call itself, or anything after it) rolls that second
   transaction back in full and durably marks the attempt ``FAILED`` instead, leaving the
   checkpoint untouched and reusable by a later retry.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.hierarchical_recursion import (
    RESUME_CONTRACT_VERSION,
    HierarchicalResumeRequest,
    HierarchicalRunStatus,
)
from app.models.enums import (
    HierarchyResumeAttemptStatus,
    HierarchyReviewDecisionValue,
    RunStatus,
)
from app.models.hierarchy_checkpoint import HierarchyCheckpoint
from app.models.hierarchy_node import HierarchyNode
from app.models.hierarchy_pending_review_item import HierarchyPendingReviewItem
from app.models.hierarchy_resume_attempt import HierarchyResumeAttempt
from app.models.hierarchy_review_decision import HierarchyReviewDecision
from app.models.run_record import RunRecord
from app.orchestration.hierarchical_harness_client import invoke_hierarchical_harness_resume
from app.orchestration.hierarchical_run_orchestrator import persist_result_and_transition
from app.persistence.hierarchy_checkpoint import (
    get_current_checkpoint_for_run,
    mark_checkpoint_consumed,
)
from app.persistence.hierarchy_node import list_hierarchy_nodes_for_run
from app.persistence.hierarchy_pending_review_item import (
    get_pending_review_item,
    list_pending_review_items_for_checkpoint,
)
from app.persistence.hierarchy_resume_attempt import (
    get_attempt_for_checkpoint,
    get_or_create_resume_attempt,
    is_attempt_stale,
    mark_attempt_failed,
    mark_attempt_in_progress,
    mark_attempt_succeeded,
)
from app.persistence.hierarchy_review_decision import get_decision_for_item
from app.persistence.hierarchy_review_decision import submit_review_decision as _persist_decision
from app.persistence.run_record import get_run_record, resume_run


class StaleCheckpointError(ValueError):
    """Raised when an operation targets a ``HierarchyCheckpoint`` that has already been
    consumed by a prior resume -- the review/resume workflow's own explicit "stale" failure
    mode (task requirement: "invalid/stale review submissions should fail clearly")."""


class ResumeAttemptInProgressError(ValueError):
    """Raised when ``resume_hierarchical_run`` is called while a *not-yet-stale*
    ``HierarchyResumeAttempt`` for the current checkpoint is already ``IN_PROGRESS`` -- a
    genuinely concurrent resume call, never silently allowed to race the one already running.
    A *stale* ``IN_PROGRESS`` attempt (see ``app.persistence.hierarchy_resume_attempt
    .is_attempt_stale``) is retried instead of raising this.
    """


class _HarnessResumeCallFailed(Exception):
    """Internal-only signal: the harness resume call did not produce a durably-persistable
    success (either a client-level error, or a cleanly-parsed but non-``SUCCEEDED`` result).
    Caught by ``resume_hierarchical_run`` itself, which rolls back and marks the attempt
    ``FAILED`` -- never propagated to a caller."""


def get_hierarchical_run_status(
    session: Session, run_record_id: UUID
) -> tuple[RunRecord, list[HierarchyNode]]:
    """One run's own ``RunRecord`` plus its full, depth-first-ordered ``HierarchyNode`` set so
    far (whatever has actually completed, regardless of the run's own current status). Raises
    ``ValueError`` if the run does not exist. Read-only."""
    run_record = get_run_record(session, run_record_id)
    if run_record is None:
        raise ValueError(f"no RunRecord with id {run_record_id}")
    nodes = list_hierarchy_nodes_for_run(session, run_record_id)
    return run_record, nodes


def list_pending_review_items(
    session: Session, run_record_id: UUID
) -> list[HierarchyPendingReviewItem]:
    """The run's own current, still-resumable pending-review items -- ``[]`` if the run has
    never paused, or if its current checkpoint has already been consumed by a resume. Raises
    ``ValueError`` if the run does not exist. Read-only."""
    run_record = get_run_record(session, run_record_id)
    if run_record is None:
        raise ValueError(f"no RunRecord with id {run_record_id}")
    checkpoint = get_current_checkpoint_for_run(session, run_record_id)
    if checkpoint is None or checkpoint.consumed_at is not None:
        return []
    return list_pending_review_items_for_checkpoint(session, checkpoint.id)


def submit_review_decision(
    *,
    pending_review_item_id: UUID,
    decision: HierarchyReviewDecisionValue,
    session: Session,
    decided_by: str | None = None,
    notes: str | None = None,
) -> HierarchyReviewDecision:
    """Record one APPROVE/REJECT decision for one pending review item.

    Raises ``ValueError`` if the item does not exist, or if a decision already exists for it
    with a *different* value (resubmitting the identical value is an idempotent no-op -- see
    ``app.persistence.hierarchy_review_decision.submit_review_decision``). Raises
    ``StaleCheckpointError`` if the item's own checkpoint has already been consumed by a resume
    -- its decision can no longer affect anything.
    """
    item = get_pending_review_item(session, pending_review_item_id)
    if item is None:
        raise ValueError(f"no HierarchyPendingReviewItem with id {pending_review_item_id}")
    checkpoint = session.get(HierarchyCheckpoint, item.hierarchy_checkpoint_id)
    if checkpoint is not None and checkpoint.consumed_at is not None:
        raise StaleCheckpointError(
            f"HierarchyPendingReviewItem {pending_review_item_id} belongs to checkpoint "
            f"{item.hierarchy_checkpoint_id}, which was already consumed by a resume -- this "
            "decision can no longer be submitted"
        )
    return _persist_decision(
        pending_review_item_id=pending_review_item_id,
        decision=decision,
        session=session,
        decided_by=decided_by,
        notes=notes,
    )


def get_resume_attempt_status(
    session: Session, run_record_id: UUID
) -> HierarchyResumeAttempt | None:
    """The run's own current checkpoint's resume attempt, or ``None`` if the run has never
    paused. Read-only -- lets a caller inspect ``status``/``attempt_count``/``error_summary``
    without needing to know this module's own internal checkpoint-lookup plumbing."""
    checkpoint = get_current_checkpoint_for_run(session, run_record_id)
    if checkpoint is None:
        return None
    return get_attempt_for_checkpoint(session, checkpoint.id)


def resume_hierarchical_run(
    *,
    run_record_id: UUID,
    session: Session,
    correlation_id: str | None = None,
    notes: str | None = None,
) -> RunRecord:
    """Resume one paused (``REQUIRES_USER_REVIEW``) hierarchical-recursion run through the
    harness's own resume canonical entrypoint -- crash-safely (see this module's own docstring).

    Every current pending-review item must already have exactly one decision recorded (via
    ``submit_review_decision``) -- raises ``ValueError`` naming the first undecided one
    otherwise, never silently defaulting a missing decision. Raises ``ValueError`` if the run
    is not currently ``REQUIRES_USER_REVIEW``.

    Idempotency/retry:

    * If the current checkpoint was already consumed by a *successful* attempt, this call
      returns the current (already-advanced) ``RunRecord`` unchanged -- a true repeat of an
      already-completed resume, resolved to the same logical result rather than erroring.
      Raises ``StaleCheckpointError`` for a consumed checkpoint with no matching successful
      attempt (an inconsistent state that should never occur).
    * If a *not-yet-stale* attempt is already ``IN_PROGRESS``, raises
      ``ResumeAttemptInProgressError`` -- a genuinely concurrent call, never raced.
    * If the current attempt is ``FAILED``, or ``IN_PROGRESS`` but stale (see
      ``app.persistence.hierarchy_resume_attempt.is_attempt_stale``), this call retries it: the
      harness is invoked again with the identical, deterministic ``run_id`` (keyed by
      checkpoint sequence, not attempt count), so the harness's *own* idempotent-replay-by-
      ``run_id`` cache returns the identical result without re-running real Agent 2 work.
    """
    run_record = get_run_record(session, run_record_id)
    if run_record is None:
        raise ValueError(f"no RunRecord with id {run_record_id}")

    checkpoint = get_current_checkpoint_for_run(session, run_record_id)
    if checkpoint is None:
        raise ValueError(f"RunRecord {run_record_id} has no checkpoint to resume from")

    existing_attempt = get_attempt_for_checkpoint(session, checkpoint.id)

    if checkpoint.consumed_at is not None:
        if (
            existing_attempt is not None
            and existing_attempt.status is HierarchyResumeAttemptStatus.SUCCEEDED
        ):
            return run_record  # idempotent repeat of an already-completed resume
        raise StaleCheckpointError(
            f"HierarchyCheckpoint {checkpoint.id} (run {run_record_id}) was already consumed "
            "by a prior resume attempt"
        )

    if run_record.status is not RunStatus.REQUIRES_USER_REVIEW:
        raise ValueError(
            f"RunRecord {run_record_id} is {run_record.status}, not REQUIRES_USER_REVIEW"
        )

    if (
        existing_attempt is not None
        and existing_attempt.status is HierarchyResumeAttemptStatus.IN_PROGRESS
        and not is_attempt_stale(existing_attempt)
    ):
        raise ResumeAttemptInProgressError(
            f"HierarchyCheckpoint {checkpoint.id} already has a resume attempt in progress "
            f"(started {existing_attempt.started_at.isoformat()}) -- not yet stale, refusing "
            "to race it"
        )
    # else: no attempt, not in progress, or stale -- fall through and (re)try below.

    pending_items = list_pending_review_items_for_checkpoint(session, checkpoint.id)
    if not pending_items:
        raise ValueError(f"HierarchyCheckpoint {checkpoint.id} has no pending review items")

    decisions: dict[str, str] = {}
    for item in pending_items:
        decision_row = get_decision_for_item(session, item.id)
        if decision_row is None:
            raise ValueError(
                f"pending review item {item.pending_id!r} (id {item.id}) has not been decided "
                "yet -- every pending item must be decided before resuming"
            )
        decisions[item.pending_id] = decision_row.decision.value

    # --- Phase 1: durably commit IN_PROGRESS before the (possibly multi-minute) harness call.
    # A crash anywhere after this point and before phase 2's own commit leaves exactly this --
    # never a half-persisted result -- durably on disk.
    attempt = get_or_create_resume_attempt(hierarchy_checkpoint_id=checkpoint.id, session=session)
    attempt = mark_attempt_in_progress(attempt.id, session, force=True)
    session.commit()

    resume_request = HierarchicalResumeRequest(
        contract_version=RESUME_CONTRACT_VERSION,
        run_id=f"{run_record_id}::resume::{checkpoint.sequence}",
        checkpoint=json.loads(checkpoint.payload),
        decisions=decisions,
        correlation_id=correlation_id,
        notes=notes,
        submitted_at=datetime.now(UTC).isoformat(),
    )

    # --- Phase 2: invoke the harness and persist everything, all-or-nothing.
    try:
        result, client_error = invoke_hierarchical_harness_resume(resume_request)
        if client_error is not None:
            raise _HarnessResumeCallFailed(f"{client_error.code}: {client_error.message}")
        assert result is not None  # invoke_hierarchical_harness_resume's own contract
        if result.status is not HierarchicalRunStatus.SUCCEEDED:
            error_message = result.summary if result.error is None else result.error.message
            raise _HarnessResumeCallFailed(error_message)

        resume_run(run_record_id=run_record_id, session=session)
        updated_run_record = persist_result_and_transition(
            run_record_id=run_record_id, result=result, session=session
        )
        mark_checkpoint_consumed(session, checkpoint.id)
        mark_attempt_succeeded(attempt.id, session)
        session.commit()
        return updated_run_record
    except _HarnessResumeCallFailed as exc:
        session.rollback()
        mark_attempt_failed(attempt.id, session, error_summary=str(exc))
        session.commit()
        return get_run_record(session, run_record_id)
    except Exception as exc:
        session.rollback()
        mark_attempt_failed(attempt.id, session, error_summary=f"unexpected error: {exc!r}")
        session.commit()
        raise


def get_final_hierarchy(session: Session, run_record_id: UUID) -> list[HierarchyNode]:
    """The run's own complete, accepted hierarchy -- every ``HierarchyNode`` row, depth-first
    ordered. Raises ``ValueError`` if the run does not exist or has not reached ``SUCCEEDED``
    yet (a paused or still-running run has no *final* hierarchy; use
    ``get_hierarchical_run_status`` for the in-progress node set). Read-only.
    """
    run_record = get_run_record(session, run_record_id)
    if run_record is None:
        raise ValueError(f"no RunRecord with id {run_record_id}")
    if run_record.status is not RunStatus.SUCCEEDED:
        raise ValueError(
            f"RunRecord {run_record_id} is {run_record.status}, not SUCCEEDED -- the final "
            "hierarchy is only available for a completed run"
        )
    return list_hierarchy_nodes_for_run(session, run_record_id)


__all__ = [
    "ResumeAttemptInProgressError",
    "StaleCheckpointError",
    "get_final_hierarchy",
    "get_hierarchical_run_status",
    "get_resume_attempt_status",
    "list_pending_review_items",
    "resume_hierarchical_run",
    "submit_review_decision",
]
