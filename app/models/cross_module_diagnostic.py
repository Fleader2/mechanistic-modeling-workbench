"""CrossModuleDiagnosticRun / CrossModuleDiagnostic: a versioned batch of detected
cross-module consistency findings for one hierarchy run, and the individual findings
themselves (Cross-Module Consistency and Reconciliation Diagnostics increment).

See ``docs/13_cross_module_diagnostics.md``. A diagnostic *run* is one invocation of the
consistency sweep over one hierarchy run's own already-persisted modules, boundary ports,
and Agent3/4/5 results -- never a new agent execution (task instructions §7). Idempotent by
``input_fingerprint`` against the latest existing run for the same hierarchy run (mirroring
``ModuleAggregate``'s own established pattern): an unchanged source state returns the
existing run and its own already-persisted findings untouched; a changed one creates a new,
separately-numbered version, and the previous version's own findings are never altered or
deleted.

**Detection content is immutable** (category/severity/message/``affected_model_module_ids``/
``evidence_payload``/``input_fingerprint`` on both tables): no persistence function in this
repository ever updates them. **The one deliberate exception** is a finding's own review
annotation (``review_status``/``review_note``/``reviewed_by``/``reviewed_at``) -- task
instructions §5 explicitly asks for "mark a diagnostic as reviewed/resolved with a human
note, without altering source results." Marking a finding reviewed is therefore the one
targeted ``UPDATE`` this increment performs anywhere, and it only ever touches those four
columns, never the finding's own detection content or anything upstream it describes.

``CrossModuleDiagnostic`` ``ON DELETE CASCADE`` from ``CrossModuleDiagnosticRun`` -- a finding
has no independent meaning apart from the run batch that produced it, the identical
"no independent existence apart from its parent" precedent ``module_boundary_port`` already
uses. ``CrossModuleDiagnosticRun`` itself ``ON DELETE RESTRICT`` from ``run_record`` -- a
durable provenance record, the identical precedent ``model_module``/``module_execution
_snapshot``/``module_aggregate`` already use.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    CrossModuleDiagnosticCategory,
    DiagnosticReviewStatus,
    DiagnosticSeverity,
)
from app.models.run_record import RunRecord

_CROSS_MODULE_DIAGNOSTIC_CATEGORY = Enum(
    CrossModuleDiagnosticCategory, name="cross_module_diagnostic_category", create_type=False
)
_DIAGNOSTIC_SEVERITY = Enum(DiagnosticSeverity, name="diagnostic_severity", create_type=False)
_DIAGNOSTIC_REVIEW_STATUS = Enum(
    DiagnosticReviewStatus, name="diagnostic_review_status", create_type=False
)


class CrossModuleDiagnosticRun(Base):
    """One immutable, versioned invocation of the cross-module consistency sweep over one
    hierarchy run."""

    __tablename__ = "cross_module_diagnostic_run"
    __table_args__ = (
        Index(
            "ix_cross_module_diagnostic_run_hierarchy_run_record_id",
            "hierarchy_run_record_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    hierarchy_run_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "run_record.id",
            ondelete="RESTRICT",
            name="fk_cross_module_diagnostic_run_hierarchy_run_record_id",
        ),
        nullable=False,
    )
    #: 1-based, increasing per ``hierarchy_run_record_id`` -- never reused, never decremented.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: ``sha256`` hex digest of the canonical encoding of every module's own comparable facts
    #: (boundary ports, latest calibration/validation results) this sweep examined -- this
    #: table's own idempotency key (``app.persistence.cross_module_diagnostic
    #: .compute_diagnostic_run_fingerprint``).
    input_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    #: Denormalized count of this run's own findings -- a convenience for a caller that only
    #: wants "how many, and how severe" without decoding every finding's own row.
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    hierarchy_run_record: Mapped[RunRecord] = relationship()
    findings: Mapped[list[CrossModuleDiagnostic]] = relationship(
        back_populates="diagnostic_run", order_by="CrossModuleDiagnostic.created_at.asc()"
    )


class CrossModuleDiagnostic(Base):
    """One detected cross-module consistency finding."""

    __tablename__ = "cross_module_diagnostic"
    __table_args__ = (Index("ix_cross_module_diagnostic_diagnostic_run_id", "diagnostic_run_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    diagnostic_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "cross_module_diagnostic_run.id",
            ondelete="CASCADE",
            name="fk_cross_module_diagnostic_diagnostic_run_id",
        ),
        nullable=False,
    )

    category: Mapped[CrossModuleDiagnosticCategory] = mapped_column(
        _CROSS_MODULE_DIAGNOSTIC_CATEGORY, nullable=False
    )
    severity: Mapped[DiagnosticSeverity] = mapped_column(_DIAGNOSTIC_SEVERITY, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    #: Opaque JSON array of ``model_module`` id strings -- every module this one finding is
    #: about (almost always two, for a pairwise comparison).
    affected_model_module_ids: Mapped[str] = mapped_column(Text, nullable=False)
    #: Opaque, pre-serialized JSON object -- decoded nowhere except ``app.persistence
    #: .cross_module_diagnostic.read_diagnostic_evidence``, the one documented site. Carries
    #: the full comparison detail (species/parameter ids, the compared values themselves, and
    #: every contributing ``run_record_id``/``execution_snapshot_id``/``aggregate_id``) --
    #: never the bare conclusion without the evidence that produced it.
    evidence_payload: Mapped[str] = mapped_column(Text, nullable=False)

    #: The one mutable field group on this table -- see module docstring.
    review_status: Mapped[DiagnosticReviewStatus] = mapped_column(
        _DIAGNOSTIC_REVIEW_STATUS,
        nullable=False,
        default=DiagnosticReviewStatus.UNREVIEWED,
        server_default=DiagnosticReviewStatus.UNREVIEWED.value,
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    diagnostic_run: Mapped[CrossModuleDiagnosticRun] = relationship(back_populates="findings")


__all__ = ["CrossModuleDiagnostic", "CrossModuleDiagnosticRun"]
