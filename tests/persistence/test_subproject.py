"""Tests for ``app.persistence.subproject``."""

from __future__ import annotations

import pytest

from app.models.enums import SubprojectTaskType
from app.persistence.subproject import (
    count_subprojects_by_project,
    get_subproject,
    list_subprojects,
    persist_subproject,
)
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


def test_list_subprojects_empty_for_project_with_none(db_session):
    project_id = make_project_id(db_session)
    assert list_subprojects(db_session, project_id) == []


def test_list_subprojects_returns_only_this_projects_rows_ordered_by_title(db_session):
    project_id = make_project_id(db_session)
    other_project_id = make_project_id(db_session)
    persist_subproject(
        project_id=project_id,
        title="zz last",
        task_type=SubprojectTaskType.TEST_MODEL,
        session=db_session,
    )
    persist_subproject(
        project_id=project_id,
        title="aa first",
        task_type=SubprojectTaskType.BUILD_MODEL,
        session=db_session,
    )
    persist_subproject(
        project_id=other_project_id,
        title="belongs to a different project",
        task_type=SubprojectTaskType.BUILD_MODEL,
        session=db_session,
    )

    rows = list_subprojects(db_session, project_id)

    assert [row.title for row in rows] == ["aa first", "zz last"]


def test_count_subprojects_by_project_empty(db_session):
    assert count_subprojects_by_project(db_session) == {}


def test_count_subprojects_by_project_aggregates_per_project(db_session):
    project_with_two = make_project_id(db_session)
    project_with_one = make_project_id(db_session)
    project_with_zero = make_project_id(db_session)
    persist_subproject(
        project_id=project_with_two,
        title="first",
        task_type=SubprojectTaskType.BUILD_MODEL,
        session=db_session,
    )
    persist_subproject(
        project_id=project_with_two,
        title="second",
        task_type=SubprojectTaskType.CALIBRATE_MODEL,
        session=db_session,
    )
    persist_subproject(
        project_id=project_with_one,
        title="only",
        task_type=SubprojectTaskType.BUILD_MODEL,
        session=db_session,
    )

    counts = count_subprojects_by_project(db_session)

    assert counts[project_with_two] == 2
    assert counts[project_with_one] == 1
    assert project_with_zero not in counts
