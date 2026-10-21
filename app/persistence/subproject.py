"""Subproject persistence. Idempotent on ``(project_id, title)``."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import SubprojectTaskType, WorkflowLifecycleStatus
from app.models.subproject import Subproject
from app.persistence.types import PersistenceAction, PersistenceResult


def _existing_by_natural_key(session: Session, project_id: UUID, title: str) -> Subproject | None:
    return session.execute(
        select(Subproject).where(Subproject.project_id == project_id, Subproject.title == title)
    ).scalar_one_or_none()


def persist_subproject(
    *,
    project_id: UUID,
    title: str,
    task_type: SubprojectTaskType,
    session: Session,
    objective: str | None = None,
    status: WorkflowLifecycleStatus = WorkflowLifecycleStatus.ACTIVE,
    notes: str | None = None,
) -> PersistenceResult:
    """Persist one ``Subproject``, keyed by ``(project_id, title)``."""
    if not isinstance(title, str) or not title.strip():
        raise ValueError("persist_subproject requires a non-empty title")

    existing = _existing_by_natural_key(session, project_id, title)
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=f"{project_id}:{title}",
            reason=(
                f"reused existing subproject {existing.id} with the identical (project_id, title)"
            ),
        )

    try:
        with session.begin_nested():
            row = Subproject(
                project_id=project_id,
                title=title,
                objective=objective,
                task_type=task_type,
                status=status,
                notes=notes,
            )
            session.add(row)
            session.flush()
    except IntegrityError:
        raced = _existing_by_natural_key(session, project_id, title)
        if raced is not None:
            return PersistenceResult(
                action=PersistenceAction.REUSED_EXISTING,
                entity_id=raced.id,
                created=False,
                reused_existing=True,
                identity=f"{project_id}:{title}",
                reason=f"reused existing subproject {raced.id} after a concurrent insert won",
            )
        return PersistenceResult(
            action=PersistenceAction.FAILED,
            entity_id=None,
            created=False,
            reused_existing=False,
            identity=f"{project_id}:{title}",
            reason=(
                "subproject creation rolled back due to a database integrity violation, "
                "and no matching row was found on recheck"
            ),
        )

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=f"{project_id}:{title}",
        reason="created new subproject",
    )


def get_subproject(session: Session, subproject_id: UUID) -> Subproject | None:
    """One ``Subproject`` row by id, or ``None``. Read-only."""
    return session.get(Subproject, subproject_id)


def get_subproject_for_project(
    session: Session, project_id: UUID, subproject_id: UUID
) -> Subproject | None:
    """One ``Subproject`` row by id, but only if it belongs to ``project_id``.

    A subproject id that exists but belongs to a *different* project returns
    ``None`` here, identically to one that does not exist at all -- so the
    "Modeling Study" detail routes can never be made to leak a study from
    one project through a different project's URL. Read-only.
    """
    subproject = session.get(Subproject, subproject_id)
    if subproject is None or subproject.project_id != project_id:
        return None
    return subproject


def list_subprojects(session: Session, project_id: UUID) -> list[Subproject]:
    """Every ``Subproject`` belonging to one project, ordered by title. Read-only."""
    return list(
        session.execute(
            select(Subproject).where(Subproject.project_id == project_id).order_by(Subproject.title)
        )
        .scalars()
        .all()
    )


def count_subprojects_by_project(session: Session) -> dict[UUID, int]:
    """Study count per project, in one aggregate query -- never per-project N+1.

    A project with zero subprojects is simply absent from the returned
    mapping; callers that need a default of ``0`` use ``dict.get(..., 0)``.
    """
    rows = session.execute(
        select(Subproject.project_id, func.count(Subproject.id)).group_by(Subproject.project_id)
    ).all()
    return dict(rows)


__all__ = [
    "count_subprojects_by_project",
    "get_subproject",
    "get_subproject_for_project",
    "list_subprojects",
    "persist_subproject",
]
