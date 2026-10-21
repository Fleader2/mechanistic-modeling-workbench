"""Module-Set persistence: create a draft from an existing, unedited automated hierarchical
run (or from a saved version, for editing); inspect it; edit a member's name/reaction
membership; discard it; explicitly save it (as a new set, or a new version of an existing one);
read a saved set/version back.

See ``docs/20_module_set_domain_contract.md`` for the full domain model,
``docs/21_module_set_first_increment.md`` for the unedited-draft increment, and
``docs/23_module_set_manual_editing_increment.md`` for module renaming and reaction-membership
editing. Ownership (project/subproject) checks live at the API route layer (mirroring
``app.api.v1.routes.projects``'s own established ``_require_*`` pattern) -- this module trusts
its own callers' contract for *which* subproject a given id belongs to, the identical discipline
``materialize_accepted_modules`` already uses ("the caller's own contract guarantee"), but still
independently re-validates every cross-entity ownership fact this module itself is responsible
for asserting (e.g. that a run or an existing set actually belongs to the subproject a draft
claims to be scoped to) -- never trusting a caller-supplied id pairing blindly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import ModuleSetDraftStatus, ModuleSetOriginMethod, RunStage, RunStatus
from app.models.model_module import ModelModule
from app.models.module_set import (
    ModuleSet,
    ModuleSetDraft,
    ModuleSetDraftMember,
    ModuleSetMember,
    ModuleSetVersion,
)
from app.models.run_record import RunRecord
from app.persistence.model_module import known_component_ids_by_type, list_model_modules_for_run


class ModuleSetDraftAlreadyResolved(ValueError):
    """Raised when ``save_draft``/``discard_draft`` is called on a draft that is no longer
    ``OPEN`` -- the duplicate-save/duplicate-discard protection. Carries the draft's own already-
    resolved state so a caller (the API route) can report it without a second lookup."""

    def __init__(self, draft: ModuleSetDraft) -> None:
        self.draft = draft
        super().__init__(f"ModuleSetDraft {draft.id} is already {draft.status.value}, not OPEN")


class ModuleSetDraftStaleEdit(ValueError):
    """Raised when an edit's ``expected_edit_version`` no longer matches the draft's own
    current ``edit_version`` -- someone else (or another tab) edited this draft first. Carries
    the draft's current, true ``edit_version`` so the caller can refetch and retry, rather than
    silently overwriting the other edit."""

    def __init__(self, draft: ModuleSetDraft, expected_edit_version: int) -> None:
        self.draft = draft
        self.expected_edit_version = expected_edit_version
        super().__init__(
            f"ModuleSetDraft {draft.id} is at edit_version {draft.edit_version}, not "
            f"{expected_edit_version} -- it was edited since last read"
        )


@dataclass(frozen=True)
class ModuleSetDraftValidationFinding:
    """One actionable, blocking problem with a draft's current (possibly mid-edit) state --
    never a style suggestion. ``docs/23`` §"Validation rules" has the full rationale for each
    ``code``."""

    code: Literal["UNASSIGNED_REACTION", "EMPTY_MODULE"]
    message: str
    reaction_id: str | None = None
    member_id: UUID | None = None


class ModuleSetDraftValidationFailed(ValueError):
    """Raised by ``save_draft`` when ``validate_draft`` finds at least one blocking finding --
    save never silently proceeds with unassigned reactions or an emptied-out module. Carries
    the findings so the caller can report all of them, not just the first."""

    def __init__(self, findings: list[ModuleSetDraftValidationFinding]) -> None:
        self.findings = findings
        super().__init__(f"draft has {len(findings)} unresolved validation finding(s)")


def _derive_reaction_ids(model_module: ModelModule) -> list[str]:
    """This module's own real, Agent-2-sourced ``REACTION`` component ids, straight from its
    ``ModelModule.attach_payload`` -- the one existing, reusable mechanism for this
    (``known_component_ids_by_type``, already relied on by calibration/validation), never
    re-derived or inferred from anything else. Sorted for a deterministic baseline."""
    return sorted(known_component_ids_by_type(model_module).get("REACTION", set()))


def _encode_ids(ids: list[str]) -> str:
    return json.dumps(sorted(ids))


def effective_reaction_component_ids(member: ModuleSetMember | ModuleSetDraftMember) -> list[str]:
    """This member's own real, current reaction selection, regardless of whether it was ever
    edited -- ``member.reaction_component_ids`` when set (an edited member, increment 23's own
    "minimal diff" property), or else derived fresh from its resolved ``ModelModule``'s own
    ``attach_payload`` (an unedited member, for which that column is ``NULL`` by design, never
    an empty selection). The one shared, correct version of the "effective ids" logic
    ``ModuleSetMemberItem.from_member``/``ModuleSetDraftMemberItem.from_draft_member`` already
    compute inline for display -- used here by the Module-Set Edited-Module Materialization
    increment wherever a member's real reaction content is needed for a harness call, not just
    a schema response.
    """
    if member.reaction_component_ids is not None:
        return sorted(json.loads(member.reaction_component_ids))
    return _derive_reaction_ids(member.model_module)


def _decode_ids(encoded: str | None) -> list[str]:
    if encoded is None:
        return []
    return json.loads(encoded)


def create_draft_from_run(
    *,
    session: Session,
    subproject_id: UUID,
    run_record_id: UUID,
    created_by: str | None = None,
) -> ModuleSetDraft:
    """Create a new, open draft seeded verbatim from one existing hierarchical run's own
    materialized modules.

    Raises ``ValueError`` if: the run does not belong to ``subproject_id``; the run is not a
    ``SUCCEEDED`` hierarchical-search run (``stage=HARNESS``); the run has no associated
    ``Model`` (``model_id IS NULL`` -- there would be no model version to pin, per
    ``docs/20`` §2.1's own resolution); or the run has no materialized modules to draft at all.
    Never mutates the run, its ``HierarchyNode``/``ModelModule`` rows, or anything else that
    already existed.
    """
    run = session.get(RunRecord, run_record_id)
    if run is None or run.subproject_id != subproject_id:
        raise ValueError(f"no hierarchical run with id {run_record_id} in this Modeling Study")
    if run.stage is not RunStage.HARNESS:
        raise ValueError(f"RunRecord {run_record_id} is not a hierarchical-search run")
    if run.status is not RunStatus.SUCCEEDED:
        raise ValueError(f"RunRecord {run_record_id} is {run.status.value}, not SUCCEEDED")
    if run.model_id is None:
        raise ValueError(
            f"RunRecord {run_record_id} has no associated Model -- there is no model version "
            "to pin a module-set version to"
        )

    modules = list_model_modules_for_run(session, run_record_id)
    if not modules:
        raise ValueError(f"RunRecord {run_record_id} has no materialized modules to draft")

    draft = ModuleSetDraft(
        subproject_id=subproject_id,
        model_id=run.model_id,
        base_run_record_id=run_record_id,
        origin_method=ModuleSetOriginMethod.AUTOMATED,
        status=ModuleSetDraftStatus.OPEN,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(draft)
    session.flush()

    for module in modules:
        reaction_ids = _encode_ids(_derive_reaction_ids(module))
        session.add(
            ModuleSetDraftMember(
                draft_id=draft.id,
                model_module_id=module.id,
                reaction_component_ids=reaction_ids,
                original_reaction_component_ids=reaction_ids,
            )
        )
    session.flush()

    return draft


def create_draft_from_version(
    *,
    session: Session,
    subproject_id: UUID,
    module_set_version_id: UUID,
    created_by: str | None = None,
) -> ModuleSetDraft:
    """Create a new, open, editable draft seeded from one existing saved ``ModuleSetVersion`` --
    the manual-editing increment's own second draft source (``docs/20`` §9's "reopen-and-
    continue-editing" path, unreachable until now).

    Each new ``ModuleSetDraftMember``'s own ``original_reaction_component_ids`` is this fresh
    draft's own baseline: whatever the version's ``ModuleSetMember`` already shows as current
    (its own prior edit round's result if it was edited, or its resolved ``ModelModule``'s own
    membership if it was never edited) -- *not* re-derived from the ``ModelModule`` every time,
    so a second edit round diffs against "what the saved version actually says," never silently
    discarding a prior edit round's own result.

    Raises ``ValueError`` if the version does not belong to ``subproject_id`` (via its own
    ``ModuleSet.subproject_id``). The "at most one OPEN draft per module_set_id" partial unique
    index (unchanged since increment 21) already prevents two concurrent edit sessions on the
    same set. Never mutates the version, its members, or anything else that already existed.
    """
    version = session.get(ModuleSetVersion, module_set_version_id)
    if version is None or version.module_set.subproject_id != subproject_id:
        raise ValueError(
            f"no module-set version with id {module_set_version_id} in this Modeling Study"
        )

    draft = ModuleSetDraft(
        subproject_id=subproject_id,
        model_id=version.model_id,
        module_set_id=version.module_set_id,
        base_version_id=version.id,
        origin_method=version.origin_method,
        status=ModuleSetDraftStatus.OPEN,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(draft)
    session.flush()

    for member in version.members:
        current_ids = (
            _decode_ids(member.reaction_component_ids)
            if member.reaction_component_ids is not None
            else _derive_reaction_ids(member.model_module)
        )
        encoded = _encode_ids(current_ids)
        session.add(
            ModuleSetDraftMember(
                draft_id=draft.id,
                model_module_id=member.model_module_id,
                display_name=member.display_name,
                reaction_component_ids=encoded,
                original_reaction_component_ids=encoded,
            )
        )
    session.flush()

    return draft


def get_draft(session: Session, draft_id: UUID) -> ModuleSetDraft | None:
    """One ``ModuleSetDraft`` row by id, or ``None``. Read-only."""
    return session.get(ModuleSetDraft, draft_id)


def get_draft_for_subproject(
    session: Session, subproject_id: UUID, draft_id: UUID
) -> ModuleSetDraft | None:
    """One ``ModuleSetDraft`` row by id, but only if it belongs to ``subproject_id`` --
    identical ownership-scoping convention as ``app.persistence.subproject
    .get_subproject_for_project``. Read-only."""
    draft = session.get(ModuleSetDraft, draft_id)
    if draft is None or draft.subproject_id != subproject_id:
        return None
    return draft


def list_drafts_for_subproject(
    session: Session, subproject_id: UUID, *, include_discarded: bool = False
) -> list[ModuleSetDraft]:
    """Every draft for one Modeling Study, newest first. Excludes ``DISCARDED`` drafts by
    default -- "hidden from normal listings," the decided rule (``docs/20`` §9) -- pass
    ``include_discarded=True`` for the one explicit audit-trail view that needs them. Read-only.
    """
    stmt = select(ModuleSetDraft).where(ModuleSetDraft.subproject_id == subproject_id)
    if not include_discarded:
        stmt = stmt.where(ModuleSetDraft.status != ModuleSetDraftStatus.DISCARDED)
    stmt = stmt.order_by(ModuleSetDraft.created_at.desc())
    return list(session.scalars(stmt))


def discard_draft(session: Session, draft_id: UUID) -> ModuleSetDraft:
    """Soft-mark one draft ``DISCARDED`` -- never hard-deleted (the decided rule, ``docs/20``
    §9). Raises ``ModuleSetDraftAlreadyResolved`` if the draft is not currently ``OPEN`` (a
    draft can be discarded at most once, identical in spirit to save's own duplicate-action
    protection)."""
    draft = session.get(ModuleSetDraft, draft_id)
    if draft is None:
        raise ValueError(f"no ModuleSetDraft with id {draft_id}")
    if draft.status is not ModuleSetDraftStatus.OPEN:
        raise ModuleSetDraftAlreadyResolved(draft)

    draft.status = ModuleSetDraftStatus.DISCARDED
    session.flush()
    return draft


def _sibling_members(
    draft: ModuleSetDraft, member: ModuleSetDraftMember
) -> list[ModuleSetDraftMember]:
    """Every draft member sharing ``member``'s own hierarchical parent -- its own
    ``ModelModule.parent_model_module_id``, including members where that is ``None`` (multiple
    top-level modules are siblings of each other too). This, not any name or position, is the
    "hierarchy rule" a reaction may move within -- fixed for the life of a draft, since editing
    never changes which ``ModelModule`` a member resolves to."""
    group_key = member.model_module.parent_model_module_id
    return [m for m in draft.members if m.model_module.parent_model_module_id == group_key]


def edit_draft_member(
    *,
    session: Session,
    draft_id: UUID,
    member_id: UUID,
    expected_edit_version: int,
    display_name: str | None = None,
    reaction_component_ids: list[str] | None = None,
) -> ModuleSetDraft:
    """Rename a draft member and/or change its reaction membership, within one hierarchical
    sibling group (``docs/23`` §"Validation rules"). Moving a reaction into ``member_id`` that
    is currently owned by a sibling silently (and only ever) reassigns it away from that
    sibling, within the same transaction -- a reaction can never be duplicated across members
    by construction, never merely checked for afterward.

    Raises ``ValueError`` if: neither ``display_name`` nor ``reaction_component_ids`` is given;
    ``display_name`` is empty/whitespace-only; ``member_id`` does not belong to ``draft_id``; or
    any id in ``reaction_component_ids`` is not a real id known to this member's own sibling
    group as of this draft's own creation (never invented, never matched by name).
    ``ModuleSetDraftAlreadyResolved`` if the draft is not ``OPEN``. ``ModuleSetDraftStaleEdit``
    if ``expected_edit_version`` no longer matches the draft's own current value.

    Never touches ``ModelModule``/``HierarchyNode``/``RunRecord``/``ModuleBoundaryPort`` -- only
    this draft's own member rows and ``origin_method``/``edit_version``.
    """
    if display_name is None and reaction_component_ids is None:
        raise ValueError("edit_draft_member requires display_name and/or reaction_component_ids")

    draft = session.get(ModuleSetDraft, draft_id)
    if draft is None:
        raise ValueError(f"no ModuleSetDraft with id {draft_id}")
    if draft.status is not ModuleSetDraftStatus.OPEN:
        raise ModuleSetDraftAlreadyResolved(draft)
    if draft.edit_version != expected_edit_version:
        raise ModuleSetDraftStaleEdit(draft, expected_edit_version)

    member = next((m for m in draft.members if m.id == member_id), None)
    if member is None:
        raise ValueError(f"no member with id {member_id} in draft {draft_id}")

    if display_name is not None:
        if not display_name.strip():
            raise ValueError("display_name must not be empty")
        member.display_name = display_name.strip()

    if reaction_component_ids is not None:
        proposed = set(reaction_component_ids)
        if not proposed:
            raise ValueError("reaction_component_ids must not be empty")

        siblings = _sibling_members(draft, member)
        group_universe = {
            rid for m in siblings for rid in _decode_ids(m.original_reaction_component_ids)
        }
        unknown = proposed - group_universe
        if unknown:
            raise ValueError(
                f"reaction id(s) {sorted(unknown)} are not known to this module's own "
                "hierarchical sibling group as of this draft's own creation -- membership "
                "can only be redistributed among already-known reactions, never invented"
            )

        for sibling in siblings:
            if sibling.id == member.id:
                continue
            sibling_current = set(_decode_ids(sibling.reaction_component_ids))
            taken = sibling_current & proposed
            if taken:
                sibling.reaction_component_ids = _encode_ids(sorted(sibling_current - taken))

        member.reaction_component_ids = _encode_ids(sorted(proposed))

    if any(
        m.display_name is not None
        or _decode_ids(m.reaction_component_ids) != _decode_ids(m.original_reaction_component_ids)
        for m in draft.members
    ):
        draft.origin_method = ModuleSetOriginMethod.MIXED_EDITED

    draft.edit_version += 1
    session.flush()
    return draft


def validate_draft(draft: ModuleSetDraft) -> list[ModuleSetDraftValidationFinding]:
    """Every blocking finding against a draft's own current (possibly mid-edit) state --
    purely a read over already-loaded member rows, no query of its own. Scoped per
    hierarchical sibling group (``docs/23`` §"Validation rules"): a reaction can only ever be
    unassigned *within* the group it has always belonged to, since editing never lets a
    reaction cross group boundaries in the first place.

    ``UNASSIGNED_REACTION``: a reaction present in some member's own ``original_
    reaction_component_ids`` for this group, but not currently owned by any member of it.
    ``EMPTY_MODULE``: a member whose current reaction membership is empty.
    """
    findings: list[ModuleSetDraftValidationFinding] = []
    seen_groups: set[UUID | None] = set()
    for member in draft.members:
        group_key = member.model_module.parent_model_module_id
        if group_key in seen_groups:
            continue
        seen_groups.add(group_key)

        siblings = _sibling_members(draft, member)
        group_universe = {
            rid for m in siblings for rid in _decode_ids(m.original_reaction_component_ids)
        }
        currently_assigned = {
            rid for m in siblings for rid in _decode_ids(m.reaction_component_ids)
        }
        for missing in sorted(group_universe - currently_assigned):
            findings.append(
                ModuleSetDraftValidationFinding(
                    code="UNASSIGNED_REACTION",
                    message=(
                        f"Reaction {missing!r} is not currently assigned to any module in its "
                        "own hierarchical sibling group."
                    ),
                    reaction_id=missing,
                )
            )
        for sibling in siblings:
            if not _decode_ids(sibling.reaction_component_ids):
                findings.append(
                    ModuleSetDraftValidationFinding(
                        code="EMPTY_MODULE",
                        message="This module has no reactions assigned to it.",
                        member_id=sibling.id,
                    )
                )
    return findings


def _allocate_stable_identifier(session: Session, subproject_id: UUID) -> str:
    """The next sequential ``"MS-00N"`` display id for one Modeling Study -- simple counting
    allocation (this is a single-user local Workbench with no concurrent-write contention to
    guard against, the identical assumption every other zero-auth convention in this schema
    already makes)."""
    count = session.execute(
        select(func.count(ModuleSet.id)).where(ModuleSet.subproject_id == subproject_id)
    ).scalar_one()
    return f"MS-{count + 1:03d}"


def save_draft(
    *,
    session: Session,
    draft_id: UUID,
    mode: Literal["new_set", "new_version"],
    set_name: str | None = None,
    existing_set_id: UUID | None = None,
    version_note: str | None = None,
    saved_by: str | None = None,
) -> ModuleSetVersion:
    """Explicitly save one open draft as either a brand new ``ModuleSet`` (``mode="new_set"``)
    or the next version of an existing one (``mode="new_version"``).

    Raises ``ModuleSetDraftAlreadyResolved`` if the draft is not ``OPEN`` -- the duplicate-save
    protection; a second call with the identical ``draft_id`` never creates a second version.
    Raises ``ValueError`` for: an empty ``set_name`` on ``mode="new_set"``; a missing/foreign
    ``existing_set_id`` on ``mode="new_version"`` (must belong to the draft's own subproject);
    or an attempt to save a new version of an existing set whose own latest version pins a
    *different* model than this draft -- the decided "changing that association requires
    explicit revalidation" rule (``docs/20`` §9); this increment implements no revalidation path,
    so that save is rejected outright rather than silently applied.

    Never creates a new ``ModelModule`` row -- every ``ModuleSetMember`` this increment can ever
    produce references the pre-existing module its ``ModuleSetDraftMember`` already named
    (``docs/20`` §2.1). Never mutates any `ModelModule`/`ModuleBoundaryPort`/
    `ModuleExecutionSnapshot`/`RunRecord` row that already existed.

    Raises ``ModuleSetDraftValidationFailed`` if ``validate_draft`` finds any blocking finding
    (an unassigned reaction, or a module edited down to zero reactions) -- save never proceeds
    with an incomplete edit, even partially.
    """
    draft = session.get(ModuleSetDraft, draft_id)
    if draft is None:
        raise ValueError(f"no ModuleSetDraft with id {draft_id}")
    if draft.status is not ModuleSetDraftStatus.OPEN:
        raise ModuleSetDraftAlreadyResolved(draft)

    findings = validate_draft(draft)
    if findings:
        raise ModuleSetDraftValidationFailed(findings)

    if mode == "new_set":
        if not isinstance(set_name, str) or not set_name.strip():
            raise ValueError('save_draft requires a non-empty set_name for mode="new_set"')
        module_set = ModuleSet(
            subproject_id=draft.subproject_id,
            stable_identifier=_allocate_stable_identifier(session, draft.subproject_id),
            name=set_name,
        )
        session.add(module_set)
        session.flush()
        version_number = 1
        base_version_id = draft.base_version_id
    elif mode == "new_version":
        if existing_set_id is None:
            raise ValueError('save_draft requires existing_set_id for mode="new_version"')
        module_set = session.get(ModuleSet, existing_set_id)
        if module_set is None or module_set.subproject_id != draft.subproject_id:
            raise ValueError(
                f"no ModuleSet with id {existing_set_id} in this draft's own Modeling Study"
            )
        latest = session.execute(
            select(ModuleSetVersion)
            .where(ModuleSetVersion.module_set_id == module_set.id)
            .order_by(ModuleSetVersion.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest is not None and latest.model_id != draft.model_id:
            raise ValueError(
                f"ModuleSet {existing_set_id}'s latest version (v{latest.version}) pins a "
                f"different model than this draft -- changing a set's pinned model requires "
                "explicit revalidation, not yet supported"
            )
        version_number = (latest.version if latest is not None else 0) + 1
        base_version_id = draft.base_version_id or (latest.id if latest is not None else None)
    else:  # pragma: no cover -- Literal already constrains valid callers
        raise ValueError(f"save_draft mode must be 'new_set' or 'new_version', got {mode!r}")

    version = ModuleSetVersion(
        module_set_id=module_set.id,
        version=version_number,
        model_id=draft.model_id,
        origin_method=draft.origin_method,
        generation_run_record_id=draft.base_run_record_id,
        base_version_id=base_version_id,
        version_note=version_note,
        saved_by=saved_by,
    )
    # `saved_at` is deliberately left to the column's own `server_default=func.now()` -- the
    # identical convention every other `created_at` column in this schema already uses -- never
    # set from Python here. Setting it explicitly would bypass that server-assigned value with
    # a client-side `datetime.now()`, which round-trips back through a later read in whatever
    # timezone the database connection itself reports (not necessarily UTC), making a freshly
    # saved response's own `saved_at` serialize with a different (if equally correct) UTC offset
    # than a later `GET` of the identical row -- confirmed live by this increment's own
    # reopen-immutability test before this fix.
    session.add(version)
    session.flush()

    for draft_member in draft.members:
        membership_edited = _decode_ids(draft_member.reaction_component_ids) != _decode_ids(
            draft_member.original_reaction_component_ids
        )
        session.add(
            ModuleSetMember(
                module_set_version_id=version.id,
                model_module_id=draft_member.model_module_id,
                display_name=draft_member.display_name,
                reaction_component_ids=(
                    draft_member.reaction_component_ids if membership_edited else None
                ),
            )
        )

    draft.module_set_id = module_set.id
    draft.status = ModuleSetDraftStatus.SAVED
    draft.resulting_version_id = version.id
    draft.updated_by = saved_by
    session.flush()

    return version


def get_module_set(session: Session, module_set_id: UUID) -> ModuleSet | None:
    """One ``ModuleSet`` row by id, or ``None``. Read-only."""
    return session.get(ModuleSet, module_set_id)


def get_module_set_for_subproject(
    session: Session, subproject_id: UUID, module_set_id: UUID
) -> ModuleSet | None:
    """One ``ModuleSet`` row by id, but only if it belongs to ``subproject_id``. Read-only."""
    module_set = session.get(ModuleSet, module_set_id)
    if module_set is None or module_set.subproject_id != subproject_id:
        return None
    return module_set


def list_module_sets_for_subproject(session: Session, subproject_id: UUID) -> list[ModuleSet]:
    """Every module set for one Modeling Study, ordered by ``stable_identifier``. Read-only."""
    stmt = (
        select(ModuleSet)
        .where(ModuleSet.subproject_id == subproject_id)
        .order_by(ModuleSet.stable_identifier.asc())
    )
    return list(session.scalars(stmt))


def get_module_set_version_by_number(
    session: Session, module_set_id: UUID, version: int
) -> ModuleSetVersion | None:
    """One ``ModuleSetVersion`` by its own set-scoped version number, or ``None``. Read-only --
    reopening a saved version never creates or mutates anything."""
    stmt = select(ModuleSetVersion).where(
        ModuleSetVersion.module_set_id == module_set_id, ModuleSetVersion.version == version
    )
    return session.execute(stmt).scalar_one_or_none()


__all__ = [
    "ModuleSetDraftAlreadyResolved",
    "ModuleSetDraftStaleEdit",
    "ModuleSetDraftValidationFailed",
    "ModuleSetDraftValidationFinding",
    "create_draft_from_run",
    "create_draft_from_version",
    "discard_draft",
    "edit_draft_member",
    "effective_reaction_component_ids",
    "get_draft",
    "get_draft_for_subproject",
    "get_module_set",
    "get_module_set_for_subproject",
    "get_module_set_version_by_number",
    "list_drafts_for_subproject",
    "list_module_sets_for_subproject",
    "save_draft",
    "validate_draft",
]
