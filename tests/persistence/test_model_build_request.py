"""Tests for ``app.persistence.model_build_request``."""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import (
    ModelBuildRequestGeneProteinRole,
    ModelBuildRequestPathwayRole,
    ModelBuildRequestReactionRole,
    ModelBuildRequestSpeciesRole,
)
from app.models.model_build_request import ModelBuildRequestSpecies
from app.persistence.model_build_request import (
    add_assumption,
    add_compartment,
    add_enzyme_state,
    add_gene_protein,
    add_pathway,
    add_reaction,
    add_regulatory_interaction,
    add_species,
    persist_model_build_request,
)
from app.persistence.types import PersistenceAction
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


def _make_mbr_id(db_session) -> uuid.UUID:
    subproject_id = make_subproject_id(db_session)
    return persist_model_build_request(subproject_id=subproject_id, session=db_session).entity_id


def test_creates_and_reuses_header(db_session):
    subproject_id = make_subproject_id(db_session)
    first = persist_model_build_request(subproject_id=subproject_id, session=db_session, notes="v1")
    second = persist_model_build_request(
        subproject_id=subproject_id, session=db_session, notes="v2"
    )
    assert first.action is PersistenceAction.CREATED
    assert second.action is PersistenceAction.REUSED_EXISTING
    assert second.entity_id == first.entity_id


def test_input_output_boundary_and_seed_species(db_session):
    mbr_id = _make_mbr_id(db_session)
    compound_id = uuid.uuid4()

    input_result = add_species(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestSpeciesRole.INPUT,
        session=db_session,
        raw_identifier="glucose",
    )
    seed_result = add_species(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestSpeciesRole.SEED,
        session=db_session,
        agent1_entity_type="compound",
        agent1_entity_id=compound_id,
    )
    boundary_result = add_species(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestSpeciesRole.BOUNDARY,
        session=db_session,
        raw_identifier="extracellular glucose",
    )

    assert input_result.action is PersistenceAction.CREATED
    assert seed_result.action is PersistenceAction.CREATED
    assert boundary_result.action is PersistenceAction.CREATED

    row = db_session.get(ModelBuildRequestSpecies, seed_result.entity_id)
    assert row.agent1_entity_id == compound_id


def test_required_and_excluded_reactions(db_session):
    mbr_id = _make_mbr_id(db_session)
    required = add_reaction(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestReactionRole.REQUIRED,
        session=db_session,
        agent1_entity_type="reaction",
        agent1_entity_id=uuid.uuid4(),
    )
    excluded = add_reaction(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestReactionRole.EXCLUDED,
        session=db_session,
        raw_identifier="R_unresolved",
    )
    assert required.action is PersistenceAction.CREATED
    assert excluded.action is PersistenceAction.CREATED


def test_seed_and_important_gene_protein_with_localization(db_session):
    mbr_id = _make_mbr_id(db_session)
    compartment_id = uuid.uuid4()
    result = add_gene_protein(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestGeneProteinRole.IMPORTANT,
        session=db_session,
        agent1_entity_type="protein",
        agent1_entity_id=uuid.uuid4(),
        localization_entity_type="compartment",
        localization_entity_id=compartment_id,
    )
    assert result.action is PersistenceAction.CREATED


def test_compartments_regulatory_interactions_and_enzyme_states(db_session):
    mbr_id = _make_mbr_id(db_session)
    assert add_compartment(model_build_request_id=mbr_id, session=db_session).action is (
        PersistenceAction.CREATED
    )
    assert add_regulatory_interaction(model_build_request_id=mbr_id, session=db_session).action is (
        PersistenceAction.CREATED
    )
    assert add_enzyme_state(model_build_request_id=mbr_id, session=db_session).action is (
        PersistenceAction.CREATED
    )


def test_pathway_include_and_exclude(db_session):
    mbr_id = _make_mbr_id(db_session)
    include = add_pathway(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestPathwayRole.INCLUDE,
        session=db_session,
        external_pathway_id="map00061",
        name="Fatty acid biosynthesis",
    )
    exclude = add_pathway(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestPathwayRole.EXCLUDE,
        session=db_session,
        external_pathway_id="map00062",
    )
    assert include.action is PersistenceAction.CREATED
    assert exclude.action is PersistenceAction.CREATED


def test_user_assumptions(db_session):
    mbr_id = _make_mbr_id(db_session)
    result = add_assumption(
        model_build_request_id=mbr_id,
        assumption="steady-state growth is assumed",
        session=db_session,
        rationale="no transient data available",
        required=True,
    )
    assert result.action is PersistenceAction.CREATED


def test_unresolved_raw_identifiers_are_retained(db_session):
    mbr_id = _make_mbr_id(db_session)
    result = add_species(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestSpeciesRole.SEED,
        session=db_session,
        raw_identifier="some-user-provided-name-not-yet-resolved",
    )
    row = db_session.get(ModelBuildRequestSpecies, result.entity_id)
    assert row.agent1_entity_id is None
    assert row.raw_identifier == "some-user-provided-name-not-yet-resolved"


def test_idempotent_child_persistence(db_session):
    mbr_id = _make_mbr_id(db_session)
    reaction_id = uuid.uuid4()
    first = add_reaction(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestReactionRole.REQUIRED,
        session=db_session,
        agent1_entity_type="reaction",
        agent1_entity_id=reaction_id,
    )
    second = add_reaction(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestReactionRole.REQUIRED,
        session=db_session,
        agent1_entity_type="reaction",
        agent1_entity_id=reaction_id,
    )
    assert first.action is PersistenceAction.CREATED
    assert second.action is PersistenceAction.REUSED_EXISTING
    assert first.entity_id == second.entity_id
