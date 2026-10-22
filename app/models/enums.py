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
    (Module-Level Agent4 Calibration with Immutable Execution-Condition Provenance increment;
    ``VALIDATION`` added by the Module-Level Agent5 Validation and Experimental Design
    increment, migration ``0009_module_execution_snapshot_validation_kind``, a one-way
    PostgreSQL enum addition -- identical precedent to ``RunStatus.REQUIRES_USER_REVIEW``'s own
    prior migration).

    A denormalized copy of information already implicit in the owning ``RunRecord.stage``
    (``AGENT3``/``AGENT4``/``AGENT5``) -- kept as its own column so a snapshot row is
    self-describing without an eager join, exactly as ``ModelModule.depth``/``module_id`` are
    themselves denormalized copies of their own producing ``HierarchyNode``'s fields.
    ``SIMULATION`` support remains schema-ready for a later increment to wire up without any
    further migration.
    """

    SIMULATION = "SIMULATION"
    CALIBRATION = "CALIBRATION"
    VALIDATION = "VALIDATION"


class ModuleAggregateCompleteness(StrEnum):
    """Whether one ``ModuleAggregate``'s own roll-up is backed by enough evidence to call it
    done, for one target (a module or the hierarchy root) and one ``ModuleExecutionKind``
    (Hierarchical Aggregation of Module-Level Agent3/4/5 Results increment).

    Deliberately three values, never a blended score: this increment never averages or
    otherwise merges child modules' own heterogeneous results (task instructions §4), so
    completeness is a statement about *coverage*, not about scientific quality or agreement.

    ``COMPLETE`` -- the target's own direct result (if attempted) succeeded, and every direct
    child (if any) is itself ``COMPLETE`` for this execution kind.
    ``PARTIAL`` -- at least one, but not all, of {the target's own direct attempt, its direct
    children} succeeded/is ``COMPLETE`` -- some real evidence exists, but the picture is not
    whole.
    ``EMPTY`` -- no successful evidence anywhere in this target's own subtree for this
    execution kind (nothing attempted, or everything attempted failed).
    """

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"


class CrossModuleDiagnosticCategory(StrEnum):
    """What kind of cross-module inconsistency one ``CrossModuleDiagnostic`` finding reports
    (Cross-Module Consistency and Reconciliation Diagnostics increment). A 1:1 mapping onto
    task instructions §2's own seven numbered detection requirements -- never a
    catch-all "something looks wrong" bucket, so each finding's own category already says
    which specific comparison produced it.
    """

    SHARED_BOUNDARY_SPECIES_CONFLICT = "SHARED_BOUNDARY_SPECIES_CONFLICT"
    UNIT_INCOMPATIBILITY = "UNIT_INCOMPATIBILITY"
    PARAMETER_ASSUMPTION_CONFLICT = "PARAMETER_ASSUMPTION_CONFLICT"
    PARENT_CHILD_BOUNDARY_INCONSISTENCY = "PARENT_CHILD_BOUNDARY_INCONSISTENCY"
    DATASET_CONTEXT_INCOMPATIBILITY = "DATASET_CONTEXT_INCOMPATIBILITY"
    CONFLICTING_CALIBRATION_OR_VALIDATION_OUTCOME = "CONFLICTING_CALIBRATION_OR_VALIDATION_OUTCOME"
    INSUFFICIENT_EVIDENCE_FOR_COMPARISON = "INSUFFICIENT_EVIDENCE_FOR_COMPARISON"


class DiagnosticSeverity(StrEnum):
    """How serious one ``CrossModuleDiagnostic`` finding is (Cross-Module Consistency and
    Reconciliation Diagnostics increment). No existing enum in this schema already carries
    this exact four-value vocabulary (``ModuleAggregateCompleteness`` is a coverage statement,
    a different concept) -- confirmed by inspection before adding a new one, per task
    instructions §3's own "use existing conventions if equivalent enums exist."

    ``INFO`` -- worth disclosing, not actionable on its own (e.g. two modules used different,
    unverifiable dataset contexts).
    ``WARNING`` -- a real heterogeneity or assumption mismatch that does not, by itself, make
    either module's own result wrong.
    ``ERROR`` -- a genuine logical conflict (the same species/parameter claimed to have two
    different, incompatible values).
    ``UNRESOLVED`` -- the comparison itself could not be concluded at all, because one side
    lacks the evidence needed to compare safely -- never silently skipped, and never treated
    as "no conflict" (task instructions §4: "never mark the hierarchy globally valid just
    because no conflict was detected").
    """

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    UNRESOLVED = "UNRESOLVED"


class DiagnosticReviewStatus(StrEnum):
    """Whether a human has reviewed one ``CrossModuleDiagnostic`` finding (Cross-Module
    Consistency and Reconciliation Diagnostics increment).

    Deliberately the one *mutable* field this increment adds anywhere: marking a finding
    reviewed never alters the finding's own detection content (category/severity/message/
    evidence) or any source record it describes -- see
    ``app.models.cross_module_diagnostic``'s own module docstring.
    """

    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"


class UnitParseStatus(StrEnum):
    """Whether one raw unit string could be resolved against the Workbench's own ``pint``
    registry (Structured Units and Dimensional-Consistency Validation increment). The mapped
    column type for ``app.models.unit_resolution.UnitResolution.parse_status`` -- see
    ``app.units``'s own identical-named class for the full rationale (deliberately re-declared
    here, not imported from ``app.units``, so every enum this schema maps to a real column
    lives in this one module, matching every other enum in this file; ``app.units`` reads this
    value only as its own plain ``.value`` string, never importing this class back).

    ``MISSING`` (no unit recorded) is kept distinct from ``MALFORMED`` (a unit string recorded
    but unparseable) -- never fabricated as either when the true state is unknown (task
    instructions §9).
    """

    PARSED = "PARSED"
    MALFORMED = "MALFORMED"
    MISSING = "MISSING"


class MeasurementValueStatus(StrEnum):
    """What one Data-tab cell in a time-series dataset's own measurement/time column actually
    says, for `app.models.time_series_dataset.TimeSeriesDatasetRow.measurements` -- never
    collapsed to a bare numeric-or-null, since "left blank," "recorded as not applicable,"
    "recorded as unknown," and "a real, reported zero" are four different scientific claims
    (task instructions: "distinguish missing, unknown, and not-applicable values; preserve
    reported zeros").

    ``MEASURED`` is the only status carrying a numeric value (zero is a perfectly ordinary
    ``MEASURED`` value, never treated as absent). ``UNRECOGNIZED`` is for a non-blank cell that
    is neither numeric nor one of the recognized missing/unknown/not-applicable tokens -- kept
    distinct from ``MISSING`` so a typo or stray text is never silently treated as "no data,"
    and is always paired with a non-blocking validation finding naming the raw text.
    """

    MEASURED = "MEASURED"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"
    UNRECOGNIZED = "UNRECOGNIZED"


class ModelSpeciesCatalogStatus(StrEnum):
    """Whether a durable, whole-model species/compartment catalog is actually available for a
    ``Model`` row, for `app.models.model_species_catalog.ModelSpeciesCatalog.status` (Model-
    Species Catalog Prerequisite increment, ``docs/26``).

    No row at all means "never attempted" -- treated identically to ``UNAVAILABLE`` by every
    reader (never silently treated as a valid, empty catalog). ``AVAILABLE`` means capture
    genuinely succeeded: every ``ModelSpeciesCatalog.species``/``compartments`` row was
    verified, via a real Antimony/RoadRunner load, to actually exist in the compiled model --
    never merely present in Agent 2's own structural network. ``UNAVAILABLE`` is an explicit,
    disclosed failure (``unavailable_reason`` always set) -- a capture failure never leaves a
    model silently treated as mapping-ready, and is never a reason to simulate, guess, or
    substitute a module's own (structurally different, never a whole model's) snapshot.
    """

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ModelSpeciesKind(StrEnum):
    """A real, compiled species' own RoadRunner-reported kind -- ``getFloatingSpeciesIds``
    versus ``getBoundarySpeciesIds`` -- for
    `app.models.model_species_catalog.ModelSpecies.kind`. Both are genuine, addressable species
    in the compiled model; neither is ever omitted from a catalog on this distinction alone."""

    FLOATING = "FLOATING"
    BOUNDARY = "BOUNDARY"


class AliasMappingAssignmentStatus(StrEnum):
    """One measurement column's own status within a single dataset<->model-version alias-
    mapping revision (`app.models.dataset_model_alias_mapping.DatasetModelAliasMappingAssignment
    .status`), for the model-specific alias-mapping increment (``docs/27``).

    Three genuinely different claims, never conflated: ``ASSIGNED`` (this column's data *is*
    the named real species -- ``target_antimony_species_id`` always set); ``SKIPPED`` (a
    deliberate, explicit decision that this column has no species home -- never re-offered as
    if undecided); ``UNRESOLVED`` (the default for a column no one has decided about yet --
    task instructions: "allow incomplete mappings to be saved with explicit unresolved
    status"). Every measurement column of a dataset gets exactly one row with one of these
    three statuses in every revision -- never silently omitted.
    """

    ASSIGNED = "ASSIGNED"
    SKIPPED = "SKIPPED"
    UNRESOLVED = "UNRESOLVED"


class AliasMappingUnitFinding(StrEnum):
    """The outcome of comparing one ``ASSIGNED`` column's own declared unit against its target
    species' own unit (``app.units.compare_units``, task instructions: "use existing units
    machinery to distinguish compatible, incompatible, and unknown units ... never silently
    convert values") -- ``None`` only when the assignment itself is not ``ASSIGNED`` (nothing
    to compare against).

    ``UNKNOWN`` collapses ``app.units.UnitComparisonStatus``'s own ``MISSING``/``MALFORMED``
    (either side absent, or present but unparseable) -- both mean "cannot tell," the one
    distinction task instructions actually asked for; the full ``compare_units`` result is
    still retained verbatim alongside, never discarded, for anyone who needs the finer
    distinction.
    """

    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


class ModuleSetOriginMethod(StrEnum):
    """How one ``ModuleSetVersion`` (or, while open, ``ModuleSetDraft``) came to have its own
    content (Module-Set Domain Model increment, ``docs/20_module_set_domain_contract.md``).

    Tracked per version/draft, never per member (deferred -- see that doc's own §5/§10): one
    holistic, user-confirmed label per save action, matching the Figma "Module set draft"/"Save
    as new module set"/"Save new set version" screens' own single "Method:" line exactly.

    ``MIXED_EDITED`` names a version that started from an existing/automated base but was then
    hand-edited before saving -- distinct from ``MANUAL`` (built from scratch, no automated
    search behind it at all) and ``AUTOMATED`` (an unedited automated result). The first
    increment built against this contract only ever produces ``AUTOMATED`` (its one supported
    draft source is an existing, unedited automated hierarchical run); ``MANUAL``/
    ``MIXED_EDITED`` become reachable only once manual editing is built, but are declared now so
    that increment never needs a migration to widen this enum.
    """

    AUTOMATED = "AUTOMATED"
    MANUAL = "MANUAL"
    MIXED_EDITED = "MIXED_EDITED"


class ModuleSetDraftStatus(StrEnum):
    """One ``ModuleSetDraft``'s own lifecycle state (Module-Set Domain Model increment).

    ``OPEN`` -- mutable working state, freely editable (not yet exercised by the first
    increment, which only ever reads/saves/discards an unedited draft -- editing is deferred).
    ``DISCARDED`` -- soft-marked, never hard-deleted (a decided choice, not a routine one --
    see ``docs/20_module_set_domain_contract.md`` §9); excluded from every default listing, and,
    like every draft regardless of status, can never be a target of execution.
    ``SAVED`` -- terminal; ``ModuleSetDraft.resulting_version_id`` names the immutable
    ``ModuleSetVersion`` this draft became. A draft already ``SAVED``/``DISCARDED`` can never be
    saved again (the save-idempotency/duplicate-save-protection rule).
    """

    OPEN = "OPEN"
    DISCARDED = "DISCARDED"
    SAVED = "SAVED"


__all__ = [
    "AliasMappingAssignmentStatus",
    "AliasMappingUnitFinding",
    "ConfidenceClass",
    "CrossModuleDiagnosticCategory",
    "DiagnosticReviewStatus",
    "DiagnosticSeverity",
    "HierarchyResumeAttemptStatus",
    "HierarchyReviewDecisionValue",
    "MeasurementValueStatus",
    "ModelBuildRequestGeneProteinRole",
    "ModelBuildRequestPathwayRole",
    "ModelBuildRequestReactionRole",
    "ModelBuildRequestSpeciesRole",
    "ModelModuleExecutionStatus",
    "ModelSourceType",
    "ModelSpeciesCatalogStatus",
    "ModelSpeciesKind",
    "ModelStatus",
    "ModelingDecisionResolutionSource",
    "ModelingDecisionStatus",
    "ModuleAggregateCompleteness",
    "ModuleBoundaryResolutionStatus",
    "ModuleBoundaryTreatmentType",
    "ModuleExecutionKind",
    "ModulePortDirection",
    "ModuleSetDraftStatus",
    "ModuleSetOriginMethod",
    "ProjectType",
    "RunStage",
    "RunStatus",
    "SubprojectTaskType",
    "UnitParseStatus",
    "WorkflowLifecycleStatus",
]
