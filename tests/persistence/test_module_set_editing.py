"""Tests for the Module-Set Manual Editing increment's persistence layer:
``create_draft_from_version``, ``edit_draft_member``, ``validate_draft``, and ``save_draft``'s
own new validation/edit-carrying behavior. See
``docs/23_module_set_manual_editing_increment.md``.
"""

from __future__ import annotations

import json

import pytest

from app.models.enums import ModuleSetDraftStatus, ModuleSetOriginMethod
from app.persistence.model_module import list_model_modules_for_run
from app.persistence.module_set import (
    ModuleSetDraftAlreadyResolved,
    ModuleSetDraftStaleEdit,
    ModuleSetDraftValidationFailed,
    create_draft_from_run,
    create_draft_from_version,
    discard_draft,
    edit_draft_member,
    save_draft,
    validate_draft,
)
from tests.persistence.conftest import make_subproject_id, make_succeeded_hierarchical_run


def _three_sibling_leaves_run(db_session):
    """Three depth-1 sibling modules (same parent -- the implicit root), each owning two real,
    distinct reaction ids -- the shape every editing test in this file needs."""
    subproject_id = make_subproject_id(db_session)
    run = make_succeeded_hierarchical_run(
        db_session,
        subproject_id=subproject_id,
        leaf_count=3,
        reaction_ids_per_leaf=[["rA1", "rA2"], ["rB1", "rB2"], ["rC1", "rC2"]],
    )
    modules = list_model_modules_for_run(db_session, run.id)
    return subproject_id, run, modules


