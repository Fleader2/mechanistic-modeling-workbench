"""Placeholder shape for a future Workbench -> Agent 2 build request, sent
via the integration harness.

**Not yet wired to anything.** Per the architecture audit, Agent 2 today
has no concept of a scoped/partial build -- it only consumes
``Agent1CuratedKnowledgeViewContract``. This dataclass is a placeholder for
what a future contract carrying a ``ModelBuildRequest``'s content to
Agent 2 might look like; it is deliberately named differently from both
Agent 1's own ``ModelSpecification`` (retired) and Agent 2's own
``ModelSpecification`` (the assembled executable model) to avoid repeating
the naming collision the audit flagged.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Agent2BuildRequestEntityReference:
    """One Agent-1-resolved entity reference to include/exclude/seed in the build.

    Mirrors one row of one ``ModelBuildRequest`` child table
    (``app.models.model_build_request``), flattened for transport.
    """

    role: str
    agent1_entity_type: str | None
    agent1_entity_id: UUID | None
    raw_identifier: str | None


@dataclass(frozen=True, slots=True)
class Agent2BuildRequest:
    """What the Workbench would eventually hand to Agent 2 (via the harness)
    to scope a build to one ``ModelBuildRequest``.
    """

    contract_version: str
    model_build_request_id: UUID
    species: tuple[Agent2BuildRequestEntityReference, ...] = ()
    reactions: tuple[Agent2BuildRequestEntityReference, ...] = ()
    gene_proteins: tuple[Agent2BuildRequestEntityReference, ...] = ()
    compartments: tuple[Agent2BuildRequestEntityReference, ...] = ()
    regulatory_interactions: tuple[Agent2BuildRequestEntityReference, ...] = ()
    enzyme_states: tuple[Agent2BuildRequestEntityReference, ...] = ()
    assumptions: tuple[str, ...] = ()


CONTRACT_VERSION = "workbench-agent2-build-request-v0-placeholder"

__all__ = ["CONTRACT_VERSION", "Agent2BuildRequest", "Agent2BuildRequestEntityReference"]
