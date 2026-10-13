"""Tests for ``app.persistence.modeling_decision``."""

from __future__ import annotations

import pytest

from app.models.enums import ModelingDecisionResolutionSource, ModelingDecisionStatus
from app.persistence.modeling_decision import (
    add_modeling_decision_option,
    defer_modeling_decision,
    get_modeling_decision,
    persist_modeling_decision,
    resolve_modeling_decision,
)
from app.persistence.types import PersistenceAction
from tests.persistence.conftest import make_project_id

pytestmark = pytest.mark.database


def test_creates_new_decision(db_session):
    project_id = make_project_id(db_session)
    result = persist_modeling_decision(
        question="which boundary species should be used?", session=db_session, project_id=project_id
    )
    assert result.action is PersistenceAction.CREATED
    row = get_modeling_decision(db_session, result.entity_id)
    assert row.status is ModelingDecisionStatus.OPEN


def test_reuses_existing_decision_idempotently(db_session):
    project_id = make_project_id(db_session)
    first = persist_modeling_decision(
        question="which carbon source?", session=db_session, project_id=project_id
    )
    second = persist_modeling_decision(
        question="which carbon source?", session=db_session, project_id=project_id
    )
    assert second.action is PersistenceAction.REUSED_EXISTING
    assert second.entity_id == first.entity_id


def test_requires_at_least_one_context_reference(db_session):
    with pytest.raises(ValueError):
        persist_modeling_decision(question="orphaned question", session=db_session)


def test_full_resolution_workflow(db_session):
    project_id = make_project_id(db_session)
    decision = persist_modeling_decision(
        question="which carbon source?", session=db_session, project_id=project_id
    )
    option_a = add_modeling_decision_option(
        decision_id=decision.entity_id, label="glucose", session=db_session
    )
    option_b = add_modeling_decision_option(
        decision_id=decision.entity_id, label="ethanol", session=db_session, recommended=True
    )
    assert option_a.action is PersistenceAction.CREATED
    assert option_b.action is PersistenceAction.CREATED

    resolved = resolve_modeling_decision(
        decision_id=decision.entity_id,
        selected_option_id=option_b.entity_id,
        resolution_source=ModelingDecisionResolutionSource.USER,
        session=db_session,
        rationale="matches observed growth data",
    )
    assert resolved.status is ModelingDecisionStatus.RESOLVED
    assert resolved.selected_option_id == option_b.entity_id


def test_resolve_rejects_cross_decision_option(db_session):
    project_id = make_project_id(db_session)
    decision_a = persist_modeling_decision(
        question="question A", session=db_session, project_id=project_id
    )
    decision_b = persist_modeling_decision(
        question="question B", session=db_session, project_id=project_id
    )
    option_for_b = add_modeling_decision_option(
        decision_id=decision_b.entity_id, label="option for B", session=db_session
    )
    with pytest.raises(ValueError):
        resolve_modeling_decision(
            decision_id=decision_a.entity_id,
            selected_option_id=option_for_b.entity_id,
            resolution_source=ModelingDecisionResolutionSource.USER,
            session=db_session,
        )


def test_defer_decision(db_session):
    project_id = make_project_id(db_session)
    decision = persist_modeling_decision(
        question="deferred question", session=db_session, project_id=project_id
    )
    deferred = defer_modeling_decision(decision_id=decision.entity_id, session=db_session)
    assert deferred.status is ModelingDecisionStatus.DEFERRED


def test_idempotent_option_persistence(db_session):
    project_id = make_project_id(db_session)
    decision = persist_modeling_decision(
        question="test-only question", session=db_session, project_id=project_id
    )
    first = add_modeling_decision_option(
        decision_id=decision.entity_id, label="option A", session=db_session
    )
    second = add_modeling_decision_option(
        decision_id=decision.entity_id, label="option A", session=db_session
    )
    assert first.action is PersistenceAction.CREATED
    assert second.action is PersistenceAction.REUSED_EXISTING
    assert first.entity_id == second.entity_id
