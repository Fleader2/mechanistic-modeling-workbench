"""Shared row-creation helpers for ``tests/persistence``."""

from __future__ import annotations

import uuid

from app.models.enums import ProjectType, SubprojectTaskType
from app.persistence.project import persist_project
from app.persistence.subproject import persist_subproject


def make_project_id(db_session, **overrides) -> uuid.UUID:
    kwargs = {
        "stable_identifier": f"PROJ_{uuid.uuid4().hex[:8]}",
        "title": "test-only project",
        "project_type": ProjectType.MICROBIAL_METABOLISM,
        "session": db_session,
    }
    kwargs.update(overrides)
    return persist_project(**kwargs).entity_id


def make_subproject_id(db_session, *, project_id=None, **overrides) -> uuid.UUID:
    if project_id is None:
        project_id = make_project_id(db_session)
    kwargs = {
        "project_id": project_id,
        "title": f"test-only subproject {uuid.uuid4().hex[:8]}",
        "task_type": SubprojectTaskType.BUILD_MODEL,
        "session": db_session,
    }
    kwargs.update(overrides)
    return persist_subproject(**kwargs).entity_id
