"""ModelSpeciesCatalog, ModelSpecies, ModelCompartment: a durable, whole-model species/
compartment catalog, captured once per ``Model`` row, available without ever running a
simulation (Model-Species Catalog Prerequisite increment). See
``docs/26_model_species_catalog_prerequisite_increment.md``.

**The one fact this whole increment exists to get right**: Agent 2's own structural
``FullNetwork.species`` (and its own ``antimony_symbol_map``) is *not* guaranteed to have
identical membership with the actually-compiled, loadable Antimony model -- confirmed directly
this increment, both empirically (a real build) and by precedent (Agent 3's own perturbation-
target resolution already discloses exactly this kind of mismatch for a reduced module).
Every ``ModelSpecies`` row here was therefore verified, via a real Antimony/RoadRunner load
(``app.orchestration.model_antimony_verification_harness_client``), to actually exist in the
compiled model -- never merely present in the structural network.

**The human-facing identifier.** ``ModelSpecies.antimony_species_id`` -- the real, compiled
Antimony symbol (human-readable whenever Agent 2's own naming module had a curated biological
name to derive it from, e.g. ``acetyl_CoA_cytosol``, never a raw internal id) -- is the *only*
field a human ever sees or selects as "the species." ``canonical_species_id`` is retained
purely as internal provenance/traceability back to Agent 2's own structural network; it is
never surfaced as if it were itself a valid mapping target.

``ModelSpeciesCatalog`` is 1:1 with its own ``Model`` row, ``ON DELETE CASCADE`` (it has no
independent existence apart from describing that one Model -- unlike ``TimeSeriesDataset``'s
own ``RESTRICT`` relationship to ``DatasetReference``, which *is* an independently-meaningful
scientific record). No row at all for a given ``model_id`` means "capture was never attempted"
-- read identically to an explicit ``UNAVAILABLE`` row by every caller (see
``app.persistence.model_species_catalog.get_model_species_catalog``). Immutable once created:
no persistence function in this repository ever issues an ``UPDATE`` against any of these three
tables.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ModelSpeciesCatalogStatus, ModelSpeciesKind
from app.models.model import Model
from app.models.run_record import RunRecord

_MODEL_SPECIES_CATALOG_STATUS = Enum(
    ModelSpeciesCatalogStatus, name="model_species_catalog_status", create_type=False
)
_MODEL_SPECIES_KIND = Enum(ModelSpeciesKind, name="model_species_kind", create_type=False)


class ModelSpeciesCatalog(Base):
    """One ``Model`` row's own durable species/compartment catalog -- or an explicit,
    disclosed record of why one is not available."""

    __tablename__ = "model_species_catalog"
    __table_args__ = (UniqueConstraint("model_id", name="uq_model_species_catalog_model_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    model_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[ModelSpeciesCatalogStatus] = mapped_column(
        _MODEL_SPECIES_CATALOG_STATUS, nullable=False
    )

    #: Always set when ``status`` is ``UNAVAILABLE`` -- a capture failure is always disclosed,
    #: never silent. ``None`` when ``AVAILABLE``.
    unavailable_reason: Mapped[str | None] = mapped_column(Text)

    #: Which real build/run this catalog (or failed capture attempt) is pinned to -- every row
    #: here, success or failure, is tied to a specific run, never a bare "it didn't work."
    source_run_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("run_record.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    #: The real, verified Antimony source text this catalog was captured from, durably
    #: retained via ``app.storage`` (never the harness's own transient run-output directory) --
    #: ``None`` only when capture failed before the text was even in hand.
    source_antimony_artifact_reference: Mapped[str | None] = mapped_column(Text)
    source_antimony_checksum: Mapped[str | None] = mapped_column(String)

    #: Canonical species ids (Agent 2's own structural network) that had an
    #: ``antimony_symbol_map`` entry, but whose symbol did not actually appear among the real,
    #: compiled model's own species -- disclosed, never silently dropped with no trace. A
    #: JSON-encoded list of strings (this repository's own established ``Text``-holding-JSON
    #: convention); empty list (``"[]"``) when nothing was unresolved, never ``None``, so
    #: "no anomalies" and "not yet checked" are never confused.
    unresolved_canonical_species_ids: Mapped[str] = mapped_column(Text, nullable=False)

    #: Canonical species ids with no ``antimony_symbol_map`` entry at all -- likewise always
    #: disclosed, same JSON-list convention as above.
    unmapped_canonical_species_ids: Mapped[str] = mapped_column(Text, nullable=False)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    model: Mapped[Model] = relationship()
    source_run_record: Mapped[RunRecord] = relationship()
    #: ``passive_deletes=True`` on both: a direct ``session.delete(catalog)`` must trust the
    #: database's own ``ON DELETE CASCADE`` (migration ``0017``) rather than the ORM's default
    #: behavior of first ``UPDATE``-ing every child's own FK to ``NULL`` -- which would violate
    #: that FK's ``NOT NULL`` constraint, since this relationship is pure decomposition with no
    #: independent existence of its own (never actually nullable).
    species: Mapped[list[ModelSpecies]] = relationship(
        back_populates="catalog",
        order_by="ModelSpecies.antimony_species_id",
        passive_deletes=True,
    )
    compartments: Mapped[list[ModelCompartment]] = relationship(
        back_populates="catalog",
        order_by="ModelCompartment.compartment_id",
        passive_deletes=True,
    )


class ModelSpecies(Base):
    """One real, compiled species, verified present in the actually-loaded Antimony model --
    see this module's own docstring for why ``antimony_species_id`` (never
    ``canonical_species_id``) is the one field a human ever sees or selects."""

    __tablename__ = "model_species"
    __table_args__ = (
        UniqueConstraint(
            "model_species_catalog_id",
            "antimony_species_id",
            name="uq_model_species_catalog_id_antimony_species_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    model_species_catalog_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_species_catalog.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: The real, compiled Antimony identifier -- the one field a human ever sees or selects as
    #: "the species." Human-readable whenever a curated biological name was available to Agent
    #: 2's own naming module; never the raw internal canonical id.
    antimony_species_id: Mapped[str] = mapped_column(Text, nullable=False)

    #: Internal provenance/traceability only -- Agent 2's own structural network id this real
    #: species was resolved from. Never surfaced as if it were itself a valid mapping target.
    canonical_species_id: Mapped[str] = mapped_column(Text, nullable=False)

    #: Agent 2's own structural ``SpeciesSpecification.name`` -- an additional, friendlier
    #: display label alongside ``antimony_species_id``, where available.
    display_name: Mapped[str | None] = mapped_column(String)

    #: Canonical compartment id/name -- display/disambiguation context (task instructions:
    #: "include compartment context"). Deliberately the *canonical* compartment id, never an
    #: Antimony-compartment-symbol translation: ``antimony_symbol_map`` exposes no compartment
    #: category at all (confirmed by inspection of ``app.agent2.pipeline._antimony_symbol_map``),
    #: and the canonical id is already validated, reliable, and sufficient for display.
    compartment_id: Mapped[str] = mapped_column(Text, nullable=False)
    compartment_name: Mapped[str | None] = mapped_column(String)

    #: ``FLOATING``/``BOUNDARY``, from the real, compiled model's own
    #: ``getFloatingSpeciesIds``/``getBoundarySpeciesIds`` -- never inferred from the structural
    #: network's own ``constant``/``boundary_condition`` flags, which describe Agent 2's own
    #: intent, not necessarily the compiled model's own actual classification.
    kind: Mapped[ModelSpeciesKind] = mapped_column(_MODEL_SPECIES_KIND, nullable=False)

    #: Always ``None`` today -- Agent 2's own ``SpeciesSpecification`` carries no unit field at
    #: all (confirmed by inspection); kept as a column for forward-compatibility, per task
    #: instructions ("capture units when authoritatively available; otherwise mark them
    #: unknown") -- honestly unknown, always, until a future increment changes this.
    unit: Mapped[str | None] = mapped_column(String)

    catalog: Mapped[ModelSpeciesCatalog] = relationship(back_populates="species")


class ModelCompartment(Base):
    """One real compartment in the captured catalog -- the same canonical id/name every
    ``ModelSpecies.compartment_id``/``compartment_name`` already carries inline, kept here as
    its own validated set so "does this species' own compartment actually exist" has something
    durable to check against (task instructions: "validate ... compartment references")."""

    __tablename__ = "model_compartment"
    __table_args__ = (
        UniqueConstraint(
            "model_species_catalog_id",
            "compartment_id",
            name="uq_model_compartment_catalog_id_compartment_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    model_species_catalog_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_species_catalog.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    compartment_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    volume_unit: Mapped[str | None] = mapped_column(String)
    species_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    catalog: Mapped[ModelSpeciesCatalog] = relationship(back_populates="compartments")


__all__ = ["ModelCompartment", "ModelSpecies", "ModelSpeciesCatalog"]
