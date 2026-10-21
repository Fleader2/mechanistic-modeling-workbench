"""Tests for ``app.persistence.model``."""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import ModelSourceType, ModelStatus
from app.persistence.model import count_models_by_subproject, get_model, list_models, persist_model
from app.persistence.types import PersistenceAction
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


def test_creates_new_model(db_session):
    subproject_id = make_subproject_id(db_session)
    identifier = f"MODEL_{uuid.uuid4().hex[:8]}"
    result = persist_model(
        subproject_id=subproject_id,
        stable_identifier=identifier,
        name="core model v1",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )
    assert result.action is PersistenceAction.CREATED
    row = get_model(db_session, result.entity_id)
    assert row.stable_identifier == identifier


def test_reuses_existing_model_idempotently(db_session):
    subproject_id = make_subproject_id(db_session)
    identifier = f"MODEL_{uuid.uuid4().hex[:8]}"
    first = persist_model(
        subproject_id=subproject_id,
        stable_identifier=identifier,
        name="first name",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )
    second = persist_model(
        subproject_id=subproject_id,
        stable_identifier=identifier,
        name="a different name",
        source_type=ModelSourceType.IMPORTED,
        session=db_session,
    )
    assert second.action is PersistenceAction.REUSED_EXISTING
    assert second.entity_id == first.entity_id
    row = get_model(db_session, first.entity_id)
    assert row.name == "first name"


def test_lineage_via_parent_model_id_never_overwrites_prior_version(db_session):
    subproject_id = make_subproject_id(db_session)
    draft = persist_model(
        subproject_id=subproject_id,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="draft model",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )
    calibrated = persist_model(
        subproject_id=subproject_id,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="calibrated model",
        source_type=ModelSourceType.DERIVED,
        session=db_session,
        parent_model_id=draft.entity_id,
        status=ModelStatus.ACTIVE,
    )
    assert calibrated.entity_id != draft.entity_id
    calibrated_row = get_model(db_session, calibrated.entity_id)
    assert calibrated_row.parent_model_id == draft.entity_id
    draft_row = get_model(db_session, draft.entity_id)
    assert draft_row.name == "draft model"


def test_artifact_reference_is_an_opaque_pointer(db_session):
    subproject_id = make_subproject_id(db_session)
    result = persist_model(
        subproject_id=subproject_id,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="model with artifact",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
        artifact_reference="harness-run://runs/2026-10-13T00-00-00/stage2_output.json",
    )
    row = get_model(db_session, result.entity_id)
    assert row.artifact_reference == "harness-run://runs/2026-10-13T00-00-00/stage2_output.json"


def test_list_models_empty_for_subproject_with_none(db_session):
    subproject_id = make_subproject_id(db_session)
    assert list_models(db_session, subproject_id) == []


def test_list_models_returns_only_this_subprojects_rows_ordered_by_name(db_session):
    subproject_id = make_subproject_id(db_session)
    other_subproject_id = make_subproject_id(db_session)
    persist_model(
        subproject_id=subproject_id,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="zz last model",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )
    persist_model(
        subproject_id=subproject_id,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="aa first model",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )
    persist_model(
        subproject_id=other_subproject_id,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="belongs to a different study",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )

    rows = list_models(db_session, subproject_id)

    assert [row.name for row in rows] == ["aa first model", "zz last model"]


def test_count_models_by_subproject_empty(db_session):
    assert count_models_by_subproject(db_session) == {}


def test_count_models_by_subproject_aggregates_per_subproject(db_session):
    subproject_with_two = make_subproject_id(db_session)
    subproject_with_one = make_subproject_id(db_session)
    subproject_with_zero = make_subproject_id(db_session)
    persist_model(
        subproject_id=subproject_with_two,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="first",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )
    persist_model(
        subproject_id=subproject_with_two,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="second",
        source_type=ModelSourceType.GENERATED,
        session=db_session,
    )
    persist_model(
        subproject_id=subproject_with_one,
        stable_identifier=f"MODEL_{uuid.uuid4().hex[:8]}",
        name="only",
        source_type=ModelSourceType.IMPORTED,
        session=db_session,
    )

    counts = count_models_by_subproject(db_session)

    assert counts[subproject_with_two] == 2
    assert counts[subproject_with_one] == 1
    assert subproject_with_zero not in counts
