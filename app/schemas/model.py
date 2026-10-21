"""Response schema for ``GET /api/v1/projects/{project_id}/subprojects/{subproject_id}/models``.

Follows ``app.schemas.project.ProjectListItem``'s own "expose only what the
screen shows, from columns that really exist" precedent. The "03 — Modeling
Study" Figma screen's "Models" table also shows "Construction" (e.g.
"Protein abundance", "Literature kinetics") and "Calibration / validation"
(e.g. "WT time course / ACC1 perturbation", "Not assigned") columns --
neither has a backing column on ``Model`` (see ``app/models/model.py``), and
per this increment's own explicit instruction, scientific
readiness/calibration/evidence assignments are never invented. Only model
identity (``name``, ``stable_identifier``), ``version_label``, and
``status`` -- real columns -- are exposed here.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ModelStatus


class ModelListItem(BaseModel):
    """One row of the "03 — Modeling Study" screen's "Models" table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    stable_identifier: str
    name: str
    version_label: str | None
    status: ModelStatus


__all__ = ["ModelListItem"]
