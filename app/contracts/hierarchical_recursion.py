"""The Workbench <-> Integration Harness hierarchical-recursion invocation/result contract.

This is the Workbench's own, independently-maintained copy of the shape
``agent-integration-harness/app/harness/workbench_contracts.py``'s own
``WorkbenchHierarchicalInvocationRequest``/``WorkbenchHierarchicalRunResult`` also define. The
two are never imported across repositories (see ``docs/01_workbench_architecture.md``) -- this
module's own ``CONTRACT_VERSION`` is what keeps the two in sync; a mismatch is detected by the
harness's own canonical entrypoint (``scripts/run_workbench_hierarchical_request.py``) and
reported back as a structured ``FAILED`` result, never silently accepted.

A second, genuinely separate contract from ``app.contracts.harness`` -- that one names the
fixed five-agent ``FULL_PIPELINE`` workflow; this one names a single Automatic Hierarchical
Recursive Modularization search against a model Agent 2 already assembled. See
``docs/04_hierarchical_recursion.md``. ``app.orchestration.hierarchical_run_orchestrator`` is
what actually constructs and sends a request and parses/persists a result; nothing in this
module performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

#: Must match the harness's own ``WORKBENCH_HIERARCHICAL_CONTRACT_VERSION`` exactly, or the
#: canonical entrypoint rejects the request with ``CONTRACT_VERSION_MISMATCH`` before running
#: anything.
CONTRACT_VERSION = "workbench-hierarchical-v1"


class HierarchicalRunStatus(StrEnum):
    """The outcome of one Workbench-invoked hierarchical-recursion run."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    #: Defined for forward compatibility; never produced by the current harness canonical
    #: entrypoint (no cancellation mechanism exists).
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class HierarchicalInvocationRequest:
    """What the Workbench sends to ask the harness to run one hierarchical recursive
    modularization search.

    ``criteria_weights``/``search_policy``/``calibration_selection_policy``/
    ``flat_orchestration_policy``/``recursion_policy`` are plain dicts, forwarded unread and
    unparsed to the harness's own orchestration call -- the Workbench never needs to
    understand their internal shape to submit a run, exactly like
    ``app.contracts.harness.HarnessInvocationRequest.input_artifact_references`` already does
    for Agent 4's/Agent 5's own request files.
    """

    contract_version: str
    run_id: str
    project_id: str
    subproject_id: str
    criteria_weights: dict
    search_policy: dict
    calibration_selection_policy: dict
    flat_orchestration_policy: dict
    recursion_policy: dict
    functional_evaluation_selection_policy: dict | None = None
    model_id: str | None = None
    agent1_organism_id: str | None = None
    input_artifact_references: dict[str, str] = field(default_factory=dict)
    exclude_single_module_from_ranking: bool = True
    apply_resolution_correction: bool = False
    correlation_id: str | None = None
    notes: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True, slots=True)
class HierarchicalRunError:
    """Structured error information for a failed/rejected run."""

    code: str
    message: str
    stage_name: str | None = None


@dataclass(frozen=True, slots=True)
class HierarchyNodeSummary:
    """One node of the hierarchy, exactly as the harness reported it -- field-for-field
    identical to that repository's own ``WorkbenchHierarchyNodeSummary``. This is the shape
    ``app.persistence.hierarchy_node.create_hierarchy_nodes`` persists, one row per entry."""

    node_id: str
    depth: int
    parent_modularization_id: str | None
    parent_module_id: str | None
    child_submodel_id: str | None
    child_modularization_id: str | None
    child_module_ids: tuple[str, ...]
    accepted: bool
    reason: str
    baseline_score: str | None
    child_score: str | None
    branch_stopping_reason: str | None
    recursive_search_stopping_reason: str
    recursive_search_rounds: int
    recursive_search_policy_version: str


