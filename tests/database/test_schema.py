"""Schema-level integrity tests: FK restrict/cascade behavior, uniqueness,
lineage, and both project types/all task types.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.enums import (
    ModelSourceType,
    ModelStatus,
    ProjectType,
    SubprojectTaskType,
    WorkflowLifecycleStatus,
)
from app.models.model import Model
from app.models.model_build_request import ModelBuildRequest, ModelBuildRequestSpecies
from app.models.modeling_decision import ModelingDecision, ModelingDecisionOption
from app.models.project import Project
from app.models.subproject import Subproject

pytestmark = pytest.mark.database


def _make_project(db_session, **kwargs) -> Project:
    kwargs.setdefault("stable_identifier", f"PROJ_{uuid.uuid4().hex[:8]}")
    kwargs.setdefault("title", "test-only project")
    kwargs.setdefault("project_type", ProjectType.MICROBIAL_METABOLISM)
    project = Project(**kwargs)
    db_session.add(project)
    db_session.flush()
    return project


def _make_subproject(db_session, *, project_id, **kwargs) -> Subproject:
    kwargs.setdefault("title", f"test-only subproject {uuid.uuid4().hex[:8]}")
    kwargs.setdefault("task_type", SubprojectTaskType.BUILD_MODEL)
    subproject = Subproject(project_id=project_id, **kwargs)
    db_session.add(subproject)
    db_session.flush()
    return subproject


def _make_model(db_session, *, subproject_id, **kwargs) -> Model:
    kwargs.setdefault("stable_identifier", f"MODEL_{uuid.uuid4().hex[:8]}")
    kwargs.setdefault("name", "test-only model")
    kwargs.setdefault("source_type", ModelSourceType.GENERATED)
    model = Model(subproject_id=subproject_id, **kwargs)
    db_session.add(model)
    db_session.flush()
    return model


def test_create_project(db_session):
    project = _make_project(db_session, title="FFA biosynthesis workbench project")
    fetched = db_session.get(Project, project.id)
    assert fetched is not None
    assert fetched.status == WorkflowLifecycleStatus.ACTIVE
    assert fetched.created_at is not None


def test_project_stable_identifier_must_be_unique(db_session):
    _make_project(db_session, stable_identifier="PROJ_DUP")
    with pytest.raises(IntegrityError):
        _make_project(db_session, stable_identifier="PROJ_DUP")


@pytest.mark.parametrize(
    "project_type", [ProjectType.MICROBIAL_METABOLISM, ProjectType.REGULATORY_NETWORK]
)
def test_both_project_types_are_persistable(db_session, project_type):
    project = _make_project(db_session, project_type=project_type)
    fetched = db_session.get(Project, project.id)
    assert fetched.project_type == project_type


def test_a_project_can_contain_multiple_subprojects(db_session):
    project = _make_project(db_session)
    sub_a = _make_subproject(db_session, project_id=project.id, title="build")
    sub_b = _make_subproject(db_session, project_id=project.id, title="calibrate")
    fetched = db_session.get(Project, project.id)
    assert {s.id for s in fetched.subprojects} == {sub_a.id, sub_b.id}


def test_subproject_project_id_title_must_be_unique(db_session):
    project = _make_project(db_session)
    _make_subproject(db_session, project_id=project.id, title="dup title")
    with pytest.raises(IntegrityError):
        _make_subproject(db_session, project_id=project.id, title="dup title")


@pytest.mark.parametrize(
    "task_type",
    [
        SubprojectTaskType.BUILD_MODEL,
        SubprojectTaskType.IMPORT_MODEL,
        SubprojectTaskType.TEST_MODEL,
        SubprojectTaskType.CALIBRATE_MODEL,
        SubprojectTaskType.EXTEND_MODEL,
    ],
)
def test_every_task_type_is_persistable(db_session, task_type):
    project = _make_project(db_session)
    subproject = _make_subproject(db_session, project_id=project.id, task_type=task_type)
    fetched = db_session.get(Subproject, subproject.id)
    assert fetched.task_type == task_type


def test_deleting_a_project_with_a_subproject_is_restricted(db_session):
    project = _make_project(db_session)
    _make_subproject(db_session, project_id=project.id)
    with pytest.raises(IntegrityError):
        db_session.delete(db_session.get(Project, project.id))
        db_session.flush()


def test_model_build_request_is_one_per_subproject(db_session):
    project = _make_project(db_session)
    subproject = _make_subproject(db_session, project_id=project.id)
    db_session.add(ModelBuildRequest(subproject_id=subproject.id))
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.add(ModelBuildRequest(subproject_id=subproject.id))
        db_session.flush()


def test_deleting_a_model_build_request_cascades_to_its_species(db_session):
    project = _make_project(db_session)
    subproject = _make_subproject(db_session, project_id=project.id)
    mbr = ModelBuildRequest(subproject_id=subproject.id)
    db_session.add(mbr)
    db_session.flush()
    db_session.add(
        ModelBuildRequestSpecies(
            model_build_request_id=mbr.id,
            role="INPUT",
            raw_identifier="glucose",
        )
    )
    db_session.flush()
    mbr_id = mbr.id

    db_session.delete(db_session.get(ModelBuildRequest, mbr_id))
    db_session.flush()
    db_session.expunge_all()

    assert (
        db_session.query(ModelBuildRequestSpecies)
        .filter_by(model_build_request_id=mbr_id)
        .one_or_none()
        is None
    )


def test_model_lineage_via_parent_model_id(db_session):
    project = _make_project(db_session)
    subproject = _make_subproject(db_session, project_id=project.id)
    parent = _make_model(db_session, subproject_id=subproject.id, status=ModelStatus.SUPERSEDED)
    child = _make_model(db_session, subproject_id=subproject.id, parent_model_id=parent.id)
    fetched = db_session.get(Model, child.id)
    assert fetched.parent_model_id == parent.id


def test_deleting_a_parent_model_with_a_child_version_is_restricted(db_session):
    project = _make_project(db_session)
    subproject = _make_subproject(db_session, project_id=project.id)
    parent = _make_model(db_session, subproject_id=subproject.id)
    _make_model(db_session, subproject_id=subproject.id, parent_model_id=parent.id)
    with pytest.raises(IntegrityError):
        db_session.delete(db_session.get(Model, parent.id))
        db_session.flush()


def test_model_stable_identifier_must_be_unique(db_session):
    project = _make_project(db_session)
    subproject = _make_subproject(db_session, project_id=project.id)
    _make_model(db_session, subproject_id=subproject.id, stable_identifier="MODEL_DUP")
    with pytest.raises(IntegrityError):
        _make_model(db_session, subproject_id=subproject.id, stable_identifier="MODEL_DUP")


def test_deleting_a_modeling_decision_cascades_to_its_options(db_session):
    decision = ModelingDecision(question="test-only question")
    db_session.add(decision)
    db_session.flush()
    db_session.add(ModelingDecisionOption(decision_id=decision.id, label="option A"))
    db_session.flush()
    decision_id = decision.id

    db_session.delete(db_session.get(ModelingDecision, decision_id))
    db_session.flush()
    db_session.expunge_all()

    assert (
        db_session.query(ModelingDecisionOption).filter_by(decision_id=decision_id).one_or_none()
        is None
    )


def test_modeling_decision_option_confidence_score_range_check(db_session):
    decision = ModelingDecision(question="test-only question")
    db_session.add(decision)
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.add(
            ModelingDecisionOption(decision_id=decision.id, label="bad", confidence_score=150)
        )
        db_session.flush()