class TestCreateDraftFromVersion:
    def test_copies_members_and_their_current_membership(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft1 = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        version = save_draft(
            session=db_session, draft_id=draft1.id, mode="new_set", set_name="Original"
        )

        draft2 = create_draft_from_version(
            session=db_session, subproject_id=subproject_id, module_set_version_id=version.id
        )
        assert draft2.status is ModuleSetDraftStatus.OPEN
        assert draft2.module_set_id == version.module_set_id
        assert draft2.base_version_id == version.id
        assert len(draft2.members) == 3
        member_reaction_sets = {
            tuple(sorted(json.loads(m.reaction_component_ids))) for m in draft2.members
        }
        assert member_reaction_sets == {("rA1", "rA2"), ("rB1", "rB2"), ("rC1", "rC2")}

    def test_rejects_a_version_belonging_to_a_different_study(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft1 = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        version = save_draft(
            session=db_session, draft_id=draft1.id, mode="new_set", set_name="Original"
        )
        other_subproject_id = make_subproject_id(db_session)
        with pytest.raises(ValueError, match="no module-set version"):
            create_draft_from_version(
                session=db_session,
                subproject_id=other_subproject_id,
                module_set_version_id=version.id,
            )

    def test_second_edit_round_carries_forward_the_first_rounds_own_result(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft1 = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        member_a = next(
            m
            for m in draft1.members
            if sorted(json.loads(m.reaction_component_ids)) == ["rA1", "rA2"]
        )
        edit_draft_member(
            session=db_session,
            draft_id=draft1.id,
            member_id=member_a.id,
            expected_edit_version=0,
            display_name="Renamed A",
        )
        version1 = save_draft(
            session=db_session, draft_id=draft1.id, mode="new_set", set_name="Original"
        )

        draft2 = create_draft_from_version(
            session=db_session, subproject_id=subproject_id, module_set_version_id=version1.id
        )
        carried = next(m for m in draft2.members if m.model_module_id == member_a.model_module_id)
        assert carried.display_name == "Renamed A"


class TestEditDraftMember:
    def test_rename_sets_display_name_and_advances_edit_version(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        member = draft.members[0]
        edit_draft_member(
            session=db_session,
            draft_id=draft.id,
            member_id=member.id,
            expected_edit_version=0,
            display_name="Fatty acid synthesis",
        )
        db_session.flush()
        assert member.display_name == "Fatty acid synthesis"
        assert draft.edit_version == 1

    def test_rename_rejects_an_empty_name(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        with pytest.raises(ValueError, match="must not be empty"):
            edit_draft_member(
                session=db_session,
                draft_id=draft.id,
                member_id=draft.members[0].id,
                expected_edit_version=0,
                display_name="   ",
            )

    def test_moving_a_reaction_to_a_sibling_removes_it_from_the_original_owner(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        member_a = next(
            m for m in draft.members if json.loads(m.reaction_component_ids) == ["rA1", "rA2"]
        )
        member_b = next(
            m for m in draft.members if json.loads(m.reaction_component_ids) == ["rB1", "rB2"]
        )

        edit_draft_member(
            session=db_session,
            draft_id=draft.id,
            member_id=member_b.id,
            expected_edit_version=0,
            reaction_component_ids=["rB1", "rB2", "rA1"],
        )
        db_session.flush()
        assert sorted(json.loads(member_b.reaction_component_ids)) == ["rA1", "rB1", "rB2"]
        assert sorted(json.loads(member_a.reaction_component_ids)) == ["rA2"]
        assert json.loads(member_a.original_reaction_component_ids) == ["rA1", "rA2"]

    def test_rejects_a_reaction_id_unknown_to_the_sibling_group(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        member = draft.members[0]
        with pytest.raises(ValueError, match="not known to this module's own hierarchical"):
            edit_draft_member(
                session=db_session,
                draft_id=draft.id,
                member_id=member.id,
                expected_edit_version=0,
                reaction_component_ids=["totally-invented-reaction"],
            )

    def test_rejects_an_empty_reaction_list(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        with pytest.raises(ValueError, match="must not be empty"):
            edit_draft_member(
                session=db_session,
                draft_id=draft.id,
                member_id=draft.members[0].id,
                expected_edit_version=0,
                reaction_component_ids=[],
            )

    def test_requires_at_least_one_field(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        with pytest.raises(ValueError, match="requires display_name"):
            edit_draft_member(
                session=db_session,
                draft_id=draft.id,
                member_id=draft.members[0].id,
                expected_edit_version=0,
            )

    def test_stale_edit_version_is_rejected(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        member = draft.members[0]
        edit_draft_member(
            session=db_session,
            draft_id=draft.id,
            member_id=member.id,
            expected_edit_version=0,
            display_name="First edit",
        )
        with pytest.raises(ModuleSetDraftStaleEdit) as exc_info:
            edit_draft_member(
                session=db_session,
                draft_id=draft.id,
                member_id=member.id,
                expected_edit_version=0,
                display_name="Conflicting edit",
            )
        assert exc_info.value.draft.edit_version == 1

    def test_editing_a_non_open_draft_is_rejected(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        discard_draft(db_session, draft.id)
        with pytest.raises(ModuleSetDraftAlreadyResolved):
            edit_draft_member(
                session=db_session,
                draft_id=draft.id,
                member_id=draft.members[0].id,
                expected_edit_version=0,
                display_name="Too late",
            )

    def test_any_edit_marks_origin_method_mixed_edited(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        assert draft.origin_method is ModuleSetOriginMethod.AUTOMATED
        edit_draft_member(
            session=db_session,
            draft_id=draft.id,
            member_id=draft.members[0].id,
            expected_edit_version=0,
            display_name="Edited",
        )
        assert draft.origin_method is ModuleSetOriginMethod.MIXED_EDITED


class TestValidateDraft:
    def test_a_fresh_unedited_draft_has_no_findings(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        assert validate_draft(draft) == []

    def test_removing_a_reaction_without_reassigning_it_is_unassigned(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        member_a = draft.members[0]
        remaining = json.loads(member_a.reaction_component_ids)[:1]
        edit_draft_member(
            session=db_session,
            draft_id=draft.id,
            member_id=member_a.id,
            expected_edit_version=0,
            reaction_component_ids=remaining,
        )
        findings = validate_draft(draft)
        assert len(findings) == 1
        assert findings[0].code == "UNASSIGNED_REACTION"

    def test_a_module_edited_down_to_zero_reactions_is_flagged(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        member_a, member_b = draft.members[0], draft.members[1]
        a_ids = json.loads(member_a.reaction_component_ids)
        b_ids = json.loads(member_b.reaction_component_ids)
        # Move every one of A's reactions onto B, leaving A empty.
        edit_draft_member(
            session=db_session,
            draft_id=draft.id,
            member_id=member_b.id,
            expected_edit_version=0,
            reaction_component_ids=[*b_ids, *a_ids],
        )
        findings = validate_draft(draft)
        assert any(f.code == "EMPTY_MODULE" and f.member_id == member_a.id for f in findings)


class TestSaveDraftWithEdits:
    def test_save_is_blocked_while_a_reaction_is_unassigned(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        member_a = draft.members[0]
        edit_draft_member(
            session=db_session,
            draft_id=draft.id,
            member_id=member_a.id,
            expected_edit_version=0,
            reaction_component_ids=["rA1"],
        )
        with pytest.raises(ModuleSetDraftValidationFailed) as exc_info:
            save_draft(session=db_session, draft_id=draft.id, mode="new_set", set_name="Blocked")
        assert exc_info.value.findings[0].code == "UNASSIGNED_REACTION"
        # Nothing was created or mutated by the failed save.
        assert draft.status is ModuleSetDraftStatus.OPEN

    def test_save_after_resolving_findings_persists_the_edits(self, db_session):
        subproject_id, run, _modules = _three_sibling_leaves_run(db_session)
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        member_a = next(
            m for m in draft.members if json.loads(m.reaction_component_ids) == ["rA1", "rA2"]
        )
        member_b = next(
            m for m in draft.members if json.loads(m.reaction_component_ids) == ["rB1", "rB2"]
        )
        edit_draft_member(
            session=db_session,
            draft_id=draft.id,
            member_id=member_a.id,
            expected_edit_version=0,
            display_name="Renamed A",
        )
        edit_draft_member(
            session=db_session,
            draft_id=draft.id,
            member_id=member_b.id,
            expected_edit_version=1,
            reaction_component_ids=["rB1", "rB2", "rA1"],
        )
        # member_a now has only rA2 left -- re-assign it to itself (no-op allowed) so nothing
        # is unassigned; the point of this test is "edits persist," not re-deriving a minimal
        # resolution.
        edit_draft_member(
            session=db_session,
            draft_id=draft.id,
            member_id=member_a.id,
            expected_edit_version=2,
            reaction_component_ids=["rA2"],
        )
        assert validate_draft(draft) == []

        version = save_draft(
            session=db_session, draft_id=draft.id, mode="new_set", set_name="Edited partition"
        )
        assert version.origin_method is ModuleSetOriginMethod.MIXED_EDITED

        saved_a = next(m for m in version.members if m.model_module_id == member_a.model_module_id)
        saved_b = next(m for m in version.members if m.model_module_id == member_b.model_module_id)
        assert saved_a.display_name == "Renamed A"
        assert json.loads(saved_a.reaction_component_ids) == ["rA2"]
        assert sorted(json.loads(saved_b.reaction_component_ids)) == ["rA1", "rB1", "rB2"]

        unedited_member = next(
            m
            for m in version.members
            if m.model_module_id not in {member_a.model_module_id, member_b.model_module_id}
        )
        assert unedited_member.display_name is None
        assert unedited_member.reaction_component_ids is None

    def test_save_never_mutates_the_resolved_model_modules(self, db_session):
        subproject_id, run, modules = _three_sibling_leaves_run(db_session)
        original_payloads = {m.id: m.attach_payload for m in modules}
        draft = create_draft_from_run(
            session=db_session, subproject_id=subproject_id, run_record_id=run.id
        )
        member_a = draft.members[0]
        edit_draft_member(
            session=db_session,
            draft_id=draft.id,
            member_id=member_a.id,
            expected_edit_version=0,
            display_name="Renamed",
        )
        save_draft(session=db_session, draft_id=draft.id, mode="new_set", set_name="Set")
        db_session.flush()
        for module in modules:
            db_session.refresh(module)
            assert module.attach_payload == original_payloads[module.id]
