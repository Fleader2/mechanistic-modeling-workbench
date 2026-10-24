"""Joint Calibration Workflow, configuration-only increment: ``CalibrationJob`` and its own
mutable-while-``DRAFT`` children.

See ``docs/29_joint_calibration_workflow_design.md`` (the design) and ``docs/30
_joint_calibration_configuration_increment.md`` (what this increment actually built).

**Mutability, by §13 of the design**: unlike every prior increment's own insert-only tables
(``ModuleExecutionSnapshot``, ``DatasetModelAliasMappingRevision``), these rows are *ordinarily
mutable while the owning ``CalibrationJob`` is ``DRAFT``* -- the closest, and deliberately
followed, precedent is ``ModuleSetDraft``/``ModuleSetDraftMember`` (``app.models.module_set``):
real edits and deletes, guarded by one optimistic-concurrency token (``CalibrationJob
.edit_version``), not an insert-only/orphan-and-replace scheme. A ``CalibrationJob`` itself is
never hard-deleted and never becomes a different kind of immutable "saved version" in this
increment -- there is no execution yet to make a snapshot of (docs/29 §3's "three persistence
tiers": this increment implements tier 1 only).

**Never catalog-validated**: ``CalibrationParameterRole.parameter_name`` and a ``PARAMETER``
-kind ``CalibrationExperimentScenarioOverride.target_component_id`` are free text, explicitly
disclosed as curator-declared rather than validated against an authoritative catalog -- no such
catalog exists yet for whole-model parameters (docs/29 §1 row 15, a gap this increment
discloses but does not close). An ``INITIAL_CONDITION``-kind override's own
``target_component_id`` *is* validated server-side, against the target model's own
``ModelSpeciesCatalog`` -- the one real, durable catalog that already exists.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.naming import conv

from app.db.base import Base
from app.models.dataset_model_alias_mapping import DatasetModelAliasMappingRevision
from app.models.enums import (
    CalibrationBindingModelMeaning,
    CalibrationBindingValueSource,
    CalibrationExperimentRole,
    CalibrationJobStatus,
    CalibrationObjectiveWeighting,
    CalibrationParameterRoleKind,
    CalibrationUncertaintySource,
    UncertaintyStatisticKind,
)
from app.models.initial_conditions_alias_mapping import InitialConditionsAliasMappingRevision
from app.models.initial_conditions_dataset import InitialConditionsDataset
from app.models.model import Model
from app.models.subproject import Subproject
from app.models.time_series_dataset import TimeSeriesDataset

_CALIBRATION_JOB_STATUS = Enum(
    CalibrationJobStatus, name="calibration_job_status", create_type=False
)
_CALIBRATION_EXPERIMENT_ROLE = Enum(
    CalibrationExperimentRole, name="calibration_experiment_role", create_type=False
)
_CALIBRATION_OBJECTIVE_WEIGHTING = Enum(
    CalibrationObjectiveWeighting, name="calibration_objective_weighting", create_type=False
)
_CALIBRATION_BINDING_MODEL_MEANING = Enum(
    CalibrationBindingModelMeaning,
    name="calibration_binding_model_meaning",
    create_type=False,
)
_CALIBRATION_BINDING_VALUE_SOURCE = Enum(
    CalibrationBindingValueSource,
    name="calibration_binding_value_source",
    create_type=False,
)
_CALIBRATION_PARAMETER_ROLE_KIND = Enum(
    CalibrationParameterRoleKind, name="calibration_parameter_role_kind", create_type=False
)
_CALIBRATION_UNCERTAINTY_SOURCE = Enum(
    CalibrationUncertaintySource, name="calibration_uncertainty_source", create_type=False
)
_UNCERTAINTY_STATISTIC_KIND = Enum(
    UncertaintyStatisticKind, name="uncertainty_statistic_kind", create_type=False
)


class CalibrationJob(Base):
    """The envelope for one "Models & experimental data" / "Variables, parameters &
    experimental settings" / "Review & readiness" configuration (docs/29 §7)."""

    __tablename__ = "calibration_job"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    subproject_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subproject.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    status: Mapped[CalibrationJobStatus] = mapped_column(
        _CALIBRATION_JOB_STATUS,
        nullable=False,
        default=CalibrationJobStatus.DRAFT,
        server_default=CalibrationJobStatus.DRAFT.value,
    )
    #: Optimistic-concurrency token, incremented by every successful edit (add/remove/change an
    #: arm, experiment, scenario override, or parameter role) -- the identical discipline
    #: ``ModuleSetDraft.edit_version`` already establishes.
    edit_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[str | None] = mapped_column(String)
    updated_by: Mapped[str | None] = mapped_column(String)

    subproject: Mapped[Subproject] = relationship()
    arms: Mapped[list[CalibrationArm]] = relationship(
        back_populates="calibration_job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CalibrationArm.sequence_index",
    )
    parameter_roles: Mapped[list[CalibrationParameterRole]] = relationship(
        back_populates="calibration_job", cascade="all, delete-orphan", passive_deletes=True
    )


