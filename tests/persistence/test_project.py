"""Tests for ``app.persistence.project``."""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import ProjectType
from app.persistence.project import get_project, persist_project
from app.persistence.types import PersistenceAction

pytestmark = pytest.mark.database


def _stable_identifier() -> str:
    return f"PROJ_{uuid.uuid4().hex[:8]}"


def test_creates_new_project(db_session):
    stable_identifier = _stable_identifier()
    result = persist_project(
        stable_identifier=stable_identifier,
        title="FFA biosynthesis in yeast",
        project_type=ProjectType.MICROBIAL_METABOLISM,
        session=db_session,
    )
    assert result.action is PersistenceAction.CREATED
    row = get_project(db_session, result.entity_id)
    assert row.stable_identifier == stable_identifier


def test_reuses_existing_project_idempotently(db_session):
    stable_identifier = _stable_identifier()
    first = persist_project(
        stable_identifier=stable_identifier,
        title="first title",
        project_type=ProjectType.MICROBIAL_METABOLISM,
        session=db_session,
    )
    second = persist_project(
        stable_identifier=stable_identifier,
        title="a different title",
        project_type=ProjectType.REGULATORY_NETWORK,
        session=db_session,
    )
    assert second.action is PersistenceAction.REUSED_EXISTING
    assert second.entity_id == first.entity_id
    row = get_project(db_session, first.entity_id)
    assert row.title == "first title"


def test_regulatory_network_project_with_biological_context_copy(db_session):
    organism_id = uuid.uuid4()
    result = persist_project(
        stable_identifier=_stable_identifier(),
        title="p53 regulatory network",
        project_type=ProjectType.REGULATORY_NETWORK,
        session=db_session,
        agent1_organism_id=organism_id,
        disease="colorectal cancer",
        tissue="colon",
    )
    row = get_project(db_session, result.entity_id)
    assert row.agent1_organism_id == organism_id
    assert row.disease == "colorectal cancer"
