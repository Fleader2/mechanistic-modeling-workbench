"""Project persistence. Idempotent on ``Project.stable_identifier``."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import ProjectType, WorkflowLifecycleStatus
from app.models.project import Project
from app.persistence.types import PersistenceAction, PersistenceResult


def _existing_by_stable_identifier(session: Session, stable_identifier: str) -> Project | None:
    return session.execute(
        select(Project).where(Project.stable_identifier == stable_identifier)
    ).scalar_one_or_none()


def persist_project(
    *,
    stable_identifier: str,
    title: str,
    project_type: ProjectType,
    session: Session,
    description: str | None = None,
    agent1_organism_id: UUID | None = None,
    biological_context_summary: str | None = None,
    strain_genotype_notes: str | None = None,
    biological_process: str | None = None,
    disease: str | None = None,
    tissue: str | None = None,
    cell_type: str | None = None,
    status: WorkflowLifecycleStatus = WorkflowLifecycleStatus.ACTIVE,
    notes: str | None = None,
) -> PersistenceResult:
    """Persist one ``Project``, keyed by ``stable_identifier``.

    Reuse never overwrites an existing project's fields -- a repeat call
    with the identical ``stable_identifier`` returns ``REUSED_EXISTING``.
    """
    if not isinstance(stable_identifier, str) or not stable_identifier.strip():
        raise ValueError("persist_project requires a non-empty stable_identifier")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("persist_project requires a non-empty title")

    existing = _existing_by_stable_identifier(session, stable_identifier)
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=stable_identifier,
            reason=f"reused existing project {existing.id} with the identical stable_identifier",
        )

    try:
        with session.begin_nested():
            row = Project(
                stable_identifier=stable_identifier,
                title=title,
                description=description,
                project_type=project_type,
                agent1_organism_id=agent1_organism_id,
                biological_context_summary=biological_context_summary,
                strain_genotype_notes=strain_genotype_notes,
                biological_process=biological_process,
                disease=disease,
                tissue=tissue,
                cell_type=cell_type,
                status=status,
                notes=notes,
            )
            session.add(row)
            session.flush()
    except IntegrityError:
        raced = _existing_by_stable_identifier(session, stable_identifier)
        if raced is not None:
            return PersistenceResult(
                action=PersistenceAction.REUSED_EXISTING,
                entity_id=raced.id,
                created=False,
                reused_existing=True,
                identity=stable_identifier,
                reason=f"reused existing project {raced.id} after a concurrent insert won",
            )
        return PersistenceResult(
            action=PersistenceAction.FAILED,
            entity_id=None,
            created=False,
            reused_existing=False,
            identity=stable_identifier,
            reason=(
                "project creation rolled back due to a database integrity violation, "
                "and no matching row was found on recheck"
            ),
        )

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=stable_identifier,
        reason="created new project",
    )


def get_project(session: Session, project_id: UUID) -> Project | None:
    """One ``Project`` row by id, or ``None``. Read-only."""
    return session.get(Project, project_id)


def list_projects(session: Session) -> list[Project]:
    """Every ``Project`` row, ordered by title for a stable, predictable listing.

    Read-only. Does not include a study count -- see
    ``app.persistence.subproject.count_subprojects_by_project`` for that,
    kept separate so a caller who does not need counts never pays for the
    extra aggregate query.
    """
    return list(session.execute(select(Project).order_by(Project.title)).scalars().all())


__all__ = ["get_project", "list_projects", "persist_project"]
