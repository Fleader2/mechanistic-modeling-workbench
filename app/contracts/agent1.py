"""Placeholder shape for a future Agent 1 biological-context/entity-reference
contract.

**Not yet wired to anything.** No code calls Agent 1 anywhere in this
repository -- the Workbench never imports another repository's runtime
code (see ``docs/01_workbench_architecture.md``). This dataclass documents
the shape a future, versioned, one-way data handoff from Agent 1 might
take, so that ``Project.agent1_organism_id``/``biological_context_summary``
and the ``agent1_entity_type``/``agent1_entity_id`` pairs scattered across
``ModelBuildRequest``'s child tables and ``DatasetReference`` have a
documented origin, even though nothing populates them automatically yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Agent1EntityReference:
    """One resolved Agent-1 entity, as the Workbench would eventually
    receive it -- a copy, never a live reference.
    """

    contract_version: str
    entity_type: str
    entity_id: UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class Agent1BiologicalContextView:
    """What a future Agent 1 contract might expose for populating a
    ``Project``'s own biological-context fields at creation time.

    Field names deliberately mirror ``Project``'s own columns
    (``app.models.project``) so that, when this is wired up, the mapping
    is a direct copy, not a redesign.
    """

    contract_version: str
    organism_id: UUID | None
    organism_display_name: str | None
    strain_genotype_notes: str | None
    biological_process: str | None
    disease: str | None
    tissue: str | None
    cell_type: str | None


CONTRACT_VERSION = "workbench-agent1-context-v0-placeholder"

__all__ = ["CONTRACT_VERSION", "Agent1BiologicalContextView", "Agent1EntityReference"]
