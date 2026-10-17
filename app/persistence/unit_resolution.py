"""UnitResolution persistence: resolve a raw unit string against ``app.units.resolve_unit
_string``, caching the result idempotently by its own exact string. No scientific logic lives
here -- this is a pure cache in front of a pure function, mirroring ``app.persistence
.module_aggregate``'s own "no update function exists at all" discipline.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import UnitParseStatus
from app.models.unit_resolution import UnitResolution
from app.units import resolve_unit_string


def get_unit_resolution(session: Session, source_unit_string: str) -> UnitResolution | None:
    """The cached resolution for one exact raw unit string, or ``None`` if never resolved
    before. Read-only."""
    stmt = select(UnitResolution).where(UnitResolution.source_unit_string == source_unit_string)
    return session.scalars(stmt).one_or_none()


def resolve_and_persist_unit(session: Session, raw: str | None) -> dict:
    """Resolve ``raw`` into its structured representation, persisting (idempotently, by exact
    string) a ``UnitResolution`` row for any non-empty string.

    A ``None``/blank string is never persisted (there is no string to key on) -- the ``MISSING``
    dict is returned directly from ``app.units.resolve_unit_string`` instead (task instructions
    §9: never fabricate a unit for what is genuinely absent).

    Idempotent: resolving the same non-empty string again returns the existing row's own
    already-stored fields rather than re-computing and re-inserting (task instructions §10).
    """
    resolved = resolve_unit_string(raw)
    if resolved["parse_status"] == UnitParseStatus.MISSING.value:
        return resolved

    assert raw is not None
    existing = get_unit_resolution(session, raw)
    if existing is not None:
        return {
            "source_unit_string": existing.source_unit_string,
            "normalized_unit": existing.normalized_unit,
            "dimensionality": existing.dimensionality,
            "parse_status": existing.parse_status.value,
        }

    row = UnitResolution(
        source_unit_string=raw,
        normalized_unit=resolved["normalized_unit"],
        dimensionality=resolved["dimensionality"],
        parse_status=UnitParseStatus(resolved["parse_status"]),
    )
    session.add(row)
    session.flush()
    return resolved


__all__ = ["get_unit_resolution", "resolve_and_persist_unit"]
