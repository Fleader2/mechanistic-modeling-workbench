"""ModelingDecision/ModelingDecisionOption persistence.

**Decision.** Idempotent on ``(project_id, subproject_id, model_id,
question)`` -- enforced at the application level (no database uniqueness
backs this).

**Option.** Idempotent on ``(decision_id, label)``.

**Resolution.** ``resolve_modeling_decision`` is the only function that
updates an existing row: it validates that the selected option actually
belongs to the decision being resolved -- a cross-decision selection is
rejected, never silently accepted.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
    ConfidenceClass,
    ModelingDecisionResolutionSource,
    ModelingDecisionStatus,
)
from app.models.modeling_decision import ModelingDecision, ModelingDecisionOption
from app.persistence.types import PersistenceAction, PersistenceResult


def _existing_decision(
    session: Session,
    *,
    project_id: UUID | None,
    subproject_id: UUID | None,
    model_id: UUID | None,
    question: str,
) -> ModelingDecision | None:
    return session.execute(
        select(ModelingDecision).where(
            ModelingDecision.project_id == project_id,
            ModelingDecision.subproject_id == subproject_id,
            ModelingDecision.model_id == model_id,
            ModelingDecision.question == question,
        )
    ).scalar_one_or_none()


def persist_modeling_decision(
    *,
    question: str,
    session: Session,
    project_id: UUID | None = None,
    subproject_id: UUID | None = None,
    model_id: UUID | None = None,
    decision_type: str | None = None,
    notes: str | None = None,
) -> PersistenceResult:
    """Persist one ``ModelingDecision``, starting ``OPEN``."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("persist_modeling_decision requires a non-empty question")
    if project_id is None and subproject_id is None and model_id is None:
        raise ValueError(
            "persist_modeling_decision requires at least one of project_id/subproject_id/model_id"
        )

    existing = _existing_decision(
        session,
        project_id=project_id,
        subproject_id=subproject_id,
        model_id=model_id,
        question=question,
    )
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=question,
            reason=f"reused existing modeling decision {existing.id} with the identical context",
        )

    row = ModelingDecision(
        project_id=project_id,
        subproject_id=subproject_id,
        model_id=model_id,
        question=question,
        decision_type=decision_type,
        status=ModelingDecisionStatus.OPEN,
        notes=notes,
    )
    session.add(row)
    session.flush()

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=question,
        reason="created new modeling decision",
    )


def add_modeling_decision_option(
    *,
    decision_id: UUID,
    label: str,
    session: Session,
    description: str | None = None,
    evidence_summary: str | None = None,
    confidence_score: float | None = None,
    confidence_class: ConfidenceClass | None = None,
    impact_summary: str | None = None,
    recommended: bool = False,
) -> PersistenceResult:
    """Add one candidate option to a ``ModelingDecision``."""
    if not isinstance(label, str) or not label.strip():
        raise ValueError("add_modeling_decision_option requires a non-empty label")

    existing = session.execute(
        select(ModelingDecisionOption).where(
            ModelingDecisionOption.decision_id == decision_id, ModelingDecisionOption.label == label
        )
    ).scalar_one_or_none()
    if existing is not None:
        return PersistenceResult(
            action=PersistenceAction.REUSED_EXISTING,
            entity_id=existing.id,
            created=False,
            reused_existing=True,
            identity=label,
            reason=f"reused existing option {existing.id} with the identical (decision_id, label)",
        )

    row = ModelingDecisionOption(
        decision_id=decision_id,
        label=label,
        description=description,
        evidence_summary=evidence_summary,
        confidence_score=confidence_score,
        confidence_class=confidence_class,
        impact_summary=impact_summary,
        recommended=recommended,
    )
    session.add(row)
    session.flush()

    return PersistenceResult(
        action=PersistenceAction.CREATED,
        entity_id=row.id,
        created=True,
        reused_existing=False,
        identity=label,
        reason="created new option",
    )


def resolve_modeling_decision(
    *,
    decision_id: UUID,
    selected_option_id: UUID,
    resolution_source: ModelingDecisionResolutionSource,
    session: Session,
    rationale: str | None = None,
) -> ModelingDecision:
    """Mark a ``ModelingDecision`` ``RESOLVED`` with its selected option.

    Raises ``ValueError`` if the decision/option do not exist, or the
    option does not belong to this decision.
    """
    decision = session.get(ModelingDecision, decision_id)
    if decision is None:
        raise ValueError(f"no ModelingDecision with id {decision_id}")
    option = session.get(ModelingDecisionOption, selected_option_id)
    if option is None:
        raise ValueError(f"no ModelingDecisionOption with id {selected_option_id}")
    if option.decision_id != decision_id:
        raise ValueError(
            f"ModelingDecisionOption {selected_option_id} belongs to decision "
            f"{option.decision_id}, not {decision_id}"
        )

    decision.selected_option_id = selected_option_id
    decision.status = ModelingDecisionStatus.RESOLVED
    decision.resolution_source = resolution_source
    if rationale is not None:
        decision.rationale = rationale
    session.flush()
    return decision


def defer_modeling_decision(*, decision_id: UUID, session: Session) -> ModelingDecision:
    """Mark a ``ModelingDecision`` ``DEFERRED`` (no option selected yet)."""
    decision = session.get(ModelingDecision, decision_id)
    if decision is None:
        raise ValueError(f"no ModelingDecision with id {decision_id}")
    decision.status = ModelingDecisionStatus.DEFERRED
    session.flush()
    return decision


def get_modeling_decision(session: Session, decision_id: UUID) -> ModelingDecision | None:
    """One ``ModelingDecision`` row by id, or ``None``. Read-only."""
    return session.get(ModelingDecision, decision_id)


__all__ = [
    "add_modeling_decision_option",
    "defer_modeling_decision",
    "get_modeling_decision",
    "persist_modeling_decision",
    "resolve_modeling_decision",
]
