"""ModelImportProvenance: an immutable, versioned record of exactly what was uploaded and
found when one ``Model`` row was created via the Whole-Model Antimony Import increment --
never created for a ``GENERATED``/``DERIVED`` model.

Mirrors ``app.models.module_execution_snapshot.ModuleExecutionSnapshot``'s own established
discipline: one row per import (``model_id`` unique -- 1:1), created once, atomically alongside
the ``Model``/``ModelSpeciesCatalog``/``ModelParameterCatalog`` rows it accompanies, and never
updated afterward. ``ON DELETE RESTRICT`` from both ``model`` and ``run_record``: a durable,
independently-meaningful provenance record, never ephemeral workflow bookkeeping.

**Model identity stays separate from file-content identity here by construction**: this row's
own ``original_checksum`` is a plain content fingerprint, never part of ``Model
.stable_identifier`` (caller-supplied, always fresh per upload) -- re-uploading byte-identical
Antimony text creates a new, independent ``Model``/``ModelImportProvenance`` pair, never
silently merged with an earlier one (task instructions: "identical bytes must not silently
merge distinct scientific records").
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.model import Model
from app.models.run_record import RunRecord


class ModelImportProvenance(Base):
    """One immutable, versioned capture of one Antimony-upload's own exact inputs and
    fidelity-audit findings."""

    __tablename__ = "model_import_provenance"
    __table_args__ = (
        UniqueConstraint("model_id", name="uq_model_import_provenance_model_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    model_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model.id", ondelete="RESTRICT", name="fk_model_import_provenance_model_id"),
        nullable=False,
        index=True,
    )
    run_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "run_record.id",
            ondelete="RESTRICT",
            name="fk_model_import_provenance_run_record_id",
        ),
        nullable=False,
    )

    #: The uploaded file's own original name, exactly as supplied -- ``save_blob``'s own
    #: content-addressed storage never tracks this; disclosed here instead.
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    #: Byte-for-byte original Antimony text, durably saved via the existing
    #: ``app.storage.save_model_antimony_text`` content-addressed convention -- the one
    #: artifact ever executed or displayed; never re-serialized or replaced by Agent 2's own
    #: canonical form.
    original_artifact_reference: Mapped[str] = mapped_column(Text, nullable=False)
    original_checksum: Mapped[str] = mapped_column(String, nullable=False)

    #: User-supplied provenance (task instructions: "optional source/reference and
    #: verification notes") -- curator-declared, never validated or interpreted.
    source_reference: Mapped[str | None] = mapped_column(Text)
    #: User-supplied free text. **Never a claim this importer itself makes**: "previously
    #: verified" status is only ever this user-supplied provenance, never inferred from
    #: compilation succeeding (task instructions: "compilation establishes executability, not
    #: biological validation").
    verification_notes: Mapped[str | None] = mapped_column(Text)

    #: Agent 2's own fidelity-audit outcome (``app.harness.model_antimony_import``, through
    #: Agent 2's own, unmodified ``import_antimony``) -- audit-only, never the gate for whether
    #: this ``Model`` is usable (that is Agent 3's own real executability check, which already
    #: must have succeeded before this row, or its owning ``Model`` row, is ever created).
    import_succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    import_error_kind: Mapped[str | None] = mapped_column(String)
    import_message: Mapped[str | None] = mapped_column(Text)
    assignment_rule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rate_rule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    algebraic_rule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    antimony_import_parser_version: Mapped[str | None] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str | None] = mapped_column(String)

    model: Mapped[Model] = relationship()
    run_record: Mapped[RunRecord] = relationship()


__all__ = ["ModelImportProvenance"]
