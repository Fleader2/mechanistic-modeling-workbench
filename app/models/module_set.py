"""Module-Set domain model: a durable, versioned, user-curated grouping of ``ModelModule`` rows,
distinct from (and sitting above) the automated hierarchical-search machinery that materializes
them. See ``docs/20_module_set_domain_contract.md`` for the full proposal and
``docs/21_module_set_first_increment.md`` for exactly what this first increment implements.

**Scope of this increment, reflected directly in these tables' own columns**: every
``ModuleSetMember``/``ModuleSetDraftMember`` row created by this increment references a
pre-existing, already-materialized ``ModelModule`` (``model_module_id`` is ``NOT NULL`` on both) --
manual editing/split/merge, and the ``ModelModule`` schema change that would let a member
*materialize* a fresh row instead of referencing one, are deferred (``docs/20`` §2.1). No
``ModuleLineageEdge`` table exists yet for the identical reason. Hierarchy and display name are
therefore never duplicated onto these tables either: hierarchy is derived at read time from each
member's own ``model_module_id -> ModelModule.parent_model_module_id``, and a module's display
name is honestly whatever the GUI shows from ``ModelModule`` itself (which has none today) rather
than an invented label.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ModuleSetDraftStatus, ModuleSetOriginMethod
from app.models.model import Model
from app.models.model_module import ModelModule
from app.models.run_record import RunRecord
from app.models.subproject import Subproject

_MODULE_SET_ORIGIN_METHOD = Enum(
    ModuleSetOriginMethod, name="module_set_origin_method", create_type=False
)
_MODULE_SET_DRAFT_STATUS = Enum(
    ModuleSetDraftStatus, name="module_set_draft_status", create_type=False
)


class ModuleSet(Base):
    """A durable identity, nothing else -- one named, study-scoped module-partitioning scheme
    that may gain many immutable versions over time. See ``docs/20`` for why this carries no
    ``model_id`` of its own: a set's identity is independent of any one model version; only each
    *version* beneath it pins one.
    """

    __tablename__ = "module_set"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    subproject_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subproject.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    #: e.g. "MS-001". Assigned atomically at "save as new module set" time -- never pre-assigned
    #: to a draft. Study-scoped sequential allocation (see persist_module_set.py).
    stable_identifier: Mapped[str] = mapped_column(String, nullable=False)
    #: e.g. "Expert partition". Free text; deliberately not unique -- stable_identifier is the
    #: true identity (two sets may share a name, per Figma's own "Expert partition" / "Expert
    #: partition -- alternative" example).
    name: Mapped[str] = mapped_column(String, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    subproject: Mapped[Subproject] = relationship()
    versions: Mapped[list[ModuleSetVersion]] = relationship(
        back_populates="module_set", order_by="ModuleSetVersion.version"
    )
    drafts: Mapped[list[ModuleSetDraft]] = relationship(back_populates="module_set")


class ModuleSetVersion(Base):
    """One immutable, saved version of one ``ModuleSet``. Pins exactly one model version
    (``model_id``) at save time -- a later version of the same set may pin a *different* model
    (a set's identity spans model versions; see ``docs/20`` §9), but never silently: this
    increment's own one draft source (an existing run) never produces two versions of a set
    pinning different models, so that "revalidation" path is not exercised here.

    Never updated after creation (no ``updated_at``) -- the identical discipline
    ``ModuleExecutionSnapshot`` already establishes for "no persistence function anywhere issues
    an UPDATE against this row."
    """

    __tablename__ = "module_set_version"
    __table_args__ = (
        UniqueConstraint("module_set_id", "version", name="uq_module_set_version_set_id_version"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    module_set_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("module_set.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: 1-based, strictly increasing per module_set_id -- never reused or decremented (the
    #: identical idiom ModuleAggregate.version/CrossModuleDiagnosticRun.version already use).
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    model_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("model.id", ondelete="RESTRICT"), nullable=False
    )

    origin_method: Mapped[ModuleSetOriginMethod] = mapped_column(
        _MODULE_SET_ORIGIN_METHOD, nullable=False
    )
    #: The hierarchical-search run whose output this version's draft was seeded from, if any --
    #: a provenance pointer, never an identity (see docs/20 §5: this is not how a set's own
    #: version lineage is tracked -- base_version_id is).
    generation_run_record_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("run_record.id", ondelete="RESTRICT")
    )
    #: "Draft based on MS-001 v1" -- recorded regardless of whether the save became a new set or
    #: a new version of an existing one.
    base_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("module_set_version.id", ondelete="RESTRICT")
    )

    version_note: Mapped[str | None] = mapped_column(Text)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    saved_by: Mapped[str | None] = mapped_column(String)

    module_set: Mapped[ModuleSet] = relationship(back_populates="versions")
    model: Mapped[Model] = relationship()
    generation_run_record: Mapped[RunRecord | None] = relationship()
    base_version: Mapped[ModuleSetVersion | None] = relationship(remote_side="ModuleSetVersion.id")
    members: Mapped[list[ModuleSetMember]] = relationship(
        back_populates="module_set_version", cascade="all, delete-orphan", passive_deletes=True
    )


class ModuleSetMember(Base):
    """One module belonging to one saved ``ModuleSetVersion``. Always resolves to a real,
    executable ``ModelModule`` row (``model_module_id`` is ``NOT NULL``) -- the central
    reconciliation this increment relies on (``docs/20`` §2): every existing simulate/calibrate/
    validate/aggregate/diagnose code path keeps working unchanged, because it only ever sees a
    plain ``model_module_id``, never a "module set" concept.

    No independent meaning apart from its own version -- ``CASCADE``, the same "no independent
    existence apart from its parent" precedent ``CrossModuleDiagnostic`` already uses from
    ``CrossModuleDiagnosticRun``.
    """

    __tablename__ = "module_set_member"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    module_set_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("module_set_version.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_module_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_module.id", ondelete="RESTRICT"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    module_set_version: Mapped[ModuleSetVersion] = relationship(back_populates="members")
    model_module: Mapped[ModelModule] = relationship()


class ModuleSetDraft(Base):
    """Mutable working state leading up to an explicit save. Not yet attached to any ``ModuleSet``
    identity until the user chooses "save as new module set" vs. "save new set version" **at
    save time** (``module_set_id`` stays ``NULL`` until then, per Figma's own "New set ID:
    assigned only when you confirm").

    This increment's own one supported creation path is ``base_run_record_id`` set (seeded,
    unedited, from an existing, model-bearing, ``SUCCEEDED`` hierarchical run) --
    ``base_version_id`` (reopen-and-continue-editing) and a from-scratch manual draft (both
    ``NULL``) are schema-ready but not reachable through any persistence function this increment
    ships, since editing is deferred.
    """

    __tablename__ = "module_set_draft"
    __table_args__ = (
        Index(
            "uq_module_set_draft_open_per_set",
            "module_set_id",
            unique=True,
            postgresql_where=text("status = 'OPEN' AND module_set_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    subproject_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subproject.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("model.id", ondelete="RESTRICT"), nullable=False
    )
    module_set_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("module_set.id", ondelete="RESTRICT")
    )
    base_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("module_set_version.id", ondelete="RESTRICT")
    )
    base_run_record_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("run_record.id", ondelete="RESTRICT")
    )

    origin_method: Mapped[ModuleSetOriginMethod] = mapped_column(
        _MODULE_SET_ORIGIN_METHOD, nullable=False
    )
    status: Mapped[ModuleSetDraftStatus] = mapped_column(
        _MODULE_SET_DRAFT_STATUS,
        nullable=False,
        default=ModuleSetDraftStatus.OPEN,
        server_default=ModuleSetDraftStatus.OPEN.value,
    )
    resulting_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("module_set_version.id", ondelete="RESTRICT")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[str | None] = mapped_column(String)
    updated_by: Mapped[str | None] = mapped_column(String)

    subproject: Mapped[Subproject] = relationship()
    model: Mapped[Model] = relationship(foreign_keys=[model_id])
    module_set: Mapped[ModuleSet | None] = relationship(back_populates="drafts")
    base_version: Mapped[ModuleSetVersion | None] = relationship(foreign_keys=[base_version_id])
    base_run_record: Mapped[RunRecord | None] = relationship(foreign_keys=[base_run_record_id])
    resulting_version: Mapped[ModuleSetVersion | None] = relationship(
        foreign_keys=[resulting_version_id]
    )
    members: Mapped[list[ModuleSetDraftMember]] = relationship(
        back_populates="draft", cascade="all, delete-orphan", passive_deletes=True
    )


class ModuleSetDraftMember(Base):
    """One module included in one open (or since-saved/discarded) draft.

    **As implemented in this increment**: ``model_module_id`` is ``NOT NULL`` -- every draft
    member this increment can ever create already references an existing, unedited materialized
    module (its only draft source). ``module_identity_id``/``parent_draft_member_id``/``name``/
    ``membership_payload`` (the full design's own columns for manual editing) are deliberately
    not part of this table at all yet -- adding them later is an additive ``ALTER TABLE``, not a
    redesign (``docs/20`` §3).
    """

    __tablename__ = "module_set_draft_member"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    draft_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("module_set_draft.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_module_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model_module.id", ondelete="RESTRICT"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    draft: Mapped[ModuleSetDraft] = relationship(back_populates="members")
    model_module: Mapped[ModelModule] = relationship()


__all__ = [
    "ModuleSet",
    "ModuleSetDraft",
    "ModuleSetDraftMember",
    "ModuleSetMember",
    "ModuleSetVersion",
]
