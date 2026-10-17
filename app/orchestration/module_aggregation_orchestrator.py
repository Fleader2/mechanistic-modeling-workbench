"""Hierarchical Aggregation of Module-Level Agent3/4/5 Results: the service layer a caller
uses to build/rebuild, retrieve, and inspect provenance for the rolled-up, per-execution-kind
summary of one target's own module-level results -- a specific ``ModelModule`` or the
hierarchy root.

No scientific logic lives here, and this module never invokes any agent or the harness --
constraint §8 ("Aggregation belongs in Workbench"). It only reads already-persisted
``RunRecord``/``ModuleExecutionSnapshot`` rows and the already-persisted hierarchy topology
(``ModelModule.parent_model_module_id``), and never merges, averages, or otherwise blends
unlike children's own results into one number (task instructions §2/§4) -- every child's own
contribution is always reported side by side, tagged by its own ``module_id``.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ModuleAggregateCompleteness, ModuleExecutionKind, RunStage, RunStatus
from app.models.model_module import ModelModule
from app.models.module_aggregate import ModuleAggregate
from app.models.run_record import RunRecord
from app.persistence.model_module import get_model_module
from app.persistence.module_aggregate import (
    compute_aggregate_fingerprint,
    create_aggregate,
    get_latest_aggregate,
    list_aggregate_versions,
    read_aggregate_payload,
)
from app.persistence.module_execution_snapshot import get_snapshot_for_run
from app.persistence.run_record import get_run_record

#: Which ``RunStage`` a given ``ModuleExecutionKind``'s own module-scoped results live under --
#: the one place this mapping is defined, reused by every lookup in this module.
_STAGE_BY_KIND: dict[ModuleExecutionKind, RunStage] = {
    ModuleExecutionKind.SIMULATION: RunStage.AGENT3,
    ModuleExecutionKind.CALIBRATION: RunStage.AGENT4,
    ModuleExecutionKind.VALIDATION: RunStage.AGENT5,
}


def _latest_direct_result(
    session: Session, model_module_id: UUID, execution_kind: ModuleExecutionKind
) -> RunRecord | None:
    """This module's own most relevant direct ``RunRecord`` for one execution kind -- the most
    recent *successful* one if any exists, else the most recent attempt of any outcome (so a
    module that only ever failed still shows that failure, never silently nothing), else
    ``None`` if this module was never run through this stage at all."""
    stage = _STAGE_BY_KIND[execution_kind]
    stmt = (
        select(RunRecord)
        .where(RunRecord.model_module_id == model_module_id, RunRecord.stage == stage)
        .order_by(RunRecord.created_at.desc())
    )
    runs = list(session.scalars(stmt))
    succeeded = [r for r in runs if r.status is RunStatus.SUCCEEDED]
    if succeeded:
        return succeeded[0]
    return runs[0] if runs else None


def _direct_children(
    session: Session, target_model_module_id: UUID | None, hierarchy_run_record_id: UUID
) -> list[ModelModule]:
    """Every direct child of one target, using only the already-persisted
    ``ModelModule.parent_model_module_id`` relationship -- never recomputed topology (task
    instructions §5). ``target_model_module_id=None`` names the hierarchy root, whose own
    direct children are every depth-1 module of this hierarchy run (``parent_model_module_id
    IS NULL``, the identical convention ``ModelModule`` itself already documents)."""
    if target_model_module_id is not None:
        stmt = select(ModelModule).where(
            ModelModule.parent_model_module_id == target_model_module_id
        )
    else:
        stmt = select(ModelModule).where(
            ModelModule.run_record_id == hierarchy_run_record_id,
            ModelModule.parent_model_module_id.is_(None),
        )
    stmt = stmt.order_by(ModelModule.module_id.asc())
    return list(session.scalars(stmt))


def _summarize_own_result(
    session: Session, run_record: RunRecord | None, execution_kind: ModuleExecutionKind
) -> dict | None:
    """A compact, per-kind diagnostic summary of one module's own direct result -- never the
    full raw report (kept reasonably sized), but always the specific fields task instructions
    §3 names: key simulation diagnostics, calibration fit/parameter/uncertainty summaries, or
    validation diagnostics/experimental-design recommendations. Returns ``None`` only when the
    module was never run through this stage at all."""
    if run_record is None:
        return None

    snapshot = get_snapshot_for_run(session, run_record.id)
    entry: dict = {
        "run_record_id": str(run_record.id),
        "status": run_record.status.value,
        "execution_snapshot_id": str(snapshot.id) if snapshot is not None else None,
    }
    if run_record.status is not RunStatus.SUCCEEDED or not run_record.artifact_reference:
        entry["error_summary"] = run_record.error_summary
        return entry

    try:
        artifact = json.loads(run_record.artifact_reference)
    except (TypeError, json.JSONDecodeError):
        entry["error_summary"] = "artifact_reference could not be parsed"
        return entry

    if execution_kind is ModuleExecutionKind.SIMULATION:
        agent3_report = artifact.get("agent3_report") or {}
        entry["overall_status"] = agent3_report.get("overall_status")
        entry["module_handoff_summary"] = artifact.get("module_handoff_summary")
    elif execution_kind is ModuleExecutionKind.CALIBRATION:
        calibration = (artifact.get("agent4_report") or {}).get("calibration") or {}
        entry["calibration_status"] = calibration.get("status")
        entry["objective_before"] = calibration.get("objective_before")
        entry["objective_after"] = calibration.get("objective_after")
        entry["parameter_estimates"] = [
            {
                "target_id": p.get("target_id"),
                "fitted_value": p.get("fitted_value"),
                "standard_error": p.get("standard_error"),
            }
            for p in calibration.get("parameter_estimates", [])
        ]
    else:  # VALIDATION
        agent5_report = artifact.get("agent5_report") or {}
        entry["validation_overall_status"] = agent5_report.get("overall_status")
        entry["calibration_run_record_id"] = artifact.get("calibration_run_record_id")
        entry["calibrated_parameter_ids_checked"] = agent5_report.get(
            "calibrated_parameter_ids_checked"
        )
        validation = agent5_report.get("validation") or {}
        entry["validation_metrics"] = validation.get("metrics")
        entry["experiment_scores"] = agent5_report.get("experiment_scores")

    return entry


def _compute_completeness(
    *, own_run_record: RunRecord | None, child_summaries: list[dict]
) -> ModuleAggregateCompleteness:
    """Pure coverage rule -- never a quality/agreement judgment (task instructions §4).

    Treats "this target's own direct attempt" (when one was ever made) and "each direct
    child's own aggregate" as equally-weighted *slots* that each independently resolve to
    complete or not -- never letting a successful own result be outvoted to ``EMPTY`` by an
    unrelated empty child, and never letting a merely-attempted-but-failed own result be
    silently forgiven by otherwise-complete children.
    """
    own_attempted = own_run_record is not None
    own_ok = own_attempted and own_run_record.status is RunStatus.SUCCEEDED
    n_children = len(child_summaries)
    n_children_complete = sum(
        1
        for c in child_summaries
        if c["completeness_status"] == ModuleAggregateCompleteness.COMPLETE.value
    )

    total_slots = n_children + (1 if own_attempted else 0)
    complete_slots = n_children_complete + (1 if own_ok else 0)

    if total_slots == 0:
        return ModuleAggregateCompleteness.EMPTY
    if complete_slots == total_slots:
        return ModuleAggregateCompleteness.COMPLETE
    if complete_slots == 0:
        return ModuleAggregateCompleteness.EMPTY
    return ModuleAggregateCompleteness.PARTIAL


def _build_aggregate(
    *,
    session: Session,
    hierarchy_run_record_id: UUID,
    target_model_module: ModelModule | None,
    execution_kind: ModuleExecutionKind,
) -> ModuleAggregate:
    target_model_module_id = target_model_module.id if target_model_module is not None else None

    own_run_record: RunRecord | None = None
    own_result_summary: dict | None = None
    if target_model_module is not None:
        own_run_record = _latest_direct_result(session, target_model_module_id, execution_kind)
        own_result_summary = _summarize_own_result(session, own_run_record, execution_kind)

    children = _direct_children(session, target_model_module_id, hierarchy_run_record_id)
    child_summaries: list[dict] = []
    fingerprint_children: list[dict] = []
    for child in children:
        # Recursive roll-up (task instructions §5): each direct child's own latest aggregate is
        # built (idempotently -- a no-op if nothing about it changed) before this level ever
        # rolls it up, so "leaf -> parent -> root" happens transparently in one top-level call.
        child_aggregate = build_module_aggregate(
            model_module_id=child.id, execution_kind=execution_kind, session=session
        )
        child_summaries.append(
            {
                "model_module_id": str(child.id),
                "module_id": child.module_id,
                "aggregate_id": str(child_aggregate.id),
                "aggregate_version": child_aggregate.version,
                "completeness_status": child_aggregate.completeness_status.value,
            }
        )
        fingerprint_children.append(
            {
                "model_module_id": str(child.id),
                "aggregate_id": str(child_aggregate.id),
                "aggregate_version": child_aggregate.version,
            }
        )

    completeness = _compute_completeness(
        own_run_record=own_run_record, child_summaries=child_summaries
    )
    missing_or_failed_children = [
        c["module_id"]
        for c in child_summaries
        if c["completeness_status"] != ModuleAggregateCompleteness.COMPLETE.value
    ]

    summary_payload = {
        "target_model_module_id": str(target_model_module_id) if target_model_module_id else None,
        "module_id": target_model_module.module_id if target_model_module is not None else None,
        "execution_kind": execution_kind.value,
        "completeness_status": completeness.value,
        "own_result": own_result_summary,
        "children": child_summaries,
        "missing_or_failed_children": missing_or_failed_children,
        "provenance": {
            "own_run_record_id": str(own_run_record.id) if own_run_record is not None else None,
            "own_execution_snapshot_id": (
                own_result_summary.get("execution_snapshot_id") if own_result_summary else None
            ),
            "contributing_child_aggregate_ids": [c["aggregate_id"] for c in child_summaries],
        },
    }

    fingerprint = compute_aggregate_fingerprint(
        {
            "own_run_record_id": str(own_run_record.id) if own_run_record is not None else None,
            "own_run_record_status": (
                own_run_record.status.value if own_run_record is not None else None
            ),
            "children": sorted(fingerprint_children, key=lambda c: c["model_module_id"]),
        }
    )

    return create_aggregate(
        hierarchy_run_record_id=hierarchy_run_record_id,
        target_model_module_id=target_model_module_id,
        execution_kind=execution_kind,
        completeness_status=completeness,
        input_fingerprint=fingerprint,
        summary_payload=summary_payload,
        session=session,
    )


def build_module_aggregate(
    *, model_module_id: UUID, execution_kind: ModuleExecutionKind, session: Session
) -> ModuleAggregate:
    """Build (or idempotently return the already-current version of) one module's own
    aggregate for one execution kind -- rolling up that module's own direct result (if any)
    plus the (recursively, already-built) latest aggregate of each of its own direct children.
    """
    module = get_model_module(session, model_module_id)
    if module is None:
        raise ValueError(f"no ModelModule with id {model_module_id}")
    return _build_aggregate(
        session=session,
        hierarchy_run_record_id=module.run_record_id,
        target_model_module=module,
        execution_kind=execution_kind,
    )


def build_root_aggregate(
    *, hierarchy_run_record_id: UUID, execution_kind: ModuleExecutionKind, session: Session
) -> ModuleAggregate:
    """Build (or idempotently return the already-current version of) the hierarchy root's own
    aggregate for one execution kind -- rolling up the (recursively, already-built) latest
    aggregate of every depth-1 ``ModelModule`` of this hierarchy run."""
    hierarchy_run = get_run_record(session, hierarchy_run_record_id)
    if hierarchy_run is None:
        raise ValueError(f"no RunRecord with id {hierarchy_run_record_id}")
    return _build_aggregate(
        session=session,
        hierarchy_run_record_id=hierarchy_run_record_id,
        target_model_module=None,
        execution_kind=execution_kind,
    )


def get_latest_module_aggregate(
    session: Session, model_module_id: UUID, execution_kind: ModuleExecutionKind
) -> ModuleAggregate | None:
    """The latest already-built aggregate for one module, or ``None`` if none has ever been
    built. Read-only -- never builds one."""
    return get_latest_aggregate(
        session, execution_kind=execution_kind, target_model_module_id=model_module_id
    )


def get_latest_root_aggregate(
    session: Session, hierarchy_run_record_id: UUID, execution_kind: ModuleExecutionKind
) -> ModuleAggregate | None:
    """The latest already-built root aggregate for one hierarchy run, or ``None``. Read-only --
    never builds one."""
    return get_latest_aggregate(
        session, execution_kind=execution_kind, hierarchy_run_record_id=hierarchy_run_record_id
    )


def list_module_aggregate_versions(
    session: Session, model_module_id: UUID, execution_kind: ModuleExecutionKind
) -> list[ModuleAggregate]:
    """Every version on file for one module's own aggregate, oldest first. Read-only."""
    return list_aggregate_versions(
        session, execution_kind=execution_kind, target_model_module_id=model_module_id
    )


