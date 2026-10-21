"""Response/request schemas for the Module-Set first increment
(``docs/20_module_set_domain_contract.md`` / ``docs/21_module_set_first_increment.md``).

Every "member" schema exposes only what ``ModelModule`` actually has -- no display name is
invented (``ModelModule`` has no ``name`` column; see ``docs/20`` §3) and no "Construction"/
"Calibration · validation"-style scientific claim is fabricated, following every prior
increment's own established "disclose honestly, never invent" convention.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    ModelModuleExecutionStatus,
    ModuleBoundaryResolutionStatus,
    ModuleBoundaryTreatmentType,
    ModulePortDirection,
    ModuleSetDraftStatus,
    ModuleSetOriginMethod,
)
from app.models.model_module import ModelModule
from app.models.module_boundary_port import ModuleBoundaryPort
from app.models.module_set import ModuleSet, ModuleSetDraft, ModuleSetVersion


class HierarchicalRunSummary(BaseModel):
    """One row of the "pick a run to draft a module set from" list."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    model_id: UUID
    created_at: datetime
    module_count: int


class ModuleSetMemberItem(BaseModel):
    """One module within a draft or a saved version. Identity/hierarchy/structure are read
    directly from the real, resolved ``ModelModule`` row this member points at -- never an
    invented display name; hierarchy (``parent_model_module_id``) is the member's own
    *resolved* module's parent, which the frontend matches against sibling members' own
    ``model_module_id``s to derive the set's own tree (never duplicated into this table, per
    ``docs/20`` §6)."""

    id: UUID
    model_module_id: UUID
    module_id: str
    depth: int
    parent_model_module_id: UUID | None
    execution_status: ModelModuleExecutionStatus

    @classmethod
    def from_member(cls, member_row_id: UUID, model_module: ModelModule) -> ModuleSetMemberItem:
        return cls(
            id=member_row_id,
            model_module_id=model_module.id,
            module_id=model_module.module_id,
            depth=model_module.depth,
            parent_model_module_id=model_module.parent_model_module_id,
            execution_status=model_module.execution_status,
        )


class BoundaryPortItem(BaseModel):
    """One ``ModuleBoundaryPort``, with the structural fact (``species_id``/``direction``)
    and the execution-specific decision (``treatment_type``/``initial_value``/``unit``/
    ``decided_by``/``decided_at``) both present but never conflated -- the identical split
    `ModuleBoundaryPort` itself already expresses (``docs/20`` §7)."""

    model_config = ConfigDict(from_attributes=True)

    port_id: str
    species_id: str
    direction: ModulePortDirection
    treatment_type: ModuleBoundaryTreatmentType
    resolution_status: ModuleBoundaryResolutionStatus
    initial_value: Decimal | None
    unit: str | None
    decided_by: str | None
    decided_at: datetime | None

    @classmethod
    def from_port(cls, port: ModuleBoundaryPort) -> BoundaryPortItem:
        return cls.model_validate(port)


class ModuleSetDraftDetail(BaseModel):
    """A draft's own full, read-only inspection view: hierarchy + hand-off to each member's
    own boundary ports (fetched separately, per member, to avoid an N-query eager load no
    caller may need)."""

    id: UUID
    subproject_id: UUID
    model_id: UUID
    module_set_id: UUID | None
    base_run_record_id: UUID | None
    base_version_id: UUID | None
    origin_method: ModuleSetOriginMethod
    status: ModuleSetDraftStatus
    resulting_version_id: UUID | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    members: list[ModuleSetMemberItem]

    @classmethod
    def from_draft(cls, draft: ModuleSetDraft) -> ModuleSetDraftDetail:
        return cls(
            id=draft.id,
            subproject_id=draft.subproject_id,
            model_id=draft.model_id,
            module_set_id=draft.module_set_id,
            base_run_record_id=draft.base_run_record_id,
            base_version_id=draft.base_version_id,
            origin_method=draft.origin_method,
            status=draft.status,
            resulting_version_id=draft.resulting_version_id,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
            created_by=draft.created_by,
            members=[
                ModuleSetMemberItem.from_member(member.id, member.model_module)
                for member in draft.members
            ],
        )


class ModuleSetVersionDetail(BaseModel):
    """One immutable, saved version -- identical shape whether freshly returned by ``save`` or
    read back later by ``reopen`` (``docs/20`` §4, rule 6: reopening is always read-only)."""

    id: UUID
    module_set_id: UUID
    module_set_stable_identifier: str
    module_set_name: str
    version: int
    model_id: UUID
    origin_method: ModuleSetOriginMethod
    generation_run_record_id: UUID | None
    base_version_id: UUID | None
    version_note: str | None
    saved_at: datetime
    saved_by: str | None
    members: list[ModuleSetMemberItem]

    @classmethod
    def from_version(cls, version: ModuleSetVersion) -> ModuleSetVersionDetail:
        return cls(
            id=version.id,
            module_set_id=version.module_set_id,
            module_set_stable_identifier=version.module_set.stable_identifier,
            module_set_name=version.module_set.name,
            version=version.version,
            model_id=version.model_id,
            origin_method=version.origin_method,
            generation_run_record_id=version.generation_run_record_id,
            base_version_id=version.base_version_id,
            version_note=version.version_note,
            saved_at=version.saved_at,
            saved_by=version.saved_by,
            members=[
                ModuleSetMemberItem.from_member(member.id, member.model_module)
                for member in version.members
            ],
        )


class ModuleSetSummary(BaseModel):
    """One row of a Modeling Study's own module-set catalog."""

    id: UUID
    stable_identifier: str
    name: str
    created_at: datetime
    latest_version: int | None
    latest_version_saved_at: datetime | None
    latest_version_origin_method: ModuleSetOriginMethod | None

    @classmethod
    def from_module_set(cls, module_set: ModuleSet) -> ModuleSetSummary:
        latest = max(module_set.versions, key=lambda v: v.version, default=None)
        return cls(
            id=module_set.id,
            stable_identifier=module_set.stable_identifier,
            name=module_set.name,
            created_at=module_set.created_at,
            latest_version=latest.version if latest else None,
            latest_version_saved_at=latest.saved_at if latest else None,
            latest_version_origin_method=latest.origin_method if latest else None,
        )


class CreateModuleSetDraftRequest(BaseModel):
    run_record_id: UUID


class SaveModuleSetDraftRequest(BaseModel):
    mode: Literal["new_set", "new_version"]
    set_name: str | None = None
    existing_set_id: UUID | None = None
    version_note: str | None = None
    saved_by: str | None = None


__all__ = [
    "BoundaryPortItem",
    "CreateModuleSetDraftRequest",
    "HierarchicalRunSummary",
    "ModuleSetDraftDetail",
    "ModuleSetMemberItem",
    "ModuleSetSummary",
    "ModuleSetVersionDetail",
    "SaveModuleSetDraftRequest",
]
