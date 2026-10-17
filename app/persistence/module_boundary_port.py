"""ModuleBoundaryPort persistence: idempotently persist candidate boundary ports, and record/
read human treatment decisions.

No scientific logic lives here: this module never decides *which* species are boundary
species (that is ``app.orchestration.module_boundary_orchestrator``'s own job, reusing the
harness/Agent 2's own topology data) and never decides *how* a boundary should be treated --
it only stores already-decided fields and enforces this increment's own two idempotency rules:
a candidate is never persisted twice, and automatic derivation never overwrites an existing
row, manual or not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
    ModuleBoundaryResolutionStatus,
    ModuleBoundaryTreatmentType,
    ModulePortDirection,
)
from app.models.module_boundary_port import ModuleBoundaryPort


def _port_id(model_module_id: UUID, species_id: str, direction: ModulePortDirection) -> str:
    """A stable, deterministic port id -- never Agent 2's own runtime-generated one (this row
    exists before any Agent 2 call is ever made)."""
    return f"port::{model_module_id}::{species_id}::{direction.value}"


def persist_candidate_boundary_ports(
    *,
    model_module_id: UUID,
    candidates: list[dict],
    session: Session,
) -> list[ModuleBoundaryPort]:
    """Create (and return only) the newly-created ``ModuleBoundaryPort`` rows for every
    ``{"species_id", "direction"}`` candidate not already represented for this module --
    always ``UNRESOLVED``/``derived_automatically=True``/``PENDING_REVIEW``. An already-
    existing row (whether itself a prior candidate or a human's own decision) is silently
    skipped, never touched -- the one mechanism that makes automatic re-derivation safe to call
    repeatedly without ever overwriting a manual decision (task instructions §10).
    """
    existing_keys = {
        (row.species_id, row.direction)
        for row in session.execute(
            select(ModuleBoundaryPort.species_id, ModuleBoundaryPort.direction).where(
                ModuleBoundaryPort.model_module_id == model_module_id
            )
        )
    }

    created: list[ModuleBoundaryPort] = []
    for candidate in candidates:
        direction = ModulePortDirection(candidate["direction"])
        species_id = candidate["species_id"]
        if (species_id, direction) in existing_keys:
            continue
        row = ModuleBoundaryPort(
            model_module_id=model_module_id,
            port_id=_port_id(model_module_id, species_id, direction),
            species_id=species_id,
            direction=direction,
            treatment_type=ModuleBoundaryTreatmentType.UNRESOLVED,
            resolution_status=ModuleBoundaryResolutionStatus.PENDING_REVIEW,
            derived_automatically=True,
        )
        session.add(row)
        session.flush()
        created.append(row)
        existing_keys.add((species_id, direction))

    return created


def submit_boundary_decision(
    *,
    port_id: UUID,
    treatment_type: ModuleBoundaryTreatmentType,
    session: Session,
    initial_value: Decimal | str | None = None,
    unit: str | None = None,
    value_source: str | None = None,
    decided_by: str | None = None,
    notes: str | None = None,
) -> ModuleBoundaryPort:
    """Record one human (or, in a future increment, Agent4/5) treatment decision for one
    boundary port.

    Raises ``ValueError`` if the port does not exist, or if ``treatment_type`` is
    ``UNRESOLVED`` (submitting a decision always resolves something -- to leave a port
    unresolved, simply never call this). Raises ``ValueError`` if an ``initial_value``/``unit``
    is supplied for a treatment that never uses one (``DYNAMIC_COUPLING``/``UNRESOLVED``) --
    never silently discarded, a genuine caller error. A value is never fabricated here --
    ``initial_value`` stays ``None`` unless the caller explicitly supplies one.
    """
    row = session.get(ModuleBoundaryPort, port_id)
    if row is None:
        raise ValueError(f"no ModuleBoundaryPort with id {port_id}")
    if treatment_type is ModuleBoundaryTreatmentType.UNRESOLVED:
        raise ValueError("submit_boundary_decision cannot resolve a port to UNRESOLVED")
    if initial_value is not None and treatment_type not in (
        ModuleBoundaryTreatmentType.EXTERNALLY_CONTROLLED,
        ModuleBoundaryTreatmentType.PRESCRIBED_INPUT,
    ):
        raise ValueError(
            f"initial_value is only meaningful for EXTERNALLY_CONTROLLED/PRESCRIBED_INPUT, "
            f"not {treatment_type}"
        )

    row.treatment_type = treatment_type
    row.resolution_status = ModuleBoundaryResolutionStatus.RESOLVED
    row.initial_value = Decimal(initial_value) if initial_value is not None else None
    row.unit = unit
    row.value_source = value_source
    row.provenance_notes = notes
    row.derived_automatically = False
    row.decided_by = decided_by
    row.decided_at = datetime.now(UTC)
    session.flush()
    return row


def get_boundary_port(session: Session, port_id: UUID) -> ModuleBoundaryPort | None:
    """One ``ModuleBoundaryPort`` row by id, or ``None``. Read-only."""
    return session.get(ModuleBoundaryPort, port_id)


def list_boundary_ports_for_module(
    session: Session, model_module_id: UUID
) -> list[ModuleBoundaryPort]:
    """Every ``ModuleBoundaryPort`` row for one module, ordered by ``species_id``/``direction``
    for deterministic display. Read-only."""
    stmt = (
        select(ModuleBoundaryPort)
        .where(ModuleBoundaryPort.model_module_id == model_module_id)
        .order_by(ModuleBoundaryPort.species_id.asc(), ModuleBoundaryPort.direction.asc())
    )
    return list(session.scalars(stmt))


__all__ = [
    "get_boundary_port",
    "list_boundary_ports_for_module",
    "persist_candidate_boundary_ports",
    "submit_boundary_decision",
]
