"""Response schemas for ``/api/v1/projects/{project_id}/subprojects/{subproject_id}/models``.

``ModelListItem`` follows ``app.schemas.project.ProjectListItem``'s own
"expose only what the screen shows, from columns that really exist"
precedent. The "03 — Modeling Study" Figma screen's "Models" table also
shows "Construction" (e.g. "Protein abundance", "Literature kinetics") and
"Calibration / validation" (e.g. "WT time course / ACC1 perturbation", "Not
assigned") columns -- neither has a backing column on ``Model`` (see
``app/models/model.py``), and per that increment's own explicit
instruction, scientific readiness/calibration/evidence assignments are
never invented. Only model identity (``name``, ``stable_identifier``),
``version_label``, and ``status`` -- real columns -- are exposed here.

``ModelDetail`` follows ``app.schemas.subproject.SubprojectDetail``'s own
"every real column" precedent instead, for the "05 — Model Overview"
screen's own metadata (``docs/19_model_overview_increment.md``). Figma's
own reference also shows "Scope" / "Structure" / "Parameters" summary
counts, a "Construction: ... Calibration: ... Validation: ..." sentence,
and a parameter-level "Values needing review" table -- none of that has any
backing column or table anywhere in this schema (no species/reaction/
parameter content is ever persisted for a ``Model``; see that increment's
own "durability audit"), and is never invented here.

``ModelLineage`` is the "History" tab's own honest content: the
``parent_model_id`` chain between ``Model`` rows is the only version
lineage this schema durably records -- there is no fine-grained,
per-parameter change-log table (no "changed by," "evidence," or "before →
after value" columns exist anywhere; this system has no user/author entity
at all), unlike Figma's own richer "History" tab mock. ``parent``/
``children`` are included only when they belong to the *same* subproject
as the model itself -- a parent or child that exists but belongs to a
different Modeling Study is disclosed via the two
``*_out_of_scope``/``*_out_of_scope_count`` fields instead of being silently
dropped (dishonest) or exposed cross-study (an ownership leak).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ModelSourceType, ModelStatus


class ModelListItem(BaseModel):
    """One row of the "03 — Modeling Study" screen's "Models" table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    stable_identifier: str
    name: str
    version_label: str | None
    status: ModelStatus


class ModelDetail(BaseModel):
    """Every column of one ``Model`` row, for the "05 — Model Overview" screen."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subproject_id: UUID
    stable_identifier: str
    name: str
    source_type: ModelSourceType
    status: ModelStatus
    artifact_reference: str | None
    parent_model_id: UUID | None
    version_label: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ModelLineage(BaseModel):
    """The "History" tab's own honest content -- see module docstring."""

    parent: ModelListItem | None
    parent_out_of_scope: bool
    children: list[ModelListItem]
    children_out_of_scope_count: int


__all__ = ["ModelDetail", "ModelLineage", "ModelListItem"]
