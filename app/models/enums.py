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
    """The execution status of one ``RunRecord``.

    ``REQUIRES_USER_REVIEW`` (Hierarchical Review/Resume increment): a non-terminal status
    between ``RUNNING`` and (``SUCCEEDED``/``FAILED``) -- the run paused because the
    underlying harness invocation returned ``requires_user_review=True``. A run in this status
    always has a current, unconsumed ``HierarchyCheckpoint`` row; resuming it transitions back
    through ``RUNNING`` exactly like the initial invocation did (see
    ``app.persistence.run_record.resume_run``/``pause_run_for_review``).
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    REQUIRES_USER_REVIEW = "REQUIRES_USER_REVIEW"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class HierarchyReviewDecisionValue(StrEnum):
    """One reviewer decision for one pending hierarchical-recursion review item (Hierarchical
    Review/Resume increment). The Workbench's own copy of the identical vocabulary
    ``agent-integration-harness/app/harness/hierarchical_recursion.types.HumanReviewDecision``
    already defines -- never imported across repositories, see this module's own docstring.
    """

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class HierarchyResumeAttemptStatus(StrEnum):
    """The execution status of one ``HierarchyResumeAttempt`` (Crash-Safe Resume increment) --
    modeled after ``RunStatus``'s own identical style, but deliberately a separate vocabulary:
    an attempt's own ``IN_PROGRESS`` names "the harness resume subprocess call is in flight"
    specifically (never a broader run stage), and an attempt has no ``REQUIRES_USER_REVIEW``
    equivalent (review happens before an attempt ever exists).

    ``PENDING``: created, not yet started. ``IN_PROGRESS``: the harness resume call is (or was
    believed to be, until proven stale) in flight -- see ``app.persistence
    .hierarchy_resume_attempt.is_attempt_stale``. ``SUCCEEDED``/``FAILED``: both reachable from
    ``IN_PROGRESS``; unlike ``RunStatus``, ``FAILED`` here is explicitly retryable (transitions
    back to ``IN_PROGRESS`` on a later retry) -- it is not a dead end.
    """

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ModulePortDirection(StrEnum):
    """A module boundary port's own signal direction (Boundary-Condition Semantics increment).

    The Workbench's own copy of the identical vocabulary
    ``agent2-antimony-builder/app/agent2/types.ModulePortDirection`` already defines -- never
    imported across repositories, see this module's own docstring. Reused verbatim (not
    reinvented) because it is exactly the direction value the harness's own module-simulation
    entrypoint already expects in an ``attach_payload["module_ports"]`` entry.
    """

    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    INPUT_OUTPUT = "INPUT_OUTPUT"


class ModuleBoundaryTreatmentType(StrEnum):
    """How one boundary port of a ``ModelModule`` is scientifically treated (Boundary-Condition
    Semantics increment).

    ``UNRESOLVED`` is the only value automatic derivation is ever allowed to assign (task
    instructions §5: never fabricate a scientific assumption) -- every other value requires an
    explicit human (or, in a future increment, Agent4/5) decision, recorded as its own
    ``ModuleBoundaryPort.decided_at``/``decided_by``.

    ``EXTERNALLY_CONTROLLED``/``PRESCRIBED_INPUT`` both map to Agent 2's own
    ``ModulePort.externally_controlled=True`` when passed to the harness's module-simulation
    entrypoint (the one mechanism Agent 2 itself has for a standalone-executable boundary) --
    distinguished here only for the Workbench's own, richer scientific bookkeeping, never a
    distinction Agent 2 itself needs to make. ``DYNAMIC_COUPLING`` is a genuine, resolved
    scientific determination (the boundary species truly depends on something outside the
    module, e.g. its own parent) that Agent 2 still has no standalone mechanism to represent --
    a module with any such port never reaches ``SIMULATION_READY`` (task instructions: "remains
    non-standalone if appropriate"), even though the port itself is not ambiguous.
    """

    EXTERNALLY_CONTROLLED = "EXTERNALLY_CONTROLLED"
    PRESCRIBED_INPUT = "PRESCRIBED_INPUT"
    DYNAMIC_COUPLING = "DYNAMIC_COUPLING"
    UNRESOLVED = "UNRESOLVED"


class ModuleBoundaryResolutionStatus(StrEnum):
    """Whether one ``ModuleBoundaryPort`` still needs human review.

    Deliberately its own column (not merely inferred ad hoc from ``treatment_type`` at read
    time) so a UI/query can filter "everything still pending review" directly -- kept
    consistent with ``treatment_type`` by the persistence layer alone
    (``app.persistence.module_boundary_port``), never by a database constraint:
    ``PENDING_REVIEW`` if and only if ``treatment_type is UNRESOLVED``.
    """

    PENDING_REVIEW = "PENDING_REVIEW"
    RESOLVED = "RESOLVED"


class ModelModuleExecutionStatus(StrEnum):
    """One ``ModelModule``'s own readiness to be handed to Agent 3 (Boundary-Condition
    Semantics increment).

    ``VIEW_ONLY`` -- the Workbench's own copy of Agent 2's identical vocabulary
    (``AntimonyArtifactReadiness.VIEW_ONLY``): no boundary ports have been derived/declared yet
    (the module's own initial state, before ``derive_boundary_ports`` is ever called -- the
    identical state a module reached purely through the hierarchy search's own output would
    stay in forever without this increment's own review workflow).
    ``REQUIRES_BOUNDARY_REVIEW`` -- at least one boundary port exists but is not yet resolved
    to a standalone-capable treatment (``UNRESOLVED`` or the genuinely-resolved-but-non-
    standalone ``DYNAMIC_COUPLING``).
    ``SIMULATION_READY`` -- every boundary port is resolved to ``EXTERNALLY_CONTROLLED`` or
    ``PRESCRIBED_INPUT`` -- Agent 3 may be invoked.
    """

    VIEW_ONLY = "VIEW_ONLY"
    REQUIRES_BOUNDARY_REVIEW = "REQUIRES_BOUNDARY_REVIEW"
    SIMULATION_READY = "SIMULATION_READY"


class ModuleExecutionKind(StrEnum):
    """Which downstream agent one ``ModuleExecutionSnapshot`` row's own execution was for
    (Module-Level Agent4 Calibration with Immutable Execution-Condition Provenance increment).

    A denormalized copy of information already implicit in the owning ``RunRecord.stage``
    (``AGENT3`` vs ``AGENT4``) -- kept as its own column so a snapshot row is self-describing
    without an eager join, exactly as ``ModelModule.depth``/``module_id`` are themselves
    denormalized copies of their own producing ``HierarchyNode``'s fields. This table is
    deliberately generic over both kinds from the start (only ``CALIBRATION`` is wired up by
    this increment; ``SIMULATION`` support is schema-ready for a later increment to adopt
    without any migration).
    """

    SIMULATION = "SIMULATION"
    CALIBRATION = "CALIBRATION"


__all__ = [
    "ConfidenceClass",
    "HierarchyResumeAttemptStatus",
    "HierarchyReviewDecisionValue",
    "ModelBuildRequestGeneProteinRole",
    "ModelBuildRequestPathwayRole",
    "ModelBuildRequestReactionRole",
    "ModelBuildRequestSpeciesRole",
    "ModelModuleExecutionStatus",
    "ModelSourceType",
    "ModelStatus",
    "ModelingDecisionResolutionSource",
    "ModelingDecisionStatus",
    "ModuleBoundaryResolutionStatus",
    "ModuleBoundaryTreatmentType",
    "ModuleExecutionKind",
    "ModulePortDirection",
    "ProjectType",
    "RunStage",
    "RunStatus",
    "SubprojectTaskType",
    "WorkflowLifecycleStatus",
]
