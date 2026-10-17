"""UnitResolution: a durable, content-addressed cache of every raw unit string this Workbench
has ever resolved against its own ``pint`` registry (Structured Units and Dimensional-
Consistency Validation increment).

See ``docs/14_structured_units.md``. Deliberately a *standalone* lookup table, not a new
column added to every existing table that happens to carry a free-text unit string
(``ModuleBoundaryPort.unit``, a calibration/validation observation's own optional unit
annotation, a parameter's own materialized unit) -- task instructions §8 ("add minimal
additive ... metadata support") is satisfied by one small new table plus pure resolution
functions that read existing unit strings on demand, never by widening every existing table's
own schema. Nothing holds a foreign key into this table; callers resolve a unit string and get
back a dict, they never need to join against this table directly (though they may, for
inspection/audit).

Immutable once created -- resolving the same string twice is a pure function of that string
alone (``app.units.resolve_unit_string``), so there is never a reason to update a row; a
different resolution for the *same* string would only ever arise from changing this
repository's own registry definitions between releases, which is out of scope here (an
accepted limitation, see ``docs/14_structured_units.md``).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import UnitParseStatus

_UNIT_PARSE_STATUS = Enum(UnitParseStatus, name="unit_parse_status", create_type=False)


class UnitResolution(Base):
    """One cached resolution of one exact raw unit string."""

    __tablename__ = "unit_resolution"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    #: The exact raw string, verbatim -- never normalized before being used as the lookup key
    #: (task instructions §2: "preserve original user/source unit strings"). Never ``NULL``/
    #: empty: a missing unit is never given a row here (see module docstring).
    source_unit_string: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    #: ``pint``'s own short pretty-printed form (e.g. ``"mM"``), or ``NULL`` if unparseable.
    normalized_unit: Mapped[str | None] = mapped_column(String)
    #: ``pint``'s own dimensionality string (e.g. ``"[substance] / [length] ** 3"``), or
    #: ``NULL`` if unparseable.
    dimensionality: Mapped[str | None] = mapped_column(String)
    parse_status: Mapped[UnitParseStatus] = mapped_column(_UNIT_PARSE_STATUS, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["UnitResolution"]
