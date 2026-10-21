"""Shared row-creation helpers for ``tests/persistence``."""

from __future__ import annotations

import uuid

from app.models.enums import ModelSourceType, ProjectType, RunStage, RunStatus, SubprojectTaskType
from app.models.run_record import RunRecord
from app.persistence.hierarchy_node import create_hierarchy_nodes
from app.persistence.model import persist_model
from app.persistence.model_module import materialize_accepted_modules
from app.persistence.project import persist_project
from app.persistence.run_record import complete_run, create_run_record, start_run
from app.persistence.subproject import persist_subproject


def make_project_id(db_session, **overrides) -> uuid.UUID:
    kwargs = {
        "stable_identifier": f"PROJ_{uuid.uuid4().hex[:8]}",
        "title": "test-only project",
        "project_type": ProjectType.MICROBIAL_METABOLISM,
        "session": db_session,
    }
    kwargs.update(overrides)
    return persist_project(**kwargs).entity_id


def make_subproject_id(db_session, *, project_id=None, **overrides) -> uuid.UUID:
    if project_id is None:
        project_id = make_project_id(db_session)
    kwargs = {
        "project_id": project_id,
        "title": f"test-only subproject {uuid.uuid4().hex[:8]}",
        "task_type": SubprojectTaskType.BUILD_MODEL,
        "session": db_session,
    }
    kwargs.update(overrides)
    return persist_subproject(**kwargs).entity_id


def make_model_id(db_session, *, subproject_id=None, **overrides) -> uuid.UUID:
    if subproject_id is None:
        subproject_id = make_subproject_id(db_session)
    kwargs = {
        "subproject_id": subproject_id,
        "stable_identifier": f"MODEL_{uuid.uuid4().hex[:8]}",
        "name": f"test-only model {uuid.uuid4().hex[:8]}",
        "source_type": ModelSourceType.GENERATED,
        "session": db_session,
    }
    kwargs.update(overrides)
    return persist_model(**kwargs).entity_id


def _attach_payload(modularization_id: str, module_id: str) -> dict:
    return {
        "modularization_id": modularization_id,
        "module_ids": [module_id],
        "memberships": [
            {"module_id": module_id, "component_type": "REACTION", "component_id": "r1"}
        ],
    }


def make_succeeded_hierarchical_run(
    db_session,
    *,
    subproject_id=None,
    model_id=None,
    leaf_count: int = 3,
    include_model: bool = True,
) -> RunRecord:
    """A terminal, ``SUCCEEDED`` ``stage=HARNESS`` run with ``leaf_count`` genuinely
    materialized depth-1 ``ModelModule`` rows -- the Module-Set Domain Model increment's own
    "existing automated run" fixture, mirroring ``tests/persistence/test_model_module.py``'s
    own established node-fixture shape (root + accepted-but-not-further-split leaves) without
    duplicating its private helpers. ``include_model=False`` omits ``model_id`` entirely, for
    the "no model to pin" rejection case.
    """
    if subproject_id is None:
        subproject_id = make_subproject_id(db_session)
    if include_model and model_id is None:
        model_id = make_model_id(db_session, subproject_id=subproject_id)

    run = create_run_record(
        subproject_id=subproject_id,
        stage=RunStage.HARNESS,
        session=db_session,
        model_id=model_id if include_model else None,
    )
    start_run(run_record_id=run.id, session=db_session)

    unique = uuid.uuid4().hex[:6]
    root_modularization_id = f"cand-root-{unique}"
    nodes = [
        {
            "node_id": f"node::depth0::root::{unique}",
            "depth": 0,
            "parent_modularization_id": None,
            "parent_module_id": None,
            "child_submodel_id": f"m1-{unique}",
            "child_modularization_id": root_modularization_id,
            "child_module_ids": [f"mod{i}-{unique}" for i in range(leaf_count)],
            "accepted": True,
            "reason": "accepted",
            "baseline_score": None,
            "child_score": "0.5",
            "branch_stopping_reason": None,
            "recursive_search_stopping_reason": "MAX_ROUNDS",
            "recursive_search_rounds": 1,
            "recursive_search_policy_version": "test-v1",
            "attach_payload": None,
        }
    ]
    for i in range(leaf_count):
        module_id = f"mod{i}-{unique}"
        nodes.append(
            {
                "node_id": f"node::depth1::{module_id}::{i:06d}",
                "depth": 1,
                "parent_modularization_id": root_modularization_id,
                "parent_module_id": module_id,
                "child_submodel_id": f"m1-{unique}::submodel::{module_id}",
                "child_modularization_id": None,
                "child_module_ids": [],
                "accepted": False,
                "reason": "recursive search never retained a genuine, non-degenerate candidate",
                "baseline_score": "0.3",
                "child_score": None,
                "branch_stopping_reason": "NO_VALID_CHILD_DECOMPOSITION",
                "recursive_search_stopping_reason": "SEARCH_EXHAUSTED",
                "recursive_search_rounds": 1,
                "recursive_search_policy_version": "test-v1",
                "attach_payload": _attach_payload(root_modularization_id, module_id),
            }
        )

    create_hierarchy_nodes(run_record_id=run.id, nodes=nodes, session=db_session)
    materialize_accepted_modules(run_record_id=run.id, session=db_session)
    return complete_run(run_record_id=run.id, status=RunStatus.SUCCEEDED, session=db_session)