@dataclass(frozen=True, slots=True)
class HierarchicalRunResult:
    """What the harness reports back for one ``HierarchicalInvocationRequest`` (or, Hierarchical
    Review/Resume increment, one ``HierarchicalResumeRequest`` -- the two share this identical
    result shape).

    Maps directly onto ``app.persistence.run_record.complete_run``'s own keyword arguments plus
    ``app.persistence.hierarchy_node.create_hierarchy_nodes`` -- ``app.orchestration
    .hierarchical_run_orchestrator`` is the one place that performs that mapping.
    """

    contract_version: str
    run_id: str
    status: HierarchicalRunStatus
    root_model_id: str | None
    nodes: tuple[HierarchyNodeSummary, ...]
    total_nodes_created: int
    total_functional_evaluations_used: int
    total_calibration_runs_used: int
    requires_user_review: bool
    pending_review_modules: tuple[dict, ...]
    recursion_policy_version: str
    started_at: str | None
    completed_at: str | None
    error: HierarchicalRunError | None
    summary: str
    warnings: tuple[str, ...] = ()
    replayed: bool = False
    #: Hierarchical Review/Resume increment: the harness's own, verbatim-opaque
    #: ``serialize_checkpoint(...)`` dict -- populated only when ``requires_user_review`` is
    #: ``True``. This repository stores it exactly as received (``app.persistence
    #: .hierarchy_checkpoint``) and passes it back, unchanged, as
    #: ``HierarchicalResumeRequest.checkpoint`` to resume this run later. Never reinterpreted.
    checkpoint: dict | None = None


def request_to_dict(request: HierarchicalInvocationRequest) -> dict:
    """Serialize a ``HierarchicalInvocationRequest`` to a plain, JSON-ready dict."""
    return {
        "contract_version": request.contract_version,
        "run_id": request.run_id,
        "project_id": request.project_id,
        "subproject_id": request.subproject_id,
        "criteria_weights": dict(request.criteria_weights),
        "search_policy": dict(request.search_policy),
        "calibration_selection_policy": dict(request.calibration_selection_policy),
        "flat_orchestration_policy": dict(request.flat_orchestration_policy),
        "recursion_policy": dict(request.recursion_policy),
        "functional_evaluation_selection_policy": (
            dict(request.functional_evaluation_selection_policy)
            if request.functional_evaluation_selection_policy is not None
            else None
        ),
        "model_id": request.model_id,
        "agent1_organism_id": request.agent1_organism_id,
        "input_artifact_references": dict(request.input_artifact_references),
        "exclude_single_module_from_ranking": request.exclude_single_module_from_ranking,
        "apply_resolution_correction": request.apply_resolution_correction,
        "correlation_id": request.correlation_id,
        "notes": request.notes,
        "submitted_at": request.submitted_at,
    }


def result_from_dict(data: dict) -> HierarchicalRunResult:
    """Parse a plain dict (as read from the harness's own output JSON) into a
    ``HierarchicalRunResult``."""
    error_data = data.get("error")
    error = (
        None
        if error_data is None
        else HierarchicalRunError(
            code=error_data["code"],
            message=error_data["message"],
            stage_name=error_data.get("stage_name"),
        )
    )
    return HierarchicalRunResult(
        contract_version=data["contract_version"],
        run_id=data["run_id"],
        status=HierarchicalRunStatus(data["status"]),
        root_model_id=data.get("root_model_id"),
        nodes=tuple(
            HierarchyNodeSummary(
                node_id=n["node_id"],
                depth=n["depth"],
                parent_modularization_id=n.get("parent_modularization_id"),
                parent_module_id=n.get("parent_module_id"),
                child_submodel_id=n.get("child_submodel_id"),
                child_modularization_id=n.get("child_modularization_id"),
                child_module_ids=tuple(n.get("child_module_ids") or ()),
                accepted=bool(n["accepted"]),
                reason=n["reason"],
                baseline_score=n.get("baseline_score"),
                child_score=n.get("child_score"),
                branch_stopping_reason=n.get("branch_stopping_reason"),
                recursive_search_stopping_reason=n["recursive_search_stopping_reason"],
                recursive_search_rounds=n["recursive_search_rounds"],
                recursive_search_policy_version=n["recursive_search_policy_version"],
            )
            for n in data.get("nodes", ())
        ),
        total_nodes_created=data.get("total_nodes_created", 0),
        total_functional_evaluations_used=data.get("total_functional_evaluations_used", 0),
        total_calibration_runs_used=data.get("total_calibration_runs_used", 0),
        requires_user_review=bool(data.get("requires_user_review", False)),
        pending_review_modules=tuple(dict(m) for m in data.get("pending_review_modules", ())),
        recursion_policy_version=data.get("recursion_policy_version", ""),
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        error=error,
        summary=data.get("summary", ""),
        warnings=tuple(data.get("warnings", ())),
        replayed=bool(data.get("replayed", False)),
        checkpoint=data.get("checkpoint"),
    )