class CalibrationArm(Base):
    """One participating whole-model version's own slot in a ``CalibrationJob`` -- always a
    ``Model``, never a ``ModelModule`` (docs/29 §6)."""

    __tablename__ = "calibration_arm"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    calibration_job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("calibration_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("model.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    #: e.g. "no_drug" / "drug_treated" -- free text, never a matching key.
    role_label: Mapped[str | None] = mapped_column(String)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    calibration_job: Mapped[CalibrationJob] = relationship(back_populates="arms")
    model: Mapped[Model] = relationship()
    experiments: Mapped[list[CalibrationExperiment]] = relationship(
        back_populates="arm",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CalibrationExperiment.sequence_index",
    )


class CalibrationExperiment(Base):
    """One experimental evaluation -- a dataset assigned to an arm, with its own scenario
    overrides, observation mapping, and objective-weighting declaration (docs/29 §3/§5)."""

    __tablename__ = "calibration_experiment"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    calibration_arm_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("calibration_arm.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    time_series_dataset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("time_series_dataset.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: The specific, immutable alias-mapping revision this experiment is pinned to -- ``NULL``
    #: until the scientist assigns one on Screen 2. Staleness (a newer revision now exists) is
    #: always computed at read time against the live current revision, never stored here.
    alias_mapping_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dataset_model_alias_mapping_revision.id", ondelete="RESTRICT"),
        index=True,
    )

    #: Initial-Conditions Dataset Import increment (``docs/36``): this experiment's own
    #: optionally-pinned initial-conditions dataset -- e.g. one cell type's own protein/
    #: metabolite abundance profile, giving a ``value_source=INITIAL_CONDITIONS_DATASET``
    #: binding something real to read from. Entirely separate from ``time_series_dataset_id``
    #: (the calibration *target* data): the same model can be evaluated against different cell
    #: types by pinning a different ``InitialConditionsDataset`` here per experiment, while the
    #: calibration-target dataset above stays whatever it already was. ``NULL`` by default --
    #: never required, since a model's own Antimony source may already declare adequate initial
    #: values.
    initial_conditions_dataset_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("initial_conditions_dataset.id", ondelete="RESTRICT"),
        index=True,
    )
    #: The specific, immutable alias-mapping revision (of the dataset above) this experiment is
    #: pinned to -- mirrors ``alias_mapping_revision_id`` exactly, one level down.
    initial_conditions_alias_mapping_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("initial_conditions_alias_mapping_revision.id", ondelete="RESTRICT"),
        index=True,
    )

    role: Mapped[CalibrationExperimentRole] = mapped_column(
        _CALIBRATION_EXPERIMENT_ROLE,
        nullable=False,
        default=CalibrationExperimentRole.CALIBRATION,
        server_default=CalibrationExperimentRole.CALIBRATION.value,
    )
    objective_weighting: Mapped[CalibrationObjectiveWeighting] = mapped_column(
        _CALIBRATION_OBJECTIVE_WEIGHTING,
        nullable=False,
        default=CalibrationObjectiveWeighting.UNWEIGHTED,
        server_default=CalibrationObjectiveWeighting.UNWEIGHTED.value,
    )
    #: Curator-declared free text backing a ``DECLARED_SIGMA`` policy -- see module docstring
    #: and ``CalibrationObjectiveWeighting`` for why this is disclosed text, not a parsed value.
    weighting_notes: Mapped[str | None] = mapped_column(Text)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    arm: Mapped[CalibrationArm] = relationship(back_populates="experiments")
    time_series_dataset: Mapped[TimeSeriesDataset] = relationship()
    alias_mapping_revision: Mapped[DatasetModelAliasMappingRevision | None] = relationship()
    initial_conditions_dataset: Mapped[InitialConditionsDataset | None] = relationship()
    initial_conditions_alias_mapping_revision: Mapped[
        InitialConditionsAliasMappingRevision | None
    ] = relationship()
    variable_bindings: Mapped[list[CalibrationExperimentVariableBinding]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", passive_deletes=True
    )
    output_weightings: Mapped[list[CalibrationExperimentOutputWeighting]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", passive_deletes=True
    )


