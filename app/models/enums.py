"""Enumerated types for the Workbench's own schema.

Every enum here is the Workbench's own, independently-defined copy, even
where its name/values parallel an enum already defined in
``agent1-biochemical-curator`` (e.g. ``ProjectType``,
``ModelingDecisionResolutionSource``). The Workbench never imports another
repository's Python code or shares a database with one -- see
``docs/01_workbench_architecture.md`` -- so there is no mechanism by which
an enum could be "shared" even if the names and intended meanings line up.
A deliberate, disclosed duplication, not an oversight.
"""

from __future__ import annotations

from enum import StrEnum


class ProjectType(StrEnum):
    """The kind of biological system a ``Project`` studies."""

    MICROBIAL_METABOLISM = "MICROBIAL_METABOLISM"
    REGULATORY_NETWORK = "REGULATORY_NETWORK"


class WorkflowLifecycleStatus(StrEnum):
    """A coarse, generic lifecycle state shared by ``Project.status`` and
    ``Subproject.status``.
    """

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    ARCHIVED = "ARCHIVED"


class SubprojectTaskType(StrEnum):
    """Which stage of the five-agent pipeline one ``Subproject`` is driving."""

    BUILD_MODEL = "BUILD_MODEL"
    IMPORT_MODEL = "IMPORT_MODEL"
    TEST_MODEL = "TEST_MODEL"
    CALIBRATE_MODEL = "CALIBRATE_MODEL"
    EXTEND_MODEL = "EXTEND_MODEL"


class ModelBuildRequestSpeciesRole(StrEnum):
    """Covers model input/start species, model output/end species, boundary
    species, and seed metabolites in one table.
    """

    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    BOUNDARY = "BOUNDARY"
    SEED = "SEED"


class ModelBuildRequestReactionRole(StrEnum):
    """Covers seed reactions, required reactions, and excluded reactions in
    one table.
    """

    SEED = "SEED"
    REQUIRED = "REQUIRED"
    EXCLUDED = "EXCLUDED"


class ModelBuildRequestGeneProteinRole(StrEnum):
    """Covers seed genes/proteins and important genes/proteins in one table."""

    SEED = "SEED"
    IMPORTANT = "IMPORTANT"


class ModelBuildRequestPathwayRole(StrEnum):
    """Pathway scope: inclusion and exclusion."""

    INCLUDE = "INCLUDE"
    EXCLUDE = "EXCLUDE"


class ModelingDecisionStatus(StrEnum):
    """Resolution status of one ``ModelingDecision``."""

    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"


class ModelingDecisionResolutionSource(StrEnum):
    """Who (or what) actually resolved a ``ModelingDecision``."""

    USER = "USER"
    AGENT = "AGENT"
    RULE = "RULE"


class ConfidenceClass(StrEnum):
    """Coarse confidence bucket for a ``ModelingDecisionOption``.

    The Workbench's own copy of a vocabulary that also exists, independently,
    in Agent 1 -- see module docstring.
    """

    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class ModelSourceType(StrEnum):
    """How one ``Model`` row's artifact came to exist."""

    GENERATED = "GENERATED"
    IMPORTED = "IMPORTED"
    DERIVED = "DERIVED"


class ModelStatus(StrEnum):
    """A ``Model`` row's own lifecycle state."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class RunStage(StrEnum):
    """Which stage of the five-agent pipeline (or the harness itself) a
    ``RunRecord`` describes.

    A closed vocabulary: the pipeline is fixed at exactly five agents plus
    the integration harness (``docs/01_workbench_architecture.md``).
    """

    AGENT1 = "AGENT1"
    AGENT2 = "AGENT2"
    AGENT3 = "AGENT3"
    AGENT4 = "AGENT4"
    AGENT5 = "AGENT5"
    HARNESS = "HARNESS"


class RunStatus(StrEnum):
    """The execution status of one ``RunRecord``."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


__all__ = [
    "ConfidenceClass",
    "ModelBuildRequestGeneProteinRole",
    "ModelBuildRequestPathwayRole",
    "ModelBuildRequestReactionRole",
    "ModelBuildRequestSpeciesRole",
    "ModelSourceType",
    "ModelStatus",
    "ModelingDecisionResolutionSource",
    "ModelingDecisionStatus",
    "ProjectType",
    "RunStage",
    "RunStatus",
    "SubprojectTaskType",
    "WorkflowLifecycleStatus",
]
