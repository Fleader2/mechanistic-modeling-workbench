"""Scoped-Build Support increment: serialize a persisted ``ModelBuildRequest`` into the
artifact Agent 2 actually consumes (``agent2-antimony-builder/app/agent2/build_request``).

This is the Workbench's own, independently-maintained copy of that contract's shape --
transcribed, never imported, the same "no repository imports another's Python package"
discipline every other cross-repository boundary in this project's family already uses
(``app/contracts/harness.py``'s own identical relationship to the harness's
``workbench_contracts.py``). ``AGENT2_BUILD_REQUEST_CONTRACT_VERSION`` below must match Agent
2's own constant of the identical name exactly, or Agent 2's own ``build_request_from_dict``
rejects the artifact before anything else runs.

Deliberately named ``ModelBuildRequest`` on both sides of this boundary -- the Workbench chose
that name specifically to avoid colliding with Agent 2's own, unrelated, pre-existing
``ModelSpecification`` (the complete assembled executable model); see
``app/models/model_build_request.py``'s own docstring for the full naming-collision rationale.

Only ``model_build_request_to_dict`` performs I/O-free serialization here; writing the result
to a file and invoking the harness is ``app.orchestration.run_orchestrator``'s job, exactly like
``app/contracts/harness.py``'s own ``request_to_dict``/``result_from_dict`` are never themselves
responsible for the subprocess call.
"""

from __future__ import annotations

from app.models.model_build_request import (
    ModelBuildRequest,
    ModelBuildRequestCompartment,
    ModelBuildRequestEnzymeState,
    ModelBuildRequestGeneProtein,
    ModelBuildRequestPathway,
    ModelBuildRequestReaction,
    ModelBuildRequestRegulatoryInteraction,
    ModelBuildRequestSpecies,
)

#: Must match ``agent2-antimony-builder/app/agent2/build_request``'s own
#: ``AGENT2_BUILD_REQUEST_CONTRACT_VERSION`` exactly, or Agent 2's own
#: ``build_request_from_dict`` rejects this artifact before scoping ever runs.
AGENT2_BUILD_REQUEST_CONTRACT_VERSION = "agent2-build-request-v1"

_RoleBearing = ModelBuildRequestSpecies | ModelBuildRequestReaction | ModelBuildRequestGeneProtein
_RoleFree = (
    ModelBuildRequestCompartment
    | ModelBuildRequestRegulatoryInteraction
    | ModelBuildRequestEnzymeState
)


def _entity_reference_dict(row: _RoleBearing | _RoleFree, *, has_role: bool) -> dict:
    data: dict = {
        "agent1_entity_type": row.agent1_entity_type,
        "agent1_entity_id": str(row.agent1_entity_id) if row.agent1_entity_id else None,
        "raw_identifier": row.raw_identifier,
    }
    if has_role:
        data["role"] = row.role.value
    if isinstance(row, ModelBuildRequestGeneProtein):
        data["localization_entity_type"] = row.localization_entity_type
        data["localization_entity_id"] = (
            str(row.localization_entity_id) if row.localization_entity_id else None
        )
        data["localization_raw_identifier"] = row.localization_raw_identifier
    return data


def _pathway_reference_dict(row: ModelBuildRequestPathway) -> dict:
    return {
        "role": row.role.value,
        "external_pathway_id": row.external_pathway_id,
        "name": row.name,
    }


def model_build_request_to_dict(row: ModelBuildRequest) -> dict:
    """Serialize a persisted ``ModelBuildRequest`` (with its eight child collections already
    loaded) into the plain, JSON-ready dict Agent 2's own ``build_request_from_dict`` parses.

    Every ``agent1_entity_id`` is serialized as a plain string -- Agent 2's own local contract
    never carries a UUID type, matching Agent 1's own string-id convention throughout
    ``app.agent2.types``. ``raw_identifier`` is always included, even when ``None``, exactly
    like every other optional field -- never silently omitted.

    A ``gene_proteins`` entry additionally always carries
    ``localization_entity_type``/``localization_entity_id``/``localization_raw_identifier``
    (``None`` when the row sets none of them) -- the only child table with a subcellular
    localization constraint. Agent 2's own scoping engine does not yet enforce it (a disclosed
    ``UNSUPPORTED_LOCALIZATION_CONSTRAINT`` warning, not a silent no-op); carrying it through
    the contract regardless means no later increment needs to touch this serializer again to
    start acting on it.
    """
    return {
        "contract_version": AGENT2_BUILD_REQUEST_CONTRACT_VERSION,
        "model_build_request_id": str(row.id),
        "species": [_entity_reference_dict(r, has_role=True) for r in row.species],
        "reactions": [_entity_reference_dict(r, has_role=True) for r in row.reactions],
        "gene_proteins": [_entity_reference_dict(r, has_role=True) for r in row.gene_proteins],
        "compartments": [_entity_reference_dict(r, has_role=False) for r in row.compartments],
        "regulatory_interactions": [
            _entity_reference_dict(r, has_role=False) for r in row.regulatory_interactions
        ],
        "enzyme_states": [_entity_reference_dict(r, has_role=False) for r in row.enzyme_states],
        "pathways": [_pathway_reference_dict(r) for r in row.pathways],
        "assumptions": [a.assumption for a in row.assumptions],
    }


__all__ = ["AGENT2_BUILD_REQUEST_CONTRACT_VERSION", "model_build_request_to_dict"]
