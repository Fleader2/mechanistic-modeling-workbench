"""ModelParameterCatalog, ModelParameter: a durable, whole-model parameter catalog, captured
from the identical real Antimony/RoadRunner round trip ``ModelSpeciesCatalog`` already uses --
never a second harness call. See ``docs/29_joint_calibration_workflow_design.md`` §1 row 15 and
``docs/31`` for the full rationale.

**The one fact this table exists to get right**: a global parameter id RoadRunner reports
(``rr.model.getGlobalParameterIds()``) is not, by itself, independently settable -- some are
defined entirely by an SBML assignment rule (e.g. Antimony's own ``Vmax := k1 * 2``) and are
genuinely *derived* quantities. ``ModelParameter.kind`` records this real, compiled-model
distinction (verified via the harness's own ``getCurrentSBML()``/``libsbml`` rule inspection,
never inferred from a name) -- a ``DERIVED`` parameter is never offered as an independent
calibration target anywhere this catalog is consulted.

**Units are real here, unlike species.** ``ModelSpecies.unit`` is always ``None`` today because
Agent 2's own structural network carries no species-unit field at all. Agent 2's own
``ParameterSpecification`` *does* carry a real ``unit`` (and ``lower_bound``/``upper_bound``) --
captured here from that structural source, the same way ``ModelSpecies.display_name``/
``compartment_name`` already are, while the parameter's own *existence* and *kind* remain
decided solely by the compiled model, never by the structural claim alone.

``ModelParameterCatalog`` is 1:1 with its own ``Model`` row, ``ON DELETE CASCADE`` -- the
identical "no independent existence apart from describing that one Model" rationale
``ModelSpeciesCatalog`` already uses. Immutable once created: no persistence function in this
repository ever issues an ``UPDATE`` against either table.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ModelParameterCatalogStatus, ModelParameterKind
from app.models.model import Model
from app.models.run_record import RunRecord

_MODEL_PARAMETER_CATALOG_STATUS = Enum(
    ModelParameterCatalogStatus, name="model_parameter_catalog_status", create_type=False
)
_MODEL_PARAMETER_KIND = Enum(ModelParameterKind, name="model_parameter_kind", create_type=False)


class ModelParameterCatalog(Base):
    """One ``Model`` row's own durable parameter catalog -- or an explicit, disclosed record
    of why one is not available."""

    __tablename__ = "model_parameter_catalog"
    __table_args__ = (
        UniqueConstraint("model_id", name="uq_model_parameter_catalog_model_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    model_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[ModelParameterCatalogStatus] = mapped_column(
        _MODEL_PARAMETER_CATALOG_STATUS, nullable=False
    )

    #: Always set when ``status`` is ``UNAVAILABLE`` -- a capture failure is always disclosed,
    #: never silent. ``None`` when ``AVAILABLE``.
    unavailable_reason: Mapped[str | None] = mapped_column(Text)

    #: Which real build/run this catalog (or failed capture attempt) is pinned to.
    source_run_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("run_record.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    #: The identical real, verified Antimony source text ``ModelSpeciesCatalog`` captures from
    #: -- the same artifact, never re-saved a second time; this column is this table's own
    #: pointer to it, kept independent so either catalog can exist without the other.
    source_antimony_artifact_reference: Mapped[str | None] = mapped_column(Text)
    source_antimony_checksum: Mapped[str | None] = mapped_column(String)

    #: Canonical parameter ids (Agent 2's own structural network) that had an
    #: ``antimony_symbol_map`` entry, but whose symbol did not actually appear among the real,
    #: compiled model's own global parameters -- disclosed, never silently dropped. JSON-encoded
    #: list of strings, empty list (``"[]"``) when nothing was unresolved, never ``None``.
    unresolved_canonical_parameter_ids: Mapped[str] = mapped_column(Text, nullable=False)

    #: Canonical parameter ids with no ``antimony_symbol_map`` entry at all -- same JSON-list
    #: convention.
    unmapped_canonical_parameter_ids: Mapped[str] = mapped_column(Text, nullable=False)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    model: Mapped[Model] = relationship()
    source_run_record: Mapped[RunRecord] = relationship()
    parameters: Mapped[list[ModelParameter]] = relationship(
        back_populates="catalog",
        order_by="ModelParameter.antimony_parameter_id",
        passive_deletes=True,
    )


class ModelParameter(Base):
    """One real, compiled global parameter, verified present in the actually-loaded Antimony
    model -- see module docstring for why ``antimony_parameter_id`` (never
    ``canonical_parameter_id``) is the one field a human ever sees or selects, and for why
    ``kind`` is the one field that may ever gate "is this fittable at all"."""

    __tablename__ = "model_parameter"
    __table_args__ = (
        UniqueConstraint(
            "model_parameter_catalog_id",
            "antimony_parameter_id",
            name="uq_model_parameter_catalog_id_antimony_parameter_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    model_parameter_catalog_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_parameter_catalog.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: The real, compiled Antimony identifier -- the one field a human ever sees or selects as
    #: "the parameter."
    antimony_parameter_id: Mapped[str] = mapped_column(Text, nullable=False)

    #: Internal provenance/traceability only -- Agent 2's own structural network id this real
    #: parameter was resolved from. Never surfaced as if it were itself a valid target.
    canonical_parameter_id: Mapped[str] = mapped_column(Text, nullable=False)

    #: Agent 2's own structural ``ParameterSpecification.name`` -- an additional, friendlier
    #: display label alongside ``antimony_parameter_id``, where available.
    display_name: Mapped[str | None] = mapped_column(String)

    #: ``INDEPENDENT``/``DERIVED`` -- from the real, compiled model's own assignment-rule
    #: inspection (module docstring), never inferred from a name or from Agent 2's own
    #: structural claims alone.
    kind: Mapped[ModelParameterKind] = mapped_column(_MODEL_PARAMETER_KIND, nullable=False)

    #: From Agent 2's own structural ``ParameterSpecification`` -- a real unit/bounds source,
    #: unlike ``ModelSpecies.unit`` (module docstring). Still never authoritative about
    #: *existence* -- only the compiled model decides that.
    unit: Mapped[str | None] = mapped_column(String)
    lower_bound: Mapped[Decimal | None] = mapped_column(Numeric)
    upper_bound: Mapped[Decimal | None] = mapped_column(Numeric)

    catalog: Mapped[ModelParameterCatalog] = relationship(back_populates="parameters")


__all__ = ["ModelParameter", "ModelParameterCatalog"]
