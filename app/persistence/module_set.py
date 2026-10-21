"""Module-Set persistence: create a draft from an existing, unedited automated hierarchical
run; inspect it; discard it; explicitly save it (as a new set, or a new version of an existing
one); read a saved set/version back.

See ``docs/20_module_set_domain_contract.md`` for the full domain model and
``docs/21_module_set_first_increment.md`` for exactly what this module implements. Ownership
(project/subproject) checks live at the API route layer (mirroring
``app.api.v1.routes.projects``'s own established ``_require_*`` pattern) -- this module trusts
its own callers' contract for *which* subproject a given id belongs to, the identical discipline
``materialize_accepted_modules`` already uses ("the caller's own contract guarantee"), but still
independently re-validates every cross-entity ownership fact this module itself is responsible
for asserting (e.g. that a run or an existing set actually belongs to the subproject a draft
claims to be scoped to) -- never trusting a caller-supplied id pairing blindly.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import ModuleSetDraftStatus, ModuleSetOriginMethod, RunStage, RunStatus
from app.models.module_set import (
    ModuleSet,
    ModuleSetDraft,
    ModuleSetDraftMember,
    ModuleSetMember,
    ModuleSetVersion,
)
from app.models.run_record import RunRecord
from app.persistence.model_module import list_model_modules_for_run


class ModuleSetDraftAlreadyResolved(ValueError):
    """Raised when ``save_draft``/``discard_draft`` is called on a draft that is no longer
    ``OPEN`` -- the duplicate-save/duplicate-discard protection. Carries the draft's own already-
    resolved state so a caller (the API route) can report it without a second lookup."""

    def __init__(self, draft: ModuleSetDraft) -> None:
        self.draft = draft
        super().__init__(f"ModuleSetDraft {draft.id} is already {draft.status.value}, not OPEN")


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
        session.add(ModuleSetDraftMember(draft_id=draft.id, model_module_id=module.id))
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
    """
    draft = session.get(ModuleSetDraft, draft_id)
    if draft is None:
        raise ValueError(f"no ModuleSetDraft with id {draft_id}")
    if draft.status is not ModuleSetDraftStatus.OPEN:
        raise ModuleSetDraftAlreadyResolved(draft)

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
        session.add(
            ModuleSetMember(
                module_set_version_id=version.id, model_module_id=draft_member.model_module_id
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
    "create_draft_from_run",
    "discard_draft",
    "get_draft",
    "get_draft_for_subproject",
    "get_module_set",
    "get_module_set_for_subproject",
    "get_module_set_version_by_number",
    "list_drafts_for_subproject",
    "list_module_sets_for_subproject",
    "save_draft",
]