class CalibrationExperimentVariableBinding(Base):
    """One independent-variable binding for one experiment -- Screen 2's "configure time,
    dose, conditions, and other supported experimental inputs" (docs/29 §7, docs/31;
    supersedes the first revision's narrower ``CalibrationExperimentScenarioOverride``).

    Every binding states its own explicit model meaning (``model_meaning`` --
    ``INITIAL_VALUE``/``PARAMETER_OVERRIDE``/``INTERVENTION``, never left implicit) and its own
    value source: a single curator-typed ``CONSTANT`` for the whole experiment, or a real,
    per-row ``DATASET_COLUMN`` read from the experiment's own pinned dataset at execution time
    -- this row never copies that data in, only names which column to read (module docstring's
    own "preserve original data ... do not silently convert values" requirement)."""

    __tablename__ = "calibration_experiment_variable_binding"
    __table_args__ = (
        CheckConstraint(
            "(model_meaning = 'INTERVENTION' AND intervention_time IS NOT NULL) OR "
            "(model_meaning != 'INTERVENTION' AND intervention_time IS NULL)",
            name=conv("ck_calibration_experiment_variable_binding_intervention_time"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    calibration_experiment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("calibration_experiment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    model_meaning: Mapped[CalibrationBindingModelMeaning] = mapped_column(
        _CALIBRATION_BINDING_MODEL_MEANING, nullable=False
    )
    #: A real, server-validated species id (``INITIAL_VALUE``/species-targeted
    #: ``INTERVENTION``) or independent parameter id (``PARAMETER_OVERRIDE``/parameter-targeted
    #: ``INTERVENTION``), checked against whichever of ``ModelSpeciesCatalog``/
    #: ``ModelParameterCatalog`` is actually ``AVAILABLE`` for the experiment's own arm's model
    #: -- curator-declared, disclosed as unvalidated, only when neither catalog is available
    #: (docs/29 §1 row 15; see ``app.persistence.calibration`` for exactly how this is decided).
    #: Never a ``DERIVED`` parameter (module docstring).
    target_component_id: Mapped[str] = mapped_column(Text, nullable=False)

    value_source: Mapped[CalibrationBindingValueSource] = mapped_column(
        _CALIBRATION_BINDING_VALUE_SOURCE, nullable=False
    )
    #: Set only when ``value_source=CONSTANT``.
    constant_value: Mapped[Decimal | None] = mapped_column(Numeric)
    constant_unit: Mapped[str | None] = mapped_column(String)
    #: Set when ``value_source=DATASET_COLUMN`` (a real
    #: ``TimeSeriesIndependentVariableColumn.column_name`` of the experiment's own pinned
    #: time-series dataset) or ``value_source=INITIAL_CONDITIONS_DATASET`` (a real
    #: ``InitialConditionsMeasurementColumn.column_name`` of the experiment's own pinned
    #: initial-conditions dataset, docs/36) -- validated server-side against whichever dataset
    #: is relevant to the chosen ``value_source``.
    source_column_name: Mapped[str | None] = mapped_column(Text)
    #: e.g. "condition_legend" (derived from the dataset's own recorded condition) or "manual"
    #: (typed directly) -- disclosure of provenance, never interpreted.
    source: Mapped[str | None] = mapped_column(String)

    #: Whole-Model Experimental-Scenario Evaluation increment (``docs/33``): the one moment
    #: during a trajectory this binding's own value takes effect. **Required when
    #: ``model_meaning=INTERVENTION``, forbidden otherwise** -- without this field,
    #: ``INTERVENTION`` would be behaviorally identical to ``INITIAL_VALUE``/
    #: ``PARAMETER_OVERRIDE`` (both of which always take effect at the trajectory's own start,
    #: ``t=0``, and so need no explicit time of their own). Enforced both here (CHECK
    #: constraint, see the owning migration) and in ``app.persistence.calibration
    #: .add_variable_binding``.
    intervention_time: Mapped[Decimal | None] = mapped_column(Numeric)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    experiment: Mapped[CalibrationExperiment] = relationship(back_populates="variable_bindings")


class CalibrationExperimentOutputWeighting(Base):
    """One experiment's own declared uncertainty/weighting setting for one specific output
    (a ``TimeSeriesMeasurementColumn.column_name`` of its own pinned dataset) -- the minimal
    error/weighting contract's own "output level" (``docs/29`` §5, ``docs/32``).

    **The intended joint objective** this configuration describes, never itself executed
    (whole-model execution does not exist yet, ``app.persistence.calibration
    .execution_capability``): for every ``CALIBRATION``-role experiment, output, and
    observation, ``residual_weight = relative_output_weight * uncertainty_scaling``, where
    ``uncertainty_scaling`` is ``1`` under ``CalibrationObjectiveWeighting.UNWEIGHTED`` or
    ``1 / sigma**2`` under ``INVERSE_VARIANCE`` (``sigma`` read from this output's own
    ``uncertainty_source``). The two factors are deliberately independent and **multiply** --
    never conflated, and never silently double-applied without disclosure (task instructions:
    "specify how dataset/output weights and uncertainty scaling interact; prevent accidental
    double-weighting" -- see ``OUTPUT_WEIGHT_AND_UNCERTAINTY_SCALING_BOTH_APPLY``).

    One row per ``(calibration_experiment_id, output_column_name)`` -- absent entirely for an
    output means "no explicit declaration yet," read identically to an explicit ``UNKNOWN``
    uncertainty source with ``relative_output_weight=1`` (never a reason this row cannot exist;
    never a reason this output is silently excluded from the objective).
    """

    __tablename__ = "calibration_experiment_output_weighting"
    __table_args__ = (
        UniqueConstraint(
            "calibration_experiment_id",
            "output_column_name",
            name="uq_calibration_experiment_output_weighting_experiment_output",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    calibration_experiment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("calibration_experiment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: A real ``TimeSeriesMeasurementColumn.column_name`` of this experiment's own pinned
    #: dataset, matched by name (measurement columns are never looked up by id outside their
    #: own dataset) and validated at set time (``app.persistence.calibration
    #: .set_experiment_output_weighting``) -- never fabricated, never left pointing at a
    #: nonexistent output.
    output_column_name: Mapped[str] = mapped_column(Text, nullable=False)

    uncertainty_source: Mapped[CalibrationUncertaintySource] = mapped_column(
        _CALIBRATION_UNCERTAINTY_SOURCE, nullable=False
    )
    #: Set only for ``USER_ASSUMED`` -- a single, curator-typed constant applied to every
    #: observation of this output in this experiment. Never set for ``MEASURED`` (the real
    #: per-row values live in the dataset's own ``TimeSeriesMeasurementUncertaintyColumn``,
    #: read at execution time, never copied here) or ``UNKNOWN``. Always strictly positive and
    #: finite -- never zero (an inverse-variance weight of ``1/sigma**2`` would be infinite),
    #: never negative, never ``inf``/``nan`` (``app.persistence.calibration
    #: .set_experiment_output_weighting`` rejects all three at set time).
    assumed_sigma_value: Mapped[Decimal | None] = mapped_column(Numeric)
    assumed_sigma_unit: Mapped[str | None] = mapped_column(String)
    #: Set only for ``USER_ASSUMED`` -- which specific statistic ``assumed_sigma_value`` is
    #: (standard deviation / variance / standard error, never left implicit; see
    #: ``app.models.enums.UncertaintyStatisticKind``). For ``MEASURED``, the kind is intrinsic
    #: to the dataset's own declared ``TimeSeriesMeasurementUncertaintyColumn.statistic_kind``
    #: and is never duplicated here.
    assumed_sigma_statistic_kind: Mapped[UncertaintyStatisticKind | None] = mapped_column(
        _UNCERTAINTY_STATISTIC_KIND
    )
    #: Independent of ``uncertainty_source`` -- an explicit, curator-chosen relative importance
    #: multiplier for this output, defaulting to ``1`` (no special importance). Always ``> 0``
    #: (module docstring) -- excluding or down-weighting an output to zero is never expressed
    #: here; remove the row, or change the experiment's own role, instead.
    relative_output_weight: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=Decimal("1"), server_default="1"
    )
    #: Curator-recorded rationale for this specific output's own uncertainty declaration (e.g.
    #: "CV% from the core facility's own assay validation," "assumed 10% from literature") --
    #: disclosed provenance, never interpreted or validated as a number (task instructions:
    #: "record assumptions/provenance").
    provenance_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    experiment: Mapped[CalibrationExperiment] = relationship(back_populates="output_weightings")


class CalibrationParameterRole(Base):
    """One parameter's relationship across a ``CalibrationJob`` (docs/29 §5). Collected even
    for a one-arm job (``MODEL_SPECIFIC``/``FIXED`` with bounds); the cross-arm linking roles
    (``EXACT_EQUALITY``/``EXACT_AFFINE_LINK``/``SOFT_PRIOR_LINK``) only become meaningful once a
    job has two or more arms."""

    __tablename__ = "calibration_parameter_role"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    calibration_job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("calibration_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Validated against the covered arm's model's own ``ModelParameterCatalog`` whenever that
    #: catalog is ``AVAILABLE`` at declaration time (docs/31) -- curator-declared, disclosed as
    #: unvalidated only when no catalog exists yet. Captured here, once, at declaration time
    #: (``catalog_validated`` records whether that validation actually ran) -- never
    #: re-evaluated retroactively against a catalog captured later, the identical "captured
    #: once, at save time" discipline ``DatasetModelAliasMappingAssignment.unit_finding``
    #: already establishes.
    parameter_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[CalibrationParameterRoleKind] = mapped_column(
        _CALIBRATION_PARAMETER_ROLE_KIND, nullable=False
    )
    catalog_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Set only for ``FIXED``.
    fixed_value: Mapped[Decimal | None] = mapped_column(Numeric)
    #: Apply to any free role (``MODEL_SPECIFIC``/``EXACT_EQUALITY``/``SOFT_PRIOR_LINK``, or a
    #: non-fixed coefficient of ``EXACT_AFFINE_LINK``) -- collected even in the one-arm case.
    lower_bound: Mapped[Decimal | None] = mapped_column(Numeric)
    upper_bound: Mapped[Decimal | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String)

    #: Set only for ``EXACT_EQUALITY``/``EXACT_AFFINE_LINK`` -- the parameter, on a specific
    #: other arm, this role's own value is derived from.
    reference_arm_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("calibration_arm.id", ondelete="RESTRICT")
    )
    reference_parameter_name: Mapped[str | None] = mapped_column(Text)
    #: Set only for ``EXACT_AFFINE_LINK``: ``target = coefficient_a * reference + coefficient_b``.
    coefficient_a: Mapped[Decimal | None] = mapped_column(Numeric)
    coefficient_a_is_fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    coefficient_b: Mapped[Decimal | None] = mapped_column(Numeric)
    coefficient_b_is_fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    calibration_job: Mapped[CalibrationJob] = relationship(back_populates="parameter_roles")
    reference_arm: Mapped[CalibrationArm | None] = relationship(foreign_keys=[reference_arm_id])
    arm_links: Mapped[list[CalibrationParameterRoleArm]] = relationship(
        back_populates="parameter_role", cascade="all, delete-orphan", passive_deletes=True
    )


class CalibrationParameterRoleArm(Base):
    """Which arms one ``CalibrationParameterRole`` actually covers."""

    __tablename__ = "calibration_parameter_role_arm"
    __table_args__ = (
        UniqueConstraint(
            "calibration_parameter_role_id",
            "calibration_arm_id",
            name="uq_calibration_parameter_role_arm_role_arm",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    calibration_parameter_role_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("calibration_parameter_role.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    calibration_arm_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("calibration_arm.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    parameter_role: Mapped[CalibrationParameterRole] = relationship(back_populates="arm_links")
    arm: Mapped[CalibrationArm] = relationship()


class CalibrationJobRevision(Base):
    """One immutable, versioned snapshot of a ``CalibrationJob``'s own complete configuration,
    captured at the exact moment "Complete review" succeeds (docs/31). Mirrors
    ``DatasetModelAliasMappingRevision``'s own "revision_number increments per parent, every
    save is a complete snapshot, never a sparse diff" discipline, combined with
    ``ModuleExecutionSnapshot``'s own "opaque, pre-serialized JSON payload" discipline for the
    snapshot content itself.

    **A later draft edit never changes an earlier revision.** Editing the job after a revision
    was captured drops its own ``status`` back to ``DRAFT`` (``app.persistence.calibration
    ._bump``) but never touches any ``CalibrationJobRevision`` row already on file; completing
    review again later captures a *new* row with the next ``revision_number``. No persistence
    function in this repository ever issues an ``UPDATE`` against this table.

    ``ON DELETE RESTRICT`` from ``calibration_job``, mirroring ``ModuleExecutionSnapshot``'s
    own "durable, independently-meaningful provenance record" precedent -- a job's own later
    history is never silently lost.
    """

    __tablename__ = "calibration_job_revision"
    __table_args__ = (
        UniqueConstraint(
            "calibration_job_id",
            "revision_number",
            name="uq_calibration_job_revision_job_id_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    calibration_job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("calibration_job.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: 1, 2, 3, ... per ``calibration_job_id`` -- never reused, never reset.
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Opaque, pre-serialized JSON object -- the job's own complete configuration (every arm,
    #: experiment, variable binding, and parameter role, exactly as ``CalibrationJobDetail``
    #: would render them) plus every finding computed at the moment of capture, for
    #: provenance. Decoded nowhere except ``app.schemas.calibration``'s own documented
    #: reader -- the same "opaque TEXT blob" discipline ``ModuleExecutionSnapshot
    #: .snapshot_payload`` already establishes.
    snapshot_payload: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str | None] = mapped_column(String)

    calibration_job: Mapped[CalibrationJob] = relationship()


__all__ = [
    "CalibrationArm",
    "CalibrationExperiment",
    "CalibrationExperimentOutputWeighting",
    "CalibrationExperimentVariableBinding",
    "CalibrationJob",
    "CalibrationJobRevision",
    "CalibrationParameterRole",
    "CalibrationParameterRoleArm",
]
