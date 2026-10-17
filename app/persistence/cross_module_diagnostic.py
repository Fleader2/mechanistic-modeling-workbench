"""CrossModuleDiagnosticRun/CrossModuleDiagnostic persistence: create (once per fingerprint,
immutably) and read back one hierarchy run's own cross-module consistency sweep, and its
individual findings -- plus the one deliberate, narrowly-scoped exception: marking a finding
reviewed.

No scientific/comparison logic lives here (that is
``app.orchestration.cross_module_diagnostics_orchestrator``'s own job) -- this module only
persists already-computed findings and enforces this table pair's own two rules: a run is
never duplicated for an unchanged input fingerprint, and a finding's own detection content is
never updated by anything except the dedicated review-marking function.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cross_module_diagnostic import CrossModuleDiagnostic, CrossModuleDiagnosticRun
from app.models.enums import (
    CrossModuleDiagnosticCategory,
    DiagnosticReviewStatus,
    DiagnosticSeverity,
)


def compute_diagnostic_run_fingerprint(payload: dict) -> str:
    """A deterministic ``sha256`` hex digest of ``payload``'s own canonical (sorted-key) JSON
    encoding -- this table's own idempotency key. Mirrors ``app.persistence
    .module_aggregate.compute_aggregate_fingerprint``'s own identical technique, applied to
    "what did this sweep examine" instead of "what did this aggregate roll up"."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_latest_diagnostic_run(
    session: Session, hierarchy_run_record_id: UUID
) -> CrossModuleDiagnosticRun | None:
    """The highest-``version`` ``CrossModuleDiagnosticRun`` on file for one hierarchy run, or
    ``None`` if the sweep has never been run. Read-only."""
    stmt = (
        select(CrossModuleDiagnosticRun)
        .where(CrossModuleDiagnosticRun.hierarchy_run_record_id == hierarchy_run_record_id)
        .order_by(CrossModuleDiagnosticRun.version.desc())
        .limit(1)
    )
    return session.scalars(stmt).one_or_none()


def list_diagnostic_run_versions(
    session: Session, hierarchy_run_record_id: UUID
) -> list[CrossModuleDiagnosticRun]:
    """Every version on file for one hierarchy run, oldest first. Read-only."""
    stmt = (
        select(CrossModuleDiagnosticRun)
        .where(CrossModuleDiagnosticRun.hierarchy_run_record_id == hierarchy_run_record_id)
        .order_by(CrossModuleDiagnosticRun.version.asc())
    )
    return list(session.scalars(stmt))


def create_diagnostic_run(
    *,
    hierarchy_run_record_id: UUID,
    input_fingerprint: str,
    findings: list[dict],
    session: Session,
) -> CrossModuleDiagnosticRun:
    """Create a new ``CrossModuleDiagnosticRun`` (with all of its own ``findings``) for one
    hierarchy run, idempotently.

    Idempotent by ``input_fingerprint`` against the *latest* existing run for this hierarchy
    run: if it matches, the existing run (and its own already-persisted findings) is returned
    unchanged -- never duplicated, and the newly-computed ``findings`` are discarded rather
    than persisted. Only a genuinely different fingerprint (changed module results/
    conditions) creates a new, incrementally numbered version with its own fresh findings; the
    old version and its own findings are never touched.

    Each entry of ``findings`` is a plain dict: ``{"category", "severity", "message",
    "affected_model_module_ids": [str, ...], "evidence_payload": dict}``.
    """
    latest = get_latest_diagnostic_run(session, hierarchy_run_record_id)
    if latest is not None and latest.input_fingerprint == input_fingerprint:
        return latest

    run = CrossModuleDiagnosticRun(
        hierarchy_run_record_id=hierarchy_run_record_id,
        version=(latest.version + 1) if latest is not None else 1,
        input_fingerprint=input_fingerprint,
        finding_count=len(findings),
    )
    session.add(run)
    session.flush()

    for finding in findings:
        row = CrossModuleDiagnostic(
            diagnostic_run_id=run.id,
            category=CrossModuleDiagnosticCategory(finding["category"]),
            severity=DiagnosticSeverity(finding["severity"]),
            message=finding["message"],
            affected_model_module_ids=json.dumps(
                [str(i) for i in finding["affected_model_module_ids"]]
            ),
            evidence_payload=json.dumps(finding["evidence_payload"]),
        )
        session.add(row)
    session.flush()
    return run


def list_findings_for_run(session: Session, diagnostic_run_id: UUID) -> list[CrossModuleDiagnostic]:
    """Every finding of one diagnostic run, in creation order. Read-only."""
    stmt = (
        select(CrossModuleDiagnostic)
        .where(CrossModuleDiagnostic.diagnostic_run_id == diagnostic_run_id)
        .order_by(CrossModuleDiagnostic.created_at.asc())
    )
    return list(session.scalars(stmt))


def get_finding(session: Session, finding_id: UUID) -> CrossModuleDiagnostic | None:
    """One finding by id, or ``None``. Read-only."""
    return session.get(CrossModuleDiagnostic, finding_id)


def read_affected_model_module_ids(finding: CrossModuleDiagnostic) -> list[str]:
    """Decode one finding's own ``affected_model_module_ids`` -- the one documented site."""
    return json.loads(finding.affected_model_module_ids)


def read_diagnostic_evidence(finding: CrossModuleDiagnostic) -> dict:
    """Decode one finding's own ``evidence_payload`` -- the one documented site."""
    return json.loads(finding.evidence_payload)


def mark_finding_reviewed(
    *,
    finding_id: UUID,
    session: Session,
    review_note: str | None = None,
    reviewed_by: str | None = None,
) -> CrossModuleDiagnostic:
    """Record a human's own review of one finding -- the one deliberate exception to this
    table pair's own "never update detection content" rule (see module docstring). Only
    ``review_status``/``review_note``/``reviewed_by``/``reviewed_at`` are ever touched; the
    finding's own ``category``/``severity``/``message``/``evidence_payload``, and every
    upstream source record it describes, are never altered.

    Raises ``ValueError`` if no such finding exists.
    """
    finding = get_finding(session, finding_id)
    if finding is None:
        raise ValueError(f"no CrossModuleDiagnostic with id {finding_id}")
    finding.review_status = DiagnosticReviewStatus.REVIEWED
    finding.review_note = review_note
    finding.reviewed_by = reviewed_by
    finding.reviewed_at = datetime.now(UTC)
    session.flush()
    return finding


__all__ = [
    "compute_diagnostic_run_fingerprint",
    "create_diagnostic_run",
    "get_finding",
    "get_latest_diagnostic_run",
    "list_diagnostic_run_versions",
    "list_findings_for_run",
    "mark_finding_reviewed",
    "read_affected_model_module_ids",
    "read_diagnostic_evidence",
]
