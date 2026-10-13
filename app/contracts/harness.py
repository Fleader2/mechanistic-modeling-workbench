"""Placeholder shapes for the future Workbench <-> Integration Harness boundary.

**Not yet wired to anything.** No code anywhere in this repository
constructs or consumes these types outside of tests exercising their own
shape. The real contract (an HTTP call, a subprocess invocation, or
something else) is a design decision for the increment that actually
builds the harness invocation -- these types exist only so that
``RunRecord`` (``app.models.run_record``) has a documented, concrete
target shape to eventually populate itself from, per the architecture
audit's own "Harness -> Workbench run result" contract-change item.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.models.enums import RunStage


@dataclass(frozen=True, slots=True)
class HarnessInvocationRequest:
    """What the Workbench would eventually send to ask the harness to run
    one stage for one subproject.

    ``contract_version`` is this placeholder shape's own version, bumped
    only when this dataclass's own fields change -- never the version of
    any agent's scientific contract, which the Workbench never enforces or
    interprets (that stays the harness's own job).
    """

    contract_version: str
    subproject_id: UUID
    stage: RunStage
    #: Opaque input payload reference (e.g. a path to a JSON artifact) --
    #: never parsed or interpreted by the Workbench itself.
    input_artifact_reference: str | None = None


@dataclass(frozen=True, slots=True)
class HarnessRunResult:
    """What the harness would eventually report back for one invocation.

    Maps directly onto ``app.persistence.run_record.complete_run``'s own
    keyword arguments -- intentionally, so that wiring this up later is a
    direct pass-through, not a redesign.
    """

    contract_version: str
    run_record_id: UUID
    succeeded: bool
    stage_contract_version: str | None = None
    artifact_reference: str | None = None
    result_summary: str | None = None
    error_summary: str | None = None


CONTRACT_VERSION = "workbench-harness-v0-placeholder"

__all__ = ["CONTRACT_VERSION", "HarnessInvocationRequest", "HarnessRunResult"]
