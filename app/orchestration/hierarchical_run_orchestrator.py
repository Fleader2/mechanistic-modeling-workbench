"""Drives one ``RunRecord``'s lifecycle through a real hierarchical-recursion harness
invocation, and persists the full node set as first-class, queryable ``HierarchyNode`` rows.

Mirrors ``app.orchestration.run_orchestrator.submit_subproject_run``'s own seven-step lifecycle
exactly (create/replay -> RUNNING -> serialize -> invoke -> parse -> store -> terminal), with
one addition: on success, every ``HierarchyNodeSummary`` the harness reported is bulk-inserted
as its own row (``app.persistence.hierarchy_node.create_hierarchy_nodes``) -- never left as an
opaque JSON blob only, so a UI can render the accepted module tree, stopped branches, scores,
and reasons with ordinary, typed queries.

No scientific logic lives here: this module never interprets, re-derives, or repairs any node's
own acceptance decision -- it only moves a ``RunRecord`` through its own state machine and
copies already-decided fields onto rows.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.hierarchical_recursion import (
    CONTRACT_VERSION,
    HierarchicalInvocationRequest,
    HierarchicalRunStatus,
    node_summary_to_dict,
)
from app.models.enums import RunStage, RunStatus
from app.orchestration.hierarchical_harness_client import invoke_hierarchical_harness
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.run_record import complete_run, create_run_record, get_run_record, start_run


def submit_hierarchical_run(
    *,
    subproject_id: UUID,
    project_id: UUID,
    session: Session,
    criteria_weights: dict,
    search_policy: dict,
    calibration_selection_policy: dict,
    flat_orchestration_policy: dict,
    recursion_policy: dict,
    functional_evaluation_selection_policy: dict | None = None,
    model_id: UUID | None = None,
    agent1_organism_id: str | None = None,
    synthetic_fixture_path: str | None = None,
    exclude_single_module_from_ranking: bool = True,
    apply_resolution_correction: bool = False,
    correlation_id: str | None = None,
    notes: str | None = None,
    run_record_id: UUID | None = None,
):
    """Run (or replay) one hierarchical-recursion harness invocation for a subproject.

    **Duplicate/replayed run handling**, identical to ``submit_subproject_run``'s own: when
    ``run_record_id`` names an existing, already-terminal ``RunRecord``, that row (and its
    already-persisted ``HierarchyNode`` rows) is returned unchanged -- the harness is never
    invoked again. Omit ``run_record_id`` to always start a genuinely new run.

    Exactly one of ``agent1_organism_id`` or ``synthetic_fixture_path`` must be supplied,
    mirroring the harness's own canonical entrypoint's identical requirement -- validated here
    first so a malformed call never pays for a subprocess invocation that would only be
    rejected anyway.

    This run is recorded as ``RunStage.HARNESS`` (the identical stage ``submit_subproject_run``
    uses for the five-agent `FULL_PIPELINE` -- both are, from ``RunRecord``'s own point of view,
    "the harness itself" being invoked; the two are distinguished by whether any
    ``HierarchyNode`` rows exist for a given run, never by a new ``RunStage`` value).
    """
    if (agent1_organism_id is None) == (synthetic_fixture_path is None):
        raise ValueError(
            "submit_hierarchical_run requires exactly one of agent1_organism_id or "
            "synthetic_fixture_path"
        )

    if run_record_id is not None:
        existing = get_run_record(session, run_record_id)
        if existing is None:
            raise ValueError(f"no RunRecord with id {run_record_id}")
        if existing.status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
            return existing
        run_record = existing
    else:
        run_record = create_run_record(
            subproject_id=subproject_id, stage=RunStage.HARNESS, session=session, model_id=model_id
        )

    run_record = start_run(run_record_id=run_record.id, session=session)

    input_artifact_references: dict[str, str] = {}
    if synthetic_fixture_path is not None:
        input_artifact_references["stage1_synthetic_source"] = synthetic_fixture_path

    request = HierarchicalInvocationRequest(
        contract_version=CONTRACT_VERSION,
        run_id=str(run_record.id),
        project_id=str(project_id),
        subproject_id=str(subproject_id),
        criteria_weights=criteria_weights,
        search_policy=search_policy,
        calibration_selection_policy=calibration_selection_policy,
        flat_orchestration_policy=flat_orchestration_policy,
        recursion_policy=recursion_policy,
        functional_evaluation_selection_policy=functional_evaluation_selection_policy,
        model_id=str(model_id) if model_id is not None else None,
        agent1_organism_id=agent1_organism_id,
        input_artifact_references=input_artifact_references,
        exclude_single_module_from_ranking=exclude_single_module_from_ranking,
        apply_resolution_correction=apply_resolution_correction,
        correlation_id=correlation_id,
        notes=notes,
        submitted_at=datetime.now(UTC).isoformat(),
    )

    result, client_error = invoke_hierarchical_harness(request)

    if client_error is not None:
        return complete_run(
            run_record_id=run_record.id,
            status=RunStatus.FAILED,
            session=session,
            error_summary=f"{client_error.code}: {client_error.message}",
        )

    assert result is not None  # invoke_hierarchical_harness's own contract

    artifact_payload = json.dumps(
        {
            "root_model_id": result.root_model_id,
            "total_nodes_created": result.total_nodes_created,
            "total_functional_evaluations_used": result.total_functional_evaluations_used,
            "total_calibration_runs_used": result.total_calibration_runs_used,
            "requires_user_review": result.requires_user_review,
            "pending_review_modules": [dict(m) for m in result.pending_review_modules],
            "recursion_policy_version": result.recursion_policy_version,
        }
    )
    warnings_payload = json.dumps(list(result.warnings)) if result.warnings else None

    if result.status is HierarchicalRunStatus.SUCCEEDED:
        create_hierarchy_nodes(
            run_record_id=run_record.id,
            nodes=[node_summary_to_dict(n) for n in result.nodes],
            session=session,
        )
        return complete_run(
            run_record_id=run_record.id,
            status=RunStatus.SUCCEEDED,
            session=session,
            contract_version=result.contract_version,
            artifact_reference=artifact_payload,
            result_summary=result.summary,
            warnings=warnings_payload,
        )

    error_message = result.summary if result.error is None else result.error.message
    return complete_run(
        run_record_id=run_record.id,
        status=RunStatus.FAILED,
        session=session,
        contract_version=result.contract_version,
        artifact_reference=artifact_payload,
        error_summary=error_message,
        warnings=warnings_payload,
    )


__all__ = ["submit_hierarchical_run"]