#: Hierarchical Review/Resume increment -- a second, genuinely separate contract from
#: ``CONTRACT_VERSION`` (that one names the *initial* invocation; this one names resuming a
#: paused run). Must match the harness's own
#: ``WORKBENCH_HIERARCHICAL_RESUME_CONTRACT_VERSION`` exactly.
RESUME_CONTRACT_VERSION = "workbench-hierarchical-resume-v1"


@dataclass(frozen=True, slots=True)
class HierarchicalResumeRequest:
    """What the Workbench sends to resume one paused hierarchical-recursion run.

    ``checkpoint`` is this repository's own stored copy of a prior ``HierarchicalRunResult
    .checkpoint`` (``app.persistence.hierarchy_checkpoint``), passed back verbatim -- never
    reconstructed or edited. ``decisions`` maps each pending entry's own ``pending_id`` (as the
    paused run's own ``pending_review_modules`` reported it) to ``"APPROVE"``/``"REJECT"``.
    """

    contract_version: str
    run_id: str
    checkpoint: dict
    decisions: dict[str, str]
    correlation_id: str | None = None
    notes: str | None = None
    submitted_at: str | None = None


def resume_request_to_dict(request: HierarchicalResumeRequest) -> dict:
    """Serialize a ``HierarchicalResumeRequest`` to a plain, JSON-ready dict."""
    return {
        "contract_version": request.contract_version,
        "run_id": request.run_id,
        "checkpoint": request.checkpoint,
        "decisions": dict(request.decisions),
        "correlation_id": request.correlation_id,
        "notes": request.notes,
        "submitted_at": request.submitted_at,
    }


def node_summary_to_dict(node: HierarchyNodeSummary) -> dict:
    """One ``HierarchyNodeSummary`` -> the plain dict shape
    ``app.persistence.hierarchy_node.create_hierarchy_nodes`` consumes."""
    return {
        "node_id": node.node_id,
        "depth": node.depth,
        "parent_modularization_id": node.parent_modularization_id,
        "parent_module_id": node.parent_module_id,
        "child_submodel_id": node.child_submodel_id,
        "child_modularization_id": node.child_modularization_id,
        "child_module_ids": list(node.child_module_ids),
        "accepted": node.accepted,
        "reason": node.reason,
        "baseline_score": node.baseline_score,
        "child_score": node.child_score,
        "branch_stopping_reason": node.branch_stopping_reason,
        "recursive_search_stopping_reason": node.recursive_search_stopping_reason,
        "recursive_search_rounds": node.recursive_search_rounds,
        "recursive_search_policy_version": node.recursive_search_policy_version,
    }


__all__ = [
    "CONTRACT_VERSION",
    "RESUME_CONTRACT_VERSION",
    "HierarchicalInvocationRequest",
    "HierarchicalResumeRequest",
    "HierarchicalRunError",
    "HierarchicalRunResult",
    "HierarchicalRunStatus",
    "HierarchyNodeSummary",
    "node_summary_to_dict",
    "request_to_dict",
    "result_from_dict",
    "resume_request_to_dict",
]
