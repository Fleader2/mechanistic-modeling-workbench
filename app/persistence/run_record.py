"""RunRecord lifecycle: create (PENDING) -> start (RUNNING) -> succeed/fail.

No live agent or harness calls happen here -- this module only records
that a stage ran and what it reported; it never invokes anything itself
(see ``docs/01_workbench_architecture.md``: no inter-agent contract-version
enforcement or orchestration logic lives in the Workbench).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import RunStage, RunStatus
from app.models.run_record import RunRecord


def create_run_record(
    *,
    subproject_id: UUID,
    stage: RunStage,
    session: Session,
    model_id: UUID | None = None,
    model_build_request_id: UUID | None = None,
) -> RunRecord:
    """Create a new ``RunRecord`` in ``PENDING`` status.

    Always creates a new row -- a run history is append-only by nature;
    there is no natural key to deduplicate against (the same stage may
    legitimately run many times for the same subproject).
    """
    row = RunRecord(
        subproject_id=subproject_id,
        model_id=model_id,
        model_build_request_id=model_build_request_id,
        stage=stage,
        status=RunStatus.PENDING,
    )
    session.add(row)
    session.flush()
    return row


def start_run(*, run_record_id: UUID, session: Session) -> RunRecord:
    """Transition a ``RunRecord`` from ``PENDING`` to ``RUNNING``.

    Raises ``ValueError`` if the record is not currently ``PENDING`` -- a
    run is never silently restarted.
    """
    row = session.get(RunRecord, run_record_id)
    if row is None:
        raise ValueError(f"no RunRecord with id {run_record_id}")
    if row.status is not RunStatus.PENDING:
        raise ValueError(f"RunRecord {run_record_id} is {row.status}, not PENDING")
    row.status = RunStatus.RUNNING
    row.started_at = datetime.now(UTC)
    session.flush()
    return row


def pause_run_for_review(
    *,
    run_record_id: UUID,
    session: Session,
    contract_version: str | None = None,
    artifact_reference: str | None = None,
    result_summary: str | None = None,
    warnings: str | None = None,
) -> RunRecord:
    """Transition a ``RunRecord`` from ``RUNNING`` to ``REQUIRES_USER_REVIEW`` (Hierarchical
    Review/Resume increment) -- a non-terminal pause, never ``completed_at``-stamped (the run
    is not done; it is waiting). Raises ``ValueError`` if the record is not currently
    ``RUNNING``.
    """
    row = session.get(RunRecord, run_record_id)
    if row is None:
        raise ValueError(f"no RunRecord with id {run_record_id}")
    if row.status is not RunStatus.RUNNING:
        raise ValueError(f"RunRecord {run_record_id} is {row.status}, not RUNNING")

    row.status = RunStatus.REQUIRES_USER_REVIEW
    row.contract_version = contract_version
    row.artifact_reference = artifact_reference
    row.result_summary = result_summary
    row.warnings = warnings
    session.flush()
    return row


def resume_run(*, run_record_id: UUID, session: Session) -> RunRecord:
    """Transition a ``RunRecord`` from ``REQUIRES_USER_REVIEW`` back to ``RUNNING``
    (Hierarchical Review/Resume increment) -- the identical re-entry point ``start_run`` already
    is for a fresh ``PENDING`` run. Raises ``ValueError`` if the record is not currently
    ``REQUIRES_USER_REVIEW``.
    """
    row = session.get(RunRecord, run_record_id)
    if row is None:
        raise ValueError(f"no RunRecord with id {run_record_id}")
    if row.status is not RunStatus.REQUIRES_USER_REVIEW:
        raise ValueError(f"RunRecord {run_record_id} is {row.status}, not REQUIRES_USER_REVIEW")
    row.status = RunStatus.RUNNING
    session.flush()
    return row


def complete_run(
    *,
    run_record_id: UUID,
    status: RunStatus,
    session: Session,
    contract_version: str | None = None,
    artifact_reference: str | None = None,
    result_summary: str | None = None,
    error_summary: str | None = None,
    warnings: str | None = None,
) -> RunRecord:
    """Transition a ``RunRecord`` to a terminal status (``SUCCEEDED``/``FAILED``).

    Raises ``ValueError`` if ``status`` is not terminal, or the record is
    not currently ``RUNNING``. ``warnings`` (Scoped-Build Support
    increment) is a pre-serialized JSON string -- this function never
    encodes/decodes it, matching ``artifact_reference``'s own
    store-opaque-string policy.
    """
    if status not in (RunStatus.SUCCEEDED, RunStatus.FAILED):
        raise ValueError(f"complete_run requires a terminal status, got {status!r}")
    row = session.get(RunRecord, run_record_id)
    if row is None:
        raise ValueError(f"no RunRecord with id {run_record_id}")
    if row.status is not RunStatus.RUNNING:
        raise ValueError(f"RunRecord {run_record_id} is {row.status}, not RUNNING")

    row.status = status
    row.completed_at = datetime.now(UTC)
    row.contract_version = contract_version
    row.artifact_reference = artifact_reference
    row.result_summary = result_summary
    row.error_summary = error_summary
    row.warnings = warnings
    session.flush()
    return row


def get_run_record(session: Session, run_record_id: UUID) -> RunRecord | None:
    """One ``RunRecord`` row by id, or ``None``. Read-only."""
    return session.get(RunRecord, run_record_id)


def resolve_stage1_inputs(run_record: RunRecord) -> tuple[str | None, str | None]:
    """The hierarchy run's own original stage-1 input (``agent1_organism_id``,
    ``stage1_synthetic_source``), recorded in its own ``artifact_reference`` JSON by
    ``app.orchestration.hierarchical_run_orchestrator.persist_result_and_transition``.

    Shared by every module-scoped operation that needs to re-invoke the harness against the
    same root model a hierarchy run was originally searched against
    (``app.orchestration.model_module_orchestrator``/``module_boundary_orchestrator``) --
    never duplicated between them. Raises ``ValueError`` if neither was ever recorded (a
    run_record predating this increment, or one whose own artifact_reference was never
    written)."""
    if not run_record.artifact_reference:
        raise ValueError(
            f"RunRecord {run_record.id} has no recorded stage-1 input to reuse for a "
            "module-scoped operation"
        )
    try:
        data = json.loads(run_record.artifact_reference)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(
            f"RunRecord {run_record.id}'s own artifact_reference could not be parsed: {exc!r}"
        ) from exc
    organism_id = data.get("agent1_organism_id")
    synthetic_source = data.get("stage1_synthetic_source")
    if organism_id is None and synthetic_source is None:
        raise ValueError(
            f"RunRecord {run_record.id} has no recorded stage-1 input to reuse for a "
            "module-scoped operation"
        )
    return organism_id, synthetic_source


__all__ = [
    "complete_run",
    "create_run_record",
    "get_run_record",
    "pause_run_for_review",
    "resolve_stage1_inputs",
    "resume_run",
    "start_run",
]
