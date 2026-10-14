"""Tests for ``app.contracts.agent2_build_request``: serializing a persisted
``ModelBuildRequest`` into the artifact Agent 2's own
``app.agent2.build_request.build_request_from_dict`` parses.
"""

from __future__ import annotations

import uuid

import pytest

from app.contracts.agent2_build_request import (
    AGENT2_BUILD_REQUEST_CONTRACT_VERSION,
    model_build_request_to_dict,
)
from app.models.enums import (
    ModelBuildRequestGeneProteinRole,
    ModelBuildRequestPathwayRole,
    ModelBuildRequestReactionRole,
    ModelBuildRequestSpeciesRole,
)
from app.persistence.model_build_request import (
    add_assumption,
    add_compartment,
    add_gene_protein,
    add_pathway,
    add_reaction,
    add_species,
    get_model_build_request,
    persist_model_build_request,
)
from tests.persistence.conftest import make_subproject_id

pytestmark = pytest.mark.database


def test_serializes_every_child_collection(db_session):
    subproject_id = make_subproject_id(db_session)
    mbr_id = persist_model_build_request(subproject_id=subproject_id, session=db_session).entity_id
    compound_id = uuid.uuid4()
    reaction_id = uuid.uuid4()
    protein_id = uuid.uuid4()
    compartment_id = uuid.uuid4()

    add_species(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestSpeciesRole.INPUT,
        session=db_session,
        agent1_entity_type="Compound",
        agent1_entity_id=compound_id,
    )
    add_reaction(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestReactionRole.REQUIRED,
        session=db_session,
        agent1_entity_type="Reaction",
        agent1_entity_id=reaction_id,
    )
    add_gene_protein(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestGeneProteinRole.IMPORTANT,
        session=db_session,
        agent1_entity_type="Protein",
        agent1_entity_id=protein_id,
    )
    add_compartment(
        model_build_request_id=mbr_id,
        session=db_session,
        agent1_entity_type="Compartment",
        agent1_entity_id=compartment_id,
    )
    add_pathway(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestPathwayRole.EXCLUDE,
        session=db_session,
        name="glycolysis",
    )
    add_assumption(
        model_build_request_id=mbr_id,
        assumption="treat compartment X as well-mixed",
        session=db_session,
    )

    row = get_model_build_request(db_session, mbr_id)
    data = model_build_request_to_dict(row)

    assert data["contract_version"] == AGENT2_BUILD_REQUEST_CONTRACT_VERSION
    assert data["model_build_request_id"] == str(mbr_id)
    assert data["species"] == [
        {
            "role": "INPUT",
            "agent1_entity_type": "Compound",
            "agent1_entity_id": str(compound_id),
            "raw_identifier": None,
        }
    ]
    assert data["reactions"] == [
        {
            "role": "REQUIRED",
            "agent1_entity_type": "Reaction",
            "agent1_entity_id": str(reaction_id),
            "raw_identifier": None,
        }
    ]
    assert data["gene_proteins"] == [
        {
            "role": "IMPORTANT",
            "agent1_entity_type": "Protein",
            "agent1_entity_id": str(protein_id),
            "raw_identifier": None,
            "localization_entity_type": None,
            "localization_entity_id": None,
            "localization_raw_identifier": None,
        }
    ]
    # Compartments carry no "role" key at all -- the Workbench's own table has no such column.
    assert data["compartments"] == [
        {
            "agent1_entity_type": "Compartment",
            "agent1_entity_id": str(compartment_id),
            "raw_identifier": None,
        }
    ]
    assert data["pathways"] == [
        {"role": "EXCLUDE", "external_pathway_id": None, "name": "glycolysis"}
    ]
    assert data["assumptions"] == ["treat compartment X as well-mixed"]
    assert data["regulatory_interactions"] == []
    assert data["enzyme_states"] == []


def test_raw_identifier_only_reference_is_preserved(db_session):
    subproject_id = make_subproject_id(db_session)
    mbr_id = persist_model_build_request(subproject_id=subproject_id, session=db_session).entity_id
    add_species(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestSpeciesRole.SEED,
        session=db_session,
        raw_identifier="glucose",
    )
    row = get_model_build_request(db_session, mbr_id)
    data = model_build_request_to_dict(row)
    assert data["species"] == [
        {
            "role": "SEED",
            "agent1_entity_type": None,
            "agent1_entity_id": None,
            "raw_identifier": "glucose",
        }
    ]


def test_gene_protein_localization_constraint_is_serialized(db_session):
    subproject_id = make_subproject_id(db_session)
    mbr_id = persist_model_build_request(subproject_id=subproject_id, session=db_session).entity_id
    protein_id = uuid.uuid4()
    localization_id = uuid.uuid4()
    add_gene_protein(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestGeneProteinRole.SEED,
        session=db_session,
        agent1_entity_type="Protein",
        agent1_entity_id=protein_id,
        localization_entity_type="Compartment",
        localization_entity_id=localization_id,
    )
    row = get_model_build_request(db_session, mbr_id)
    data = model_build_request_to_dict(row)
    assert data["gene_proteins"] == [
        {
            "role": "SEED",
            "agent1_entity_type": "Protein",
            "agent1_entity_id": str(protein_id),
            "raw_identifier": None,
            "localization_entity_type": "Compartment",
            "localization_entity_id": str(localization_id),
            "localization_raw_identifier": None,
        }
    ]


def test_species_reference_carries_no_localization_keys(db_session):
    """Only ``gene_proteins`` has a localization constraint column -- every other child
    table's own serialized dict never carries these keys at all."""
    subproject_id = make_subproject_id(db_session)
    mbr_id = persist_model_build_request(subproject_id=subproject_id, session=db_session).entity_id
    add_species(
        model_build_request_id=mbr_id,
        role=ModelBuildRequestSpeciesRole.SEED,
        session=db_session,
        raw_identifier="glucose",
    )
    row = get_model_build_request(db_session, mbr_id)
    data = model_build_request_to_dict(row)
    assert "localization_entity_id" not in data["species"][0]


def test_empty_model_build_request_serializes_to_empty_collections(db_session):
    subproject_id = make_subproject_id(db_session)
    mbr_id = persist_model_build_request(subproject_id=subproject_id, session=db_session).entity_id
    row = get_model_build_request(db_session, mbr_id)
    data = model_build_request_to_dict(row)
    for key in (
        "species",
        "reactions",
        "gene_proteins",
        "compartments",
        "regulatory_interactions",
        "enzyme_states",
        "pathways",
        "assumptions",
    ):
        assert data[key] == []
