"""Tests for ``app.persistence.cross_module_diagnostic``."""

from __future__ import annotations

import pytest

from app.models.enums import RunStage
from app.persistence.cross_module_diagnostic import (
    compute_diagnostic_run_fingerprint,
    create_diagnostic_run,
    get_finding,
    get_latest_diagnostic_run,
    list_diagnostic_run_versions,
    list_findings_for_run,
    mark_finding_reviewed,
    read_affected_model_module_ids,
    read_diagnostic_evidence,
)
from app.persistence.run_record import create_run_record, start_run
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


def _make_hierarchy_run(db_session):
    subproject_id = make_subproject_id(db_session)
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.HARNESS, session=db_session)
    start_run(run_record_id=run.id, session=db_session)
    return run


def _finding(**overrides) -> dict:
    data = {
        "category": "SHARED_BOUNDARY_SPECIES_CONFLICT",
        "severity": "ERROR",
        "message": "species X disagrees between modA and modB",
        "affected_model_module_ids": ["00000000-0000-0000-0000-000000000001"],
        "evidence_payload": {"species_id": "X"},
    }
    data.update(overrides)
    return data


def test_create_diagnostic_run_persists_findings(db_session):
    run = _make_hierarchy_run(db_session)
    findings = [_finding()]
    fingerprint = compute_diagnostic_run_fingerprint({"modules": ["a"]})

    diagnostic_run = create_diagnostic_run(
        hierarchy_run_record_id=run.id,
        input_fingerprint=fingerprint,
        findings=findings,
        session=db_session,
    )
    assert diagnostic_run.version == 1
    assert diagnostic_run.finding_count == 1

    persisted = list_findings_for_run(db_session, diagnostic_run.id)
    assert len(persisted) == 1
    assert persisted[0].severity.value == "ERROR"
    assert read_diagnostic_evidence(persisted[0]) == {"species_id": "X"}
    assert read_affected_model_module_ids(persisted[0]) == ["00000000-0000-0000-0000-000000000001"]


def test_create_diagnostic_run_is_idempotent_by_fingerprint(db_session):
    run = _make_hierarchy_run(db_session)
    fingerprint = compute_diagnostic_run_fingerprint({"modules": ["a"]})

    first = create_diagnostic_run(
        hierarchy_run_record_id=run.id,
        input_fingerprint=fingerprint,
        findings=[_finding()],
        session=db_session,
    )
    second = create_diagnostic_run(
        hierarchy_run_record_id=run.id,
        input_fingerprint=fingerprint,
        findings=[_finding(), _finding()],  # must never be applied
        session=db_session,
    )
    assert second.id == first.id
    assert second.version == 1
    assert second.finding_count == 1


def test_create_diagnostic_run_with_a_new_fingerprint_creates_a_new_version(db_session):
    run = _make_hierarchy_run(db_session)
    v1 = create_diagnostic_run(
        hierarchy_run_record_id=run.id,
        input_fingerprint="fp-1",
        findings=[_finding()],
        session=db_session,
    )
    v2 = create_diagnostic_run(
        hierarchy_run_record_id=run.id,
        input_fingerprint="fp-2",
        findings=[],
        session=db_session,
    )
    assert v2.id != v1.id
    assert v2.version == 2
    assert v2.finding_count == 0

    versions = list_diagnostic_run_versions(db_session, run.id)
    assert [v.version for v in versions] == [1, 2]

    # The old version's own findings are never touched.
    assert len(list_findings_for_run(db_session, v1.id)) == 1

    latest = get_latest_diagnostic_run(db_session, run.id)
    assert latest.id == v2.id


def test_get_latest_diagnostic_run_returns_none_when_absent(db_session):
    run = _make_hierarchy_run(db_session)
    assert get_latest_diagnostic_run(db_session, run.id) is None


def test_mark_finding_reviewed_only_touches_review_fields(db_session):
    run = _make_hierarchy_run(db_session)
    diagnostic_run = create_diagnostic_run(
        hierarchy_run_record_id=run.id,
        input_fingerprint="fp-review",
        findings=[_finding()],
        session=db_session,
    )
    (finding,) = list_findings_for_run(db_session, diagnostic_run.id)
    original_message = finding.message
    original_evidence = read_diagnostic_evidence(finding)

    reviewed = mark_finding_reviewed(
        finding_id=finding.id,
        session=db_session,
        review_note="confirmed with the PI, acceptable for now",
        reviewed_by="alice",
    )
    assert reviewed.review_status.value == "REVIEWED"
    assert reviewed.review_note == "confirmed with the PI, acceptable for now"
    assert reviewed.reviewed_by == "alice"
    assert reviewed.reviewed_at is not None
    # Detection content is never altered by a review.
    assert reviewed.message == original_message
    assert read_diagnostic_evidence(reviewed) == original_evidence


def test_mark_finding_reviewed_raises_for_unknown_finding(db_session):
    import uuid

    with pytest.raises(ValueError, match="no CrossModuleDiagnostic"):
        mark_finding_reviewed(finding_id=uuid.uuid4(), session=db_session)


def test_fresh_session_reload_preserves_review_annotation(db_session):
    run = _make_hierarchy_run(db_session)
    diagnostic_run = create_diagnostic_run(
        hierarchy_run_record_id=run.id,
        input_fingerprint="fp-reload",
        findings=[_finding()],
        session=db_session,
    )
    (finding,) = list_findings_for_run(db_session, diagnostic_run.id)
    mark_finding_reviewed(
        finding_id=finding.id, session=db_session, review_note="noted", reviewed_by="bob"
    )
    finding_id = finding.id

    db_session.expire_all()

    reloaded = get_finding(db_session, finding_id)
    assert reloaded.review_status.value == "REVIEWED"
    assert reloaded.review_note == "noted"
    assert reloaded.reviewed_by == "bob"
