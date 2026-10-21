"""Tests for ``app.persistence.dataset_reference``."""

from __future__ import annotations

import uuid

import pytest

from app.persistence.dataset_reference import (
    count_dataset_references_by_subproject,
    get_dataset_reference,
    persist_dataset_reference,
)
from app.persistence.types import PersistenceAction
from tests.persistence.conftest import make_project_id, make_subproject_id

pytestmark = pytest.mark.database


def test_creates_new_dataset_reference(db_session):
    project_id = make_project_id(db_session)
    result = persist_dataset_reference(
        project_id=project_id,
        name="protein abundance dataset",
        dataset_type="experimental_observation",
        artifact_reference="s3://bucket/abundance.csv",
        session=db_session,
    )
    assert result.action is PersistenceAction.CREATED
    row = get_dataset_reference(db_session, result.entity_id)
    assert row.dataset_type == "experimental_observation"


def test_reuses_existing_dataset_reference_idempotently(db_session):
    project_id = make_project_id(db_session)
    first = persist_dataset_reference(
        project_id=project_id,
        name="dataset",
        dataset_type="calibration_target",
        artifact_reference="s3://bucket/dataset.csv",
        session=db_session,
    )
    second = persist_dataset_reference(
        project_id=project_id,
        name="dataset",
        dataset_type="validation_holdout",
        artifact_reference="s3://bucket/dataset.csv",
        session=db_session,
    )
    assert second.action is PersistenceAction.REUSED_EXISTING
    assert second.entity_id == first.entity_id
    row = get_dataset_reference(db_session, first.entity_id)
    assert row.dataset_type == "calibration_target"


def test_dataset_reference_scoped_to_a_subproject(db_session):
    project_id = make_project_id(db_session)
    subproject_id = make_subproject_id(db_session, project_id=project_id)
    result = persist_dataset_reference(
        project_id=project_id,
        subproject_id=subproject_id,
        name="holdout set",
        dataset_type="validation_holdout",
        artifact_reference="s3://bucket/holdout.csv",
        session=db_session,
        agent1_entity_type="experimental_context",
        agent1_entity_id=uuid.uuid4(),
    )
    row = get_dataset_reference(db_session, result.entity_id)
    assert row.subproject_id == subproject_id
    assert row.agent1_entity_type == "experimental_context"


def test_count_dataset_references_by_subproject_empty(db_session):
    assert count_dataset_references_by_subproject(db_session) == {}


def test_count_dataset_references_by_subproject_ignores_project_only_rows(db_session):
    project_id = make_project_id(db_session)
    subproject_with_two = make_subproject_id(db_session, project_id=project_id)
    subproject_with_zero = make_subproject_id(db_session, project_id=project_id)
    persist_dataset_reference(
        project_id=project_id,
        subproject_id=subproject_with_two,
        name="first",
        dataset_type="experimental_observation",
        artifact_reference="s3://bucket/first.csv",
        session=db_session,
    )
    persist_dataset_reference(
        project_id=project_id,
        subproject_id=subproject_with_two,
        name="second",
        dataset_type="calibration_target",
        artifact_reference="s3://bucket/second.csv",
        session=db_session,
    )
    # Scoped only to the project, not any specific study -- must never be
    # attributed to subproject_with_two or any other study.
    persist_dataset_reference(
        project_id=project_id,
        name="project-wide dataset",
        dataset_type="experimental_observation",
        artifact_reference="s3://bucket/project-wide.csv",
        session=db_session,
    )

    counts = count_dataset_references_by_subproject(db_session)

    assert counts[subproject_with_two] == 2
    assert subproject_with_zero not in counts
