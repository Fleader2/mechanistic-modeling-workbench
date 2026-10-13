"""Tests for ``app.persistence.subproject``."""

from __future__ import annotations

import pytest

from app.models.enums import SubprojectTaskType
from app.persistence.subproject import get_subproject, persist_subproject
from app.persistence.types import PersistenceAction
from tests.persistence.conftest import make_project_id

pytestmark = pytest.mark.database


def test_creates_new_subproject(db_session):
    project_id = make_project_id(db_session)
    result = persist_subproject(
        project_id=project_id,
        title="build the core model",
        task_type=SubprojectTaskType.BUILD_MODEL,
        session=db_session,
    )
    assert result.action is PersistenceAction.CREATED
    row = get_subproject(db_session, result.entity_id)
    assert row.task_type is SubprojectTaskType.BUILD_MODEL


def test_reuses_existing_subproject_idempotently(db_session):
    project_id = make_project_id(db_session)
    first = persist_subproject(
        project_id=project_id,
        title="calibrate",
        task_type=SubprojectTaskType.CALIBRATE_MODEL,
        session=db_session,
    )
    second = persist_subproject(
        project_id=project_id,
        title="calibrate",
        task_type=SubprojectTaskType.TEST_MODEL,
        session=db_session,
    )
    assert second.action is PersistenceAction.REUSED_EXISTING
    assert second.entity_id == first.entity_id
    row = get_subproject(db_session, first.entity_id)
    assert row.task_type is SubprojectTaskType.CALIBRATE_MODEL


def test_multiple_subprojects_per_project(db_session):
    project_id = make_project_id(db_session)
    build = persist_subproject(
        project_id=project_id,
        title="build",
        task_type=SubprojectTaskType.BUILD_MODEL,
        session=db_session,
    )
    calibrate = persist_subproject(
        project_id=project_id,
        title="calibrate",
        task_type=SubprojectTaskType.CALIBRATE_MODEL,
        session=db_session,
    )
    assert build.entity_id != calibrate.entity_id
