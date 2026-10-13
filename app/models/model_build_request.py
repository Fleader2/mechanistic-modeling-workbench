"""ModelBuildRequest: what the user wants a model built from -- not an
executable model.

See ``docs/02_database_schema.md`` ("Table: model_build_request" and its
eight child tables) and ``docs/01_workbench_architecture.md``.

Replaces the concept Agent 1's own (to-be-retired) migration ``0020``
called ``ModelSpecification`` -- renamed here specifically because Agent 2
(``agent2-antimony-builder``) already has its own, unrelated, in-memory
type of the identical name meaning "the complete assembled executable
model." The two must never be confused; see the architecture audit.

Every reference to an Agent-1-owned biological entity (a compound, a
reaction, a gene, a protein, a compartment, a regulatory interaction, an
enzyme state) is a plain ``(agent1_entity_type, agent1_entity_id)`` pair --
a copied identifier obtained from a future Agent 1 contract, never a
foreign key, since the Workbench cannot reach Agent 1's database and must
never assume it can. ``raw_identifier`` always preserves the user's own
original text when it cannot (yet) be resolved to a copied Agent 1 entity
id -- never discarded, so a later Agent 1 resolution pass has something to
work with.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Text, false, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    ModelBuildRequestGeneProteinRole,
    ModelBuildRequestPathwayRole,
    ModelBuildRequestReactionRole,
    ModelBuildRequestSpeciesRole,
)
from app.models.subproject import Subproject

if TYPE_CHECKING:
    pass

_MBR_SPECIES_ROLE = Enum(
    ModelBuildRequestSpeciesRole, name="model_build_request_species_role", create_type=False
)
_MBR_REACTION_ROLE = Enum(
    ModelBuildRequestReactionRole, name="model_build_request_reaction_role", create_type=False
)
_MBR_GENE_PROTEIN_ROLE = Enum(
    ModelBuildRequestGeneProteinRole,
    name="model_build_request_gene_protein_role",
    create_type=False,
)
_MBR_PATHWAY_ROLE = Enum(
    ModelBuildRequestPathwayRole, name="model_build_request_pathway_role", create_type=False
)


class ModelBuildRequest(Base):
    """What the user wants constructed for one ``Subproject``.

    One build request per subproject: ``subproject_id`` is unique, so a
    subproject's own constraints are revised in place, never versioned as
    separate rows (same policy as Agent 1's own retired ``model_specification``).
    """

    __tablename__ = "model_build_request"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    subproject_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subproject.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    subproject: Mapped[Subproject] = relationship(back_populates="build_request")
    species: Mapped[list[ModelBuildRequestSpecies]] = relationship(
        back_populates="build_request", cascade="all, delete-orphan", passive_deletes=True
    )
    reactions: Mapped[list[ModelBuildRequestReaction]] = relationship(
        back_populates="build_request", cascade="all, delete-orphan", passive_deletes=True
    )
    gene_proteins: Mapped[list[ModelBuildRequestGeneProtein]] = relationship(
        back_populates="build_request", cascade="all, delete-orphan", passive_deletes=True
    )
    compartments: Mapped[list[ModelBuildRequestCompartment]] = relationship(
        back_populates="build_request", cascade="all, delete-orphan", passive_deletes=True
    )
    regulatory_interactions: Mapped[list[ModelBuildRequestRegulatoryInteraction]] = relationship(
        back_populates="build_request", cascade="all, delete-orphan", passive_deletes=True
    )
    enzyme_states: Mapped[list[ModelBuildRequestEnzymeState]] = relationship(
        back_populates="build_request", cascade="all, delete-orphan", passive_deletes=True
    )
    pathways: Mapped[list[ModelBuildRequestPathway]] = relationship(
        back_populates="build_request", cascade="all, delete-orphan", passive_deletes=True
    )
    assumptions: Mapped[list[ModelBuildRequestAssumption]] = relationship(
        back_populates="build_request", cascade="all, delete-orphan", passive_deletes=True
    )


class ModelBuildRequestSpecies(Base):
    """Covers model input/start species, model output/end species, boundary
    species, and seed metabolites in one table, distinguished by ``role``.
    """

    __tablename__ = "model_build_request_species"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_build_request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_build_request.id",
            ondelete="CASCADE",
            name="fk_mbr_species_model_build_request_id_mbr",
        ),
        nullable=False,
        index=True,
    )

    role: Mapped[ModelBuildRequestSpeciesRole] = mapped_column(_MBR_SPECIES_ROLE, nullable=False)

    agent1_entity_type: Mapped[str | None] = mapped_column(String)
    agent1_entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    raw_identifier: Mapped[str | None] = mapped_column(String)

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    build_request: Mapped[ModelBuildRequest] = relationship(back_populates="species")


class ModelBuildRequestReaction(Base):
    """Covers seed reactions, required reactions, and excluded reactions in
    one table.
    """

    __tablename__ = "model_build_request_reaction"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_build_request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_build_request.id",
            ondelete="CASCADE",
            name="fk_mbr_reaction_model_build_request_id_mbr",
        ),
        nullable=False,
        index=True,
    )

    role: Mapped[ModelBuildRequestReactionRole] = mapped_column(_MBR_REACTION_ROLE, nullable=False)

    agent1_entity_type: Mapped[str | None] = mapped_column(String)
    agent1_entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    raw_identifier: Mapped[str | None] = mapped_column(String)

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    build_request: Mapped[ModelBuildRequest] = relationship(back_populates="reactions")


class ModelBuildRequestGeneProtein(Base):
    """Covers seed genes/proteins and important genes/proteins in one table.

    ``localization_entity_id``/``localization_raw_identifier`` carry the
    subcellular localization constraint on this one reference -- distinct
    from "compartments to include" (``ModelBuildRequestCompartment``).
    """

    __tablename__ = "model_build_request_gene_protein"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_build_request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_build_request.id",
            ondelete="CASCADE",
            name="fk_mbr_gene_protein_model_build_request_id_mbr",
        ),
        nullable=False,
        index=True,
    )

    role: Mapped[ModelBuildRequestGeneProteinRole] = mapped_column(
        _MBR_GENE_PROTEIN_ROLE, nullable=False
    )

    agent1_entity_type: Mapped[str | None] = mapped_column(String)
    agent1_entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    raw_identifier: Mapped[str | None] = mapped_column(String)

    localization_entity_type: Mapped[str | None] = mapped_column(String)
    localization_entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    localization_raw_identifier: Mapped[str | None] = mapped_column(String)

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    build_request: Mapped[ModelBuildRequest] = relationship(back_populates="gene_proteins")


class ModelBuildRequestCompartment(Base):
    """Compartments the model as a whole should include."""

    __tablename__ = "model_build_request_compartment"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_build_request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_build_request.id",
            ondelete="CASCADE",
            name="fk_mbr_compartment_model_build_request_id_mbr",
        ),
        nullable=False,
        index=True,
    )

    agent1_entity_type: Mapped[str | None] = mapped_column(String)
    agent1_entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    raw_identifier: Mapped[str | None] = mapped_column(String)

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    build_request: Mapped[ModelBuildRequest] = relationship(back_populates="compartments")


class ModelBuildRequestRegulatoryInteraction(Base):
    """Regulatory interactions to include."""

    __tablename__ = "model_build_request_regulatory_interaction"
    __table_args__ = (
        # Explicit, shortened index name: the naming-convention-derived name
        # exceeds PostgreSQL's 63-byte identifier limit.
        Index(
            "ix_mbr_reg_interaction_model_build_request_id",
            "model_build_request_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_build_request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_build_request.id",
            ondelete="CASCADE",
            name="fk_mbr_reg_interaction_model_build_request_id_mbr",
        ),
        nullable=False,
    )

    agent1_entity_type: Mapped[str | None] = mapped_column(String)
    agent1_entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    raw_identifier: Mapped[str | None] = mapped_column(String)

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    build_request: Mapped[ModelBuildRequest] = relationship(
        back_populates="regulatory_interactions"
    )


class ModelBuildRequestEnzymeState(Base):
    """PTMs/protein states to include."""

    __tablename__ = "model_build_request_enzyme_state"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_build_request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_build_request.id",
            ondelete="CASCADE",
            name="fk_mbr_enzyme_state_model_build_request_id_mbr",
        ),
        nullable=False,
        index=True,
    )

    agent1_entity_type: Mapped[str | None] = mapped_column(String)
    agent1_entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    raw_identifier: Mapped[str | None] = mapped_column(String)

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    build_request: Mapped[ModelBuildRequest] = relationship(back_populates="enzyme_states")


class ModelBuildRequestPathway(Base):
    """Pathway scope: inclusion and exclusion.

    No ``Pathway`` entity exists anywhere in this system (confirmed during
    the architecture audit: Agent 1 itself stores bare pathway id/name
    strings for the identical reason), so this stores the source's own
    pathway identifier directly.
    """

    __tablename__ = "model_build_request_pathway"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_build_request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_build_request.id",
            ondelete="CASCADE",
            name="fk_mbr_pathway_model_build_request_id_mbr",
        ),
        nullable=False,
        index=True,
    )

    role: Mapped[ModelBuildRequestPathwayRole] = mapped_column(_MBR_PATHWAY_ROLE, nullable=False)

    external_pathway_id: Mapped[str | None] = mapped_column(String)
    name: Mapped[str | None] = mapped_column(String)

    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    build_request: Mapped[ModelBuildRequest] = relationship(back_populates="pathways")


class ModelBuildRequestAssumption(Base):
    """One user constraint or assumption attached to a ``ModelBuildRequest``.

    The Workbench's own table for this -- unlike Agent 1, which reuses its
    existing ``ModelingAssumption`` table polymorphically, the Workbench has
    no such table to reuse, so this is a small, dedicated one.
    """

    __tablename__ = "model_build_request_assumption"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    model_build_request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "model_build_request.id",
            ondelete="CASCADE",
            name="fk_mbr_assumption_model_build_request_id_mbr",
        ),
        nullable=False,
        index=True,
    )

    assumption: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    build_request: Mapped[ModelBuildRequest] = relationship(back_populates="assumptions")


__all__ = [
    "ModelBuildRequest",
    "ModelBuildRequestAssumption",
    "ModelBuildRequestCompartment",
    "ModelBuildRequestEnzymeState",
    "ModelBuildRequestGeneProtein",
    "ModelBuildRequestPathway",
    "ModelBuildRequestReaction",
    "ModelBuildRequestRegulatoryInteraction",
    "ModelBuildRequestSpecies",
]