def read_aggregate_summary(aggregate: ModuleAggregate) -> dict:
    """Decode one aggregate's own ``summary_payload``. Thin, documented re-export of
    ``app.persistence.module_aggregate.read_aggregate_payload`` for orchestration-layer
    callers."""
    return read_aggregate_payload(aggregate)


def get_aggregate_provenance(session: Session, aggregate: ModuleAggregate) -> dict:
    """The *full*, recursively-flattened set of everything that contributed anywhere in this
    aggregate's own subtree -- every contributing ``RunRecord`` id, every
    ``ModuleExecutionSnapshot`` id, every ``ModelModule`` id, and every ``ModuleAggregate`` id
    (this one and every descendant) -- walked by following each child's own recorded
    ``aggregate_id`` link, never by re-deriving topology. Used to verify "every reported
    summary item is traceable to its source RunRecord/ModuleExecutionSnapshot."
    """
    payload = read_aggregate_payload(aggregate)
    run_record_ids: set[str] = set()
    snapshot_ids: set[str] = set()
    aggregate_ids: set[str] = {str(aggregate.id)}
    model_module_ids: set[str] = set()

    if payload.get("target_model_module_id"):
        model_module_ids.add(payload["target_model_module_id"])
    provenance = payload.get("provenance") or {}
    if provenance.get("own_run_record_id"):
        run_record_ids.add(provenance["own_run_record_id"])
    if provenance.get("own_execution_snapshot_id"):
        snapshot_ids.add(provenance["own_execution_snapshot_id"])

    for child in payload.get("children", []):
        model_module_ids.add(child["model_module_id"])
        child_aggregate = session.get(ModuleAggregate, UUID(child["aggregate_id"]))
        if child_aggregate is None:
            continue
        nested = get_aggregate_provenance(session, child_aggregate)
        run_record_ids |= set(nested["run_record_ids"])
        snapshot_ids |= set(nested["execution_snapshot_ids"])
        aggregate_ids |= set(nested["aggregate_ids"])
        model_module_ids |= set(nested["model_module_ids"])

    return {
        "run_record_ids": sorted(run_record_ids),
        "execution_snapshot_ids": sorted(snapshot_ids),
        "aggregate_ids": sorted(aggregate_ids),
        "model_module_ids": sorted(model_module_ids),
    }


__all__ = [
    "build_module_aggregate",
    "build_root_aggregate",
    "get_aggregate_provenance",
    "get_latest_module_aggregate",
    "get_latest_root_aggregate",
    "list_module_aggregate_versions",
    "read_aggregate_summary",
]
