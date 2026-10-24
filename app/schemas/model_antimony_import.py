"""Response/request schemas for the Whole-Model Antimony Import increment's own API surface
(``docs/34``). Mirrors ``app.schemas.time_series_dataset``'s own established preview/save
split: a preview never persists anything; a save re-verifies and persists atomically.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.model_import_provenance import ModelImportProvenance
from app.orchestration.model_antimony_import_orchestrator import AntimonyImportPreview


class AntimonyImportPreviewResponse(BaseModel):
    """Everything the "Preview compilation findings" step shows -- never persisted. Re-run,
    never trusted from this response, at save time."""

    load_succeeded: bool
    load_message: str | None
    floating_species_ids: list[str]
    boundary_species_ids: list[str]
    compartment_ids: list[str]
    global_parameter_ids: list[str]
    assignment_rule_derived_parameter_ids: list[str]
    import_succeeded: bool
    import_error_kind: str | None
    import_message: str | None
    assignment_rule_count: int
    rate_rule_count: int
    algebraic_rule_count: int
    event_count: int

    @classmethod
    def from_preview(cls, preview: AntimonyImportPreview) -> AntimonyImportPreviewResponse:
        return cls(
            load_succeeded=preview.load_succeeded,
            load_message=preview.load_message,
            floating_species_ids=list(preview.floating_species_ids),
            boundary_species_ids=list(preview.boundary_species_ids),
            compartment_ids=list(preview.compartment_ids),
            global_parameter_ids=list(preview.global_parameter_ids),
            assignment_rule_derived_parameter_ids=list(
                preview.assignment_rule_derived_parameter_ids
            ),
            import_succeeded=preview.import_succeeded,
            import_error_kind=preview.import_error_kind,
            import_message=preview.import_message,
            assignment_rule_count=preview.assignment_rule_count,
            rate_rule_count=preview.rate_rule_count,
            algebraic_rule_count=preview.algebraic_rule_count,
            event_count=preview.event_count,
        )


class ModelImportProvenanceItem(BaseModel):
    """Every column of one ``ModelImportProvenance`` row -- only present for an ``IMPORTED``
    model."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    original_checksum: str
    source_reference: str | None
    verification_notes: str | None
    import_succeeded: bool
    import_error_kind: str | None
    import_message: str | None
    assignment_rule_count: int
    rate_rule_count: int
    algebraic_rule_count: int
    event_count: int
    antimony_import_parser_version: str | None
    created_at: datetime
    created_by: str | None

    @classmethod
    def from_model(cls, provenance: ModelImportProvenance) -> ModelImportProvenanceItem:
        return cls.model_validate(provenance)


class AntimonySourceResponse(BaseModel):
    """The read-only Antimony source text for one model's own pinned, verified artifact --
    only present once a species catalog has actually been captured for it (any source_type,
    not only ``IMPORTED``)."""

    antimony_text: str


__all__ = [
    "AntimonyImportPreviewResponse",
    "AntimonySourceResponse",
    "ModelImportProvenanceItem",
]
