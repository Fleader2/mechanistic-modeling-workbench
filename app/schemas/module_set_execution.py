"""Response/request schemas for the Module-Set Edited-Module Materialization increment, Phase B
(``docs/24_module_set_execution_increment.md``).
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import (
    ModuleBoundaryResolutionStatus,
    ModuleBoundaryTreatmentType,
    ModulePortDirection,
    RunStatus,
)
from app.models.module_execution_snapshot import ModuleExecutionSnapshot
from app.models.module_set_execution import ModuleSetMemberBoundaryPort, ModuleSetMemberReview
from app.models.run_record import RunRecord
from app.persistence.module_set_execution import ReadinessFinding


class ModuleSetMemberBoundaryPortItem(BaseModel):
    """One boundary-condition treatment decision for one module-set member's own current
    reaction selection -- structural fact (``species_id``/``direction``) and the
    execution-specific decision (``treatment_type``/``initial_value``/``unit``/``decided_by``)
    both present, never conflated, identically to ``BoundaryPortItem`` (docs/20 §7)."""

    id: UUID
    species_id: str
    direction: ModulePortDirection
    treatment_type: ModuleBoundaryTreatmentType
    resolution_status: ModuleBoundaryResolutionStatus
    initial_value: Decimal | None
    unit: str | None
    decided_by: str | None
    decided_at: datetime | None

    @classmethod
    def from_port(cls, port: ModuleSetMemberBoundaryPort) -> ModuleSetMemberBoundaryPortItem:
        return cls(
            id=port.id,
            species_id=port.species_id,
            direction=port.direction,
            treatment_type=port.treatment_type,
            resolution_status=port.resolution_status,
            initial_value=port.initial_value,
            unit=port.unit,
            decided_by=port.decided_by,
            decided_at=port.decided_at,
        )


class ReadinessFindingItem(BaseModel):
    code: Literal["UNRESOLVED_BOUNDARY_PORT", "NO_BOUNDARY_PORTS_DERIVED"]
    message: str
    species_id: str | None
    direction: str | None

    @classmethod
    def from_finding(cls, finding: ReadinessFinding) -> ReadinessFindingItem:
        return cls(
            code=finding.code,
            message=finding.message,
            species_id=finding.species_id,
            direction=finding.direction,
        )


class ModuleSetMemberReviewDetail(BaseModel):
    """One module-set member's own full boundary-review state: every candidate/decided port,
    every current blocking readiness finding, and ``review_version`` -- the optimistic-
    concurrency token a decision/simulation submission must echo back. Never claims readiness
    proves whole-model coverage or biological validity -- only that Agent 2 has enough resolved
    structural information to build a standalone artifact (docs/24's own explicit disclosure)."""

    id: UUID
    module_set_member_id: UUID
    review_version: int
    derived_at: datetime | None
    ports: list[ModuleSetMemberBoundaryPortItem]
    findings: list[ReadinessFindingItem]
    ready: bool

    @classmethod
    def from_review(
        cls,
        review: ModuleSetMemberReview,
        ports: list[ModuleSetMemberBoundaryPort],
        findings: list[ReadinessFinding],
    ) -> ModuleSetMemberReviewDetail:
        return cls(
            id=review.id,
            module_set_member_id=review.module_set_member_id,
            review_version=review.review_version,
            derived_at=review.derived_at,
            ports=[ModuleSetMemberBoundaryPortItem.from_port(p) for p in ports],
            findings=[ReadinessFindingItem.from_finding(f) for f in findings],
            ready=not findings,
        )


class SubmitBoundaryDecisionRequest(BaseModel):
    expected_review_version: int
    treatment_type: ModuleBoundaryTreatmentType
    initial_value: str | None = None
    unit: str | None = None
    decided_by: str | None = None


class SubmitModuleSetSimulationRequest(BaseModel):
    expected_review_version: int
    solver_settings: dict | None = None
    saved_by: str | None = None


class ModuleSetSimulationRunItem(BaseModel):
    """One simulation run submitted for a module-set member -- status/timing always present;
    ``module_handoff_summary``/``lineage``/``agent3_report`` only once the run has completed
    (``SUCCEEDED`` or ``FAILED`` -- a harness-side failure can still carry a partial
    ``module_handoff_summary``/``lineage`` if materialization itself succeeded before Agent 3
    failed). Labeled explicitly as simulation output, never calibration or validation."""

    id: UUID
    status: RunStatus
    module_set_member_id: UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    result_summary: str | None
    error_summary: str | None
    module_handoff_summary: dict | None
    lineage: dict | None
    agent3_report: dict | None

    @classmethod
    def from_run(cls, run: RunRecord) -> ModuleSetSimulationRunItem:
        module_handoff_summary = None
        lineage = None
        agent3_report = None
        if run.artifact_reference:
            try:
                parsed = json.loads(run.artifact_reference)
                module_handoff_summary = parsed.get("module_handoff_summary")
                lineage = parsed.get("lineage")
                agent3_report = parsed.get("agent3_report")
            except (json.JSONDecodeError, TypeError):
                pass
        return cls(
            id=run.id,
            status=run.status,
            module_set_member_id=run.module_set_member_id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            result_summary=run.result_summary,
            error_summary=run.error_summary,
            module_handoff_summary=module_handoff_summary,
            lineage=lineage,
            agent3_report=agent3_report,
        )


class ModuleSetSimulationSnapshotItem(BaseModel):
    """The immutable, pinned input configuration for one simulation run -- exactly what was
    submitted, never what the member's own (immutable, saved) state happens to show now,
    though for a saved module-set member those are always identical."""

    reaction_component_ids: list[str]
    resolved_boundary_ports: list[dict]
    solver_settings: dict
    saved_by: str | None

    @classmethod
    def from_snapshot(cls, snapshot: ModuleExecutionSnapshot) -> ModuleSetSimulationSnapshotItem:
        payload = json.loads(snapshot.snapshot_payload)
        return cls(
            reaction_component_ids=payload.get("reaction_component_ids", []),
            resolved_boundary_ports=payload.get("resolved_boundary_ports", []),
            solver_settings=payload.get("solver_settings", {}),
            saved_by=payload.get("saved_by"),
        )


__all__ = [
    "ModuleSetMemberBoundaryPortItem",
    "ModuleSetMemberReviewDetail",
    "ModuleSetSimulationRunItem",
    "ModuleSetSimulationSnapshotItem",
    "ReadinessFindingItem",
    "SubmitBoundaryDecisionRequest",
    "SubmitModuleSetSimulationRequest",
]
