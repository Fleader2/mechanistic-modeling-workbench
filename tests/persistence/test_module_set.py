"""Tests for ``app.persistence.module_set``.

Covers, per this increment's own explicit testing requirements
(``docs/21_module_set_first_increment.md``): historical-record preservation (nothing this module
touches is ever mutated), ownership isolation, save idempotency/duplicate-save protection, and
immutability of a saved version.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import RunStage
from app.persistence.model_module import get_model_module, list_model_modules_for_run
from app.persistence.module_boundary_port import (
    list_boundary_ports_for_module,
    persist_candidate_boundary_ports,
)
from app.persistence.module_set import (
    ModuleSetDraftAlreadyResolved,
    create_draft_from_run,
    discard_draft,
    get_draft_for_subproject,
    get_module_set_for_subproject,
    get_module_set_version_by_number,
    list_drafts_for_subproject,
    list_module_sets_for_subproject,
    save_draft,
)
from app.persistence.run_record import create_run_record, get_run_record, start_run
from tests.persistence.conftest import (
    make_model_id,
    make_subproject_id,
    make_succeeded_hierarchical_run,
)

pytestmark = pytest.mark.database


# --- create_draft_from_run ---------------------------------------------------


def test_create_draft_from_run_copies_every_materialized_module(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id, leaf_count=3)

    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )

    assert draft.status.value == "OPEN"
    assert draft.module_set_id is None
    assert draft.model_id == run.model_id
    assert draft.base_run_record_id == run.id
    assert len(draft.members) == 3
    expected_module_ids = {m.id for m in list_model_modules_for_run(db_session, run.id)}
    assert {m.model_module_id for m in draft.members} == expected_module_ids


def test_create_draft_from_run_rejects_a_run_from_a_different_subproject(db_session):
    owning_subproject_id = make_subproject_id(db_session)
    other_subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=owning_subproject_id)

    with pytest.raises(ValueError, match="no hierarchical run"):
        create_draft_from_run(
            session=db_session, subproject_id=other_subproject_id, run_record_id=run.id
        )


def test_create_draft_from_run_rejects_a_run_with_no_model(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(
        db_session, subproject_id=subproject_id, include_model=False
    )

    with pytest.raises(ValueError, match="no associated Model"):
        create_draft_from_run(session=db_session, subproject_id=subproject_id, run_record_id=run.id)


def test_create_draft_from_run_rejects_a_run_that_is_not_succeeded(db_session):
    subproject_id = make_subproject_id(db_session)
    model_id = make_model_id(db_session, subproject_id=subproject_id)
    run = create_run_record(
        subproject_id=subproject_id,
        stage=RunStage.HARNESS,
        session=db_session,
        model_id=model_id,
    )
    start_run(run_record_id=run.id, session=db_session)  # left RUNNING, never completed

    with pytest.raises(ValueError, match="not SUCCEEDED"):
        create_draft_from_run(session=db_session, subproject_id=subproject_id, run_record_id=run.id)


def test_create_draft_from_run_rejects_a_run_with_no_materialized_modules(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id, leaf_count=0)

    with pytest.raises(ValueError, match="no materialized modules"):
        create_draft_from_run(session=db_session, subproject_id=subproject_id, run_record_id=run.id)


def test_create_draft_from_run_never_mutates_the_source_run_or_its_modules(db_session):
    """Historical-record preservation: drafting never touches anything that already existed."""
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id, leaf_count=2)
    modules_before = {
        m.id: (m.run_record_id, m.execution_status, m.attach_payload)
        for m in list_model_modules_for_run(db_session, run.id)
    }
    run_before = (run.status, run.model_id, run.completed_at)

    create_draft_from_run(session=db_session, subproject_id=subproject_id, run_record_id=run.id)
    db_session.flush()
    db_session.expire_all()

    run_after = get_run_record(db_session, run.id)
    assert (run_after.status, run_after.model_id, run_after.completed_at) == run_before
    for module_id, before in modules_before.items():
        after = get_model_module(db_session, module_id)
        assert (after.run_record_id, after.execution_status, after.attach_payload) == before


# --- discard ------------------------------------------------------------------


def test_discard_draft_soft_marks_and_never_deletes(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )

    discarded = discard_draft(db_session, draft.id)

    assert discarded.status.value == "DISCARDED"
    # Still findable by id -- soft-marked, never hard-deleted.
    assert get_draft_for_subproject(db_session, subproject_id, draft.id) is not None


def test_discard_draft_twice_raises_already_resolved(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )
    discard_draft(db_session, draft.id)

    with pytest.raises(ModuleSetDraftAlreadyResolved):
        discard_draft(db_session, draft.id)


def test_list_drafts_hides_discarded_by_default(db_session):
    subproject_id = make_subproject_id(db_session)
    run_a = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    run_b = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    open_draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run_a.id
    )
    discarded_draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run_b.id
    )
    discard_draft(db_session, discarded_draft.id)

    visible = list_drafts_for_subproject(db_session, subproject_id)
    assert {d.id for d in visible} == {open_draft.id}

    everything = list_drafts_for_subproject(db_session, subproject_id, include_discarded=True)
    assert {d.id for d in everything} == {open_draft.id, discarded_draft.id}


# --- save: new_set -------------------------------------------------------------


def test_save_as_new_set_creates_set_version_one_referencing_original_modules(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id, leaf_count=3)
    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )
    original_module_ids = {m.model_module_id for m in draft.members}

    version = save_draft(
        session=db_session,
        draft_id=draft.id,
        mode="new_set",
        set_name="Expert partition",
        version_note="Initial review.",
        saved_by="Test Author",
    )

    assert version.version == 1
    assert version.module_set.name == "Expert partition"
    assert version.module_set.stable_identifier == "MS-001"
    assert version.model_id == run.model_id
    assert version.generation_run_record_id == run.id
    assert {m.model_module_id for m in version.members} == original_module_ids

    db_session.refresh(draft)
    assert draft.status.value == "SAVED"
    assert draft.resulting_version_id == version.id
    assert draft.module_set_id == version.module_set_id


def test_save_as_new_set_rejects_empty_set_name(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )

    with pytest.raises(ValueError, match="non-empty set_name"):
        save_draft(session=db_session, draft_id=draft.id, mode="new_set", set_name="   ")


def test_stable_identifiers_increment_sequentially_per_subproject(db_session):
    subproject_id = make_subproject_id(db_session)
    run_a = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    run_b = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft_a = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run_a.id
    )
    draft_b = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run_b.id
    )

    version_a = save_draft(session=db_session, draft_id=draft_a.id, mode="new_set", set_name="A")
    version_b = save_draft(session=db_session, draft_id=draft_b.id, mode="new_set", set_name="B")

    assert version_a.module_set.stable_identifier == "MS-001"
    assert version_b.module_set.stable_identifier == "MS-002"


# --- save: duplicate-save protection (idempotency) -----------------------------


def test_saving_an_already_saved_draft_raises_and_creates_nothing_new(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )
    first_version = save_draft(
        session=db_session, draft_id=draft.id, mode="new_set", set_name="Once"
    )

    with pytest.raises(ModuleSetDraftAlreadyResolved) as exc_info:
        save_draft(session=db_session, draft_id=draft.id, mode="new_set", set_name="Twice")

    assert exc_info.value.draft.resulting_version_id == first_version.id
    # No second set/version was created for this subproject.
    assert len(list_module_sets_for_subproject(db_session, subproject_id)) == 1


def test_saving_a_discarded_draft_raises(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )
    discard_draft(db_session, draft.id)

    with pytest.raises(ModuleSetDraftAlreadyResolved):
        save_draft(session=db_session, draft_id=draft.id, mode="new_set", set_name="Too late")


# --- save: new_version ----------------------------------------------------------


def test_save_new_version_allocates_the_next_integer_regardless_of_origin(db_session):
    subproject_id = make_subproject_id(db_session)
    model_id = make_model_id(db_session, subproject_id=subproject_id)
    run_1 = make_succeeded_hierarchical_run(
        db_session, subproject_id=subproject_id, model_id=model_id
    )
    draft_1 = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run_1.id
    )
    version_1 = save_draft(session=db_session, draft_id=draft_1.id, mode="new_set", set_name="Set")

    run_2 = make_succeeded_hierarchical_run(
        db_session, subproject_id=subproject_id, model_id=model_id
    )
    draft_2 = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run_2.id
    )
    version_2 = save_draft(
        session=db_session,
        draft_id=draft_2.id,
        mode="new_version",
        existing_set_id=version_1.module_set_id,
    )

    run_3 = make_succeeded_hierarchical_run(
        db_session, subproject_id=subproject_id, model_id=model_id
    )
    draft_3 = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run_3.id
    )
    version_3 = save_draft(
        session=db_session,
        draft_id=draft_3.id,
        mode="new_version",
        existing_set_id=version_1.module_set_id,
    )

    assert [version_1.version, version_2.version, version_3.version] == [1, 2, 3]
    assert version_2.base_version_id == version_1.id
    assert version_3.base_version_id == version_2.id


def test_save_new_version_rejects_an_existing_set_from_a_different_subproject(db_session):
    owning_subproject_id = make_subproject_id(db_session)
    other_subproject_id = make_subproject_id(db_session)
    run_1 = make_succeeded_hierarchical_run(db_session, subproject_id=owning_subproject_id)
    draft_1 = create_draft_from_run(
        session=db_session, subproject_id=owning_subproject_id, run_record_id=run_1.id
    )
    version_1 = save_draft(session=db_session, draft_id=draft_1.id, mode="new_set", set_name="Set")

    run_2 = make_succeeded_hierarchical_run(db_session, subproject_id=other_subproject_id)
    draft_2 = create_draft_from_run(
        session=db_session, subproject_id=other_subproject_id, run_record_id=run_2.id
    )

    with pytest.raises(ValueError, match="no ModuleSet"):
        save_draft(
            session=db_session,
            draft_id=draft_2.id,
            mode="new_version",
            existing_set_id=version_1.module_set_id,
        )


def test_save_new_version_rejects_a_different_pinned_model_without_revalidation(db_session):
    subproject_id = make_subproject_id(db_session)
    run_1 = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft_1 = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run_1.id
    )
    version_1 = save_draft(session=db_session, draft_id=draft_1.id, mode="new_set", set_name="Set")

    # A second run against a *different* model, same study.
    run_2 = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft_2 = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run_2.id
    )
    assert draft_2.model_id != version_1.model_id

    with pytest.raises(ValueError, match="explicit revalidation"):
        save_draft(
            session=db_session,
            draft_id=draft_2.id,
            mode="new_version",
            existing_set_id=version_1.module_set_id,
        )


# --- immutability / historical-record preservation at save time ----------------


def test_save_never_mutates_pre_existing_module_module_boundary_port_or_run_record(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id, leaf_count=2)
    modules = list_model_modules_for_run(db_session, run.id)
    first_module_id = modules[0].id

    persist_candidate_boundary_ports(
        model_module_id=first_module_id,
        candidates=[{"species_id": "S1", "direction": "OUTPUT"}],
        session=db_session,
    )
    ports_before = [
        (p.id, p.treatment_type, p.resolution_status)
        for p in list_boundary_ports_for_module(db_session, first_module_id)
    ]
    run_before = (run.status, run.completed_at)

    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )
    save_draft(session=db_session, draft_id=draft.id, mode="new_set", set_name="Set")
    db_session.expire_all()

    ports_after = [
        (p.id, p.treatment_type, p.resolution_status)
        for p in list_boundary_ports_for_module(db_session, first_module_id)
    ]
    assert ports_after == ports_before
    run_after = get_run_record(db_session, run.id)
    assert (run_after.status, run_after.completed_at) == run_before


def test_reopening_a_saved_version_is_read_only_and_stable_across_repeated_reads(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )
    saved = save_draft(
        session=db_session, draft_id=draft.id, mode="new_set", set_name="Set", version_note="n"
    )

    first_read = get_module_set_version_by_number(db_session, saved.module_set_id, 1)
    db_session.expire_all()
    second_read = get_module_set_version_by_number(db_session, saved.module_set_id, 1)

    assert first_read.id == second_read.id
    assert first_read.saved_at == second_read.saved_at
    assert first_read.version_note == second_read.version_note == "n"
    assert {m.model_module_id for m in first_read.members} == {
        m.model_module_id for m in second_read.members
    }


def test_get_module_set_version_by_number_returns_none_for_unknown_version(db_session):
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=subproject_id)
    draft = create_draft_from_run(
        session=db_session, subproject_id=subproject_id, run_record_id=run.id
    )
    saved = save_draft(session=db_session, draft_id=draft.id, mode="new_set", set_name="Set")

    assert get_module_set_version_by_number(db_session, saved.module_set_id, 99) is None


# --- ownership isolation for reads ----------------------------------------------


def test_get_module_set_for_subproject_enforces_ownership(db_session):
    owning_subproject_id = make_subproject_id(db_session)
    other_subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=owning_subproject_id)
    draft = create_draft_from_run(
        session=db_session, subproject_id=owning_subproject_id, run_record_id=run.id
    )
    saved = save_draft(session=db_session, draft_id=draft.id, mode="new_set", set_name="Set")

    assert (
        get_module_set_for_subproject(db_session, owning_subproject_id, saved.module_set_id)
        is not None
    )
    assert (
        get_module_set_for_subproject(db_session, other_subproject_id, saved.module_set_id) is None
    )


def test_get_draft_for_subproject_enforces_ownership(db_session):
    owning_subproject_id = make_subproject_id(db_session)
    other_subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(db_session, subproject_id=owning_subproject_id)
    draft = create_draft_from_run(
        session=db_session, subproject_id=owning_subproject_id, run_record_id=run.id
    )

    assert get_draft_for_subproject(db_session, owning_subproject_id, draft.id) is not None
    assert get_draft_for_subproject(db_session, other_subproject_id, draft.id) is None


def test_get_draft_for_subproject_returns_none_for_unknown_id(db_session):
    subproject_id = make_subproject_id(db_session)
    assert get_draft_for_subproject(db_session, subproject_id, uuid.uuid4()) is None
