"""ModelImportProvenance persistence: create (once, immutably) and read back the exact
provenance one Antimony-upload used.

No scientific logic lives here, and -- deliberately -- no update function exists at all: once
created, a row is never modified by any code in this repository (see
``app.models.model_import_provenance``'s own module docstring for why).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.model_import_provenance import ModelImportProvenance


def create_model_import_provenance(
    *,
    model_id: UUID,
    run_record_id: UUID,
    original_filename: str,
    original_artifact_reference: str,
    original_checksum: str,
    import_succeeded: bool,
    source_reference: str | None = None,
    verification_notes: str | None = None,
    import_error_kind: str | None = None,
    import_message: str | None = None,
    assignment_rule_count: int = 0,
    rate_rule_count: int = 0,
    algebraic_rule_count: int = 0,
    event_count: int = 0,
    antimony_import_parser_version: str | None = None,
    created_by: str | None = None,
    session: Session,
) -> ModelImportProvenance:
    """Create the one, immutable ``ModelImportProvenance`` row for ``model_id``.

    Idempotent by ``model_id`` (its own unique constraint, the natural identity key: one
    imported model, one provenance row): if a row already exists, it is returned unchanged,
    never duplicated and never updated -- a caller replaying an identical save request must
    never retroactively rewrite an already-captured provenance record.
    """
    existing = get_model_import_provenance(session, model_id)
    if existing is not None:
        return existing

    row = ModelImportProvenance(
        model_id=model_id,
        run_record_id=run_record_id,
        original_filename=original_filename,
        original_artifact_reference=original_artifact_reference,
        original_checksum=original_checksum,
        source_reference=source_reference,
        verification_notes=verification_notes,
        import_succeeded=import_succeeded,
        import_error_kind=import_error_kind,
        import_message=import_message,
        assignment_rule_count=assignment_rule_count,
        rate_rule_count=rate_rule_count,
        algebraic_rule_count=algebraic_rule_count,
        event_count=event_count,
        antimony_import_parser_version=antimony_import_parser_version,
        created_by=created_by,
    )
    session.add(row)
    session.flush()
    return row


def get_model_import_provenance(
    session: Session, model_id: UUID
) -> ModelImportProvenance | None:
    """The one ``ModelImportProvenance`` for a given model, or ``None`` (never created for a
    ``GENERATED``/``DERIVED`` model). Read-only."""
    stmt = select(ModelImportProvenance).where(ModelImportProvenance.model_id == model_id)
    return session.scalars(stmt).one_or_none()


__all__ = ["create_model_import_provenance", "get_model_import_provenance"]
