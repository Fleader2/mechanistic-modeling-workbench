"""Whole-Model Experimental-Scenario Evaluation increment: resolve one saved
``CalibrationJobRevision``'s own experiment, together with explicit candidate parameter
values, into a fully-resolved scenario -- validated against authoritative catalogs, with every
conflict/dosing-schedule ambiguity rejected -- then submit/track/persist its evaluation as a
background ``RunRecord``, mirroring ``app.persistence.module_set_execution``'s own established
submit/claim/track discipline exactly.

**Prediction only, never fitting.** This module never introduces an optimizer, never adjusts a
candidate value on its own, and never touches ``execution_capability``/``WHOLE_MODEL_EXECUTION``
(calibration execution stays disabled, unconditionally, regardless of this module's own
existence) -- it only answers "given this exact, already-resolved scenario, what does the
model predict," for Agent 4's future joint-optimization loop to call, once per experiment, per
candidate parameter vector.

**Operates on a saved revision's own frozen snapshot, never the live, possibly-still-being-
edited draft** -- ``CalibrationJobRevision.snapshot_payload`` (``app.persistence.calibration
._build_snapshot_payload``) is the one source of truth for every binding/output-weighting this
module reads; a later draft edit (which never touches an already-captured revision) can never
retroactively change what an already-submitted evaluation run actually used.

**Precedence (module docstring of ``app.agent3.scenario_evaluation``, mirrored here)**: a
binding's own resolved value (``INITIAL_VALUE``/``PARAMETER_OVERRIDE``/the starting value of an
``INTERVENTION``) is applied once, at the scenario's own start; a caller-supplied candidate
value for the identical target as a ``PARAMETER_OVERRIDE``/parameter-targeted ``INTERVENTION``
binding is a conflicting duplicate, always rejected -- never silently preferred one way or the
other.

**Dosing-schedule discipline**: a ``DATASET_COLUMN``-sourced binding's own value must be
identical across every row of this experiment's own (dataset, condition) scope -- a dataset
column that genuinely varies row-to-row within that scope is a dosing *schedule*, never
silently reduced to a single scalar override (task instructions: "never treat successive dose
rows as a dosing schedule without explicit instructions") -- rejected with an actionable error
naming every distinct value found.

**Initial-conditions discipline (Initial-Conditions Dataset Import increment, docs/36)**: an
``INITIAL_CONDITIONS_DATASET``-sourced binding's own value is resolved from this experiment's
own pinned ``InitialConditionsDataset``, via its own pinned alias-mapping revision -- never
hand-typed. The identical never-silently-reduced discipline applies to a duplicate
``target_name`` (``app.initial_conditions.parser``'s own disclosed, non-blocking finding): if
the dataset's own duplicate rows for the one target_name a binding resolves to actually
disagree, this is rejected with an actionable error naming every distinct value found, exactly
like a varying dosing-schedule column. An abundance measurement is never automatically treated
as a model concentration or parameter value: if the mapping's own ``unit_finding`` (computed
once, at mapping-save time, from ``compare_units``) is ``INCOMPATIBLE``, resolution is rejected
outright rather than silently handing an incompatible-unit number to the harness -- the one
place this check previously stopped short of actually reaching. ``UNKNOWN`` (either side's own
unit undeclared) is never treated as equivalent to a known-safe unit, but is also never
blocking on its own -- "cannot tell" is not the same claim as "confirmed incompatible."
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.calibration import CalibrationExperiment, CalibrationJob, CalibrationJobRevision
from app.models.calibration_scenario_evaluation import CalibrationScenarioEvaluationSnapshot
from app.models.enums import (
    AliasMappingAssignmentStatus,
    AliasMappingUnitFinding,
    ModelParameterCatalogStatus,
    ModelParameterKind,
    ModelSpeciesCatalogStatus,
    RunStage,
    RunStatus,
)
from app.models.initial_conditions_dataset import InitialConditionsDatasetRow
from app.models.run_record import RunRecord
from app.models.time_series_dataset import TimeSeriesDatasetRow, TimeSeriesMeasurementColumn
from app.persistence.dataset_model_alias_mapping import get_mapping_revision
from app.persistence.initial_conditions_alias_mapping import (
    get_mapping_revision as get_ic_mapping_revision,
)
from app.persistence.model_parameter_catalog import get_model_parameter_catalog
from app.persistence.model_species_catalog import get_model_species_catalog
from app.persistence.run_record import create_run_record
from app.storage import read_artifact

#: Active (non-terminal) run statuses -- used for the application-level duplicate-active-run
#: lookup (module docstring of ``app.models.calibration_scenario_evaluation``: this cannot be
#: a database constraint).
_ACTIVE_RUN_STATUSES = (RunStatus.PENDING, RunStatus.RUNNING)


class ScenarioResolutionError(ValueError):
    """Raised when a scenario cannot be resolved into a well-formed, unambiguous evaluation
    request: an unknown experiment/condition, a conflicting override, a dataset column that
    varies within its own (experiment, condition) scope, an unresolvable intervention target,
    or no mapped output species at all. Always actionable -- never a generic failure."""


class ScenarioEvaluationAlreadyActiveError(ValueError):
    """Raised when a genuinely identical scenario (same experiment, condition, candidate
    values, and solver settings) already has an active (``PENDING``/``RUNNING``) run --
    deliberately best-effort, never a database-level guarantee (see
    ``app.models.calibration_scenario_evaluation`` module docstring). Carries the existing run
    so the caller can poll it instead of submitting a true duplicate."""

    def __init__(self, existing_run: RunRecord) -> None:
        self.existing_run = existing_run
        super().__init__(
            f"an identical scenario evaluation is already active (run {existing_run.id}, "
            f"status={existing_run.status.value})"
        )


@dataclass(frozen=True)
class ResolvedScenario:
    """Everything needed to build a harness ``ScenarioEvaluationRequest`` for one experiment,
    plus the real observed values/units to display alongside the predictions once they come
    back."""

    antimony_text: str
    antimony_artifact_reference: str
    antimony_checksum: str | None
    requested_times: tuple[Decimal, ...]
    requested_row_ids: tuple[str, ...]
    requested_output_ids: tuple[str, ...]
    #: ``antimony_species_id`` -> this experiment's own measurement column name, for display.
    output_column_names: dict[str, str]
    #: ``antimony_species_id`` -> that measurement column's own declared unit (``None`` if
    #: never declared) -- preserved, never converted (module docstring's "honest units").
    output_units: dict[str, str | None]
    #: ``antimony_species_id`` -> one observed value per ``requested_times`` entry (``None``
    #: where the dataset row itself has no ``MEASURED`` value for that column).
    observed_values: dict[str, tuple[float | None, ...]]
    parameter_overrides: dict[str, Decimal]
    initial_value_overrides: dict[str, Decimal]
    interventions: tuple[dict, ...]
    input_hash: str


def _find_experiment_snapshot(revision: CalibrationJobRevision, experiment_id: UUID) -> dict:
    payload = json.loads(revision.snapshot_payload)
    experiment_id_str = str(experiment_id)
    for arm in payload["arms"]:
        for experiment in arm["experiments"]:
            if experiment["id"] == experiment_id_str:
                return {**experiment, "model_id": arm["model_id"]}
    raise ScenarioResolutionError(
        f"revision {revision.revision_number} of calibration job {revision.calibration_job_id} "
        f"has no experiment with id {experiment_id}"
    )


def _rows_for_scope(
    session: Session, *, time_series_dataset_id: UUID, condition_id: str | None
) -> list[TimeSeriesDatasetRow]:
    all_rows = list(
        session.scalars(
            select(TimeSeriesDatasetRow)
            .where(TimeSeriesDatasetRow.time_series_dataset_id == time_series_dataset_id)
            .order_by(TimeSeriesDatasetRow.row_index.asc())
        )
    )
    declared_conditions = {r.condition_id for r in all_rows if r.condition_id is not None}
    if condition_id is None:
        if declared_conditions:
            raise ScenarioResolutionError(
                f"this experiment's dataset declares {len(declared_conditions)} distinct "
                "condition(s); condition_id must be specified to scope this evaluation to one "
                "of them, never evaluated across all of them at once"
            )
        scoped = all_rows
    else:
        if condition_id not in declared_conditions:
            raise ScenarioResolutionError(
                f"condition_id {condition_id!r} is not a condition this experiment's dataset "
                f"actually declares ({sorted(declared_conditions)!r})"
            )
        scoped = [r for r in all_rows if r.condition_id == condition_id]
    scoped = [r for r in scoped if r.time_value is not None]
    if not scoped:
        raise ScenarioResolutionError(
            "no dataset row with a real, recorded time value is in scope for this experiment"
            + (f" and condition {condition_id!r}" if condition_id is not None else "")
        )
    return scoped


def _resolve_dataset_column_value(
    rows: list[TimeSeriesDatasetRow], *, column_name: str, binding_label: str
) -> Decimal:
    """The one value a ``DATASET_COLUMN`` binding resolves to across every in-scope row --
    raises ``ScenarioResolutionError`` naming every distinct value found if the column is not
    constant across this scope (module docstring's dosing-schedule rejection)."""
    distinct_values: dict[str, float] = {}
    for row in rows:
        entry = json.loads(row.independent_variables).get(column_name)
        if entry is None or entry.get("value") is None:
            continue
        distinct_values[str(entry["value"])] = entry["value"]
    if not distinct_values:
        raise ScenarioResolutionError(
            f"{binding_label} reads independent-variable column {column_name!r}, which has no "
            "recorded value in any in-scope dataset row"
        )
    if len(distinct_values) > 1:
        raise ScenarioResolutionError(
            f"{binding_label} reads independent-variable column {column_name!r}, which varies "
            f"across in-scope dataset rows ({sorted(distinct_values.values())!r}) -- this is a "
            "dosing schedule, never silently reduced to a single value; scope this evaluation "
            "to a single condition, or model the variation as an explicit intervention"
        )
    return Decimal(str(next(iter(distinct_values.values()))))


def _resolve_initial_conditions_dataset_value(
    session: Session,
    *,
    initial_conditions_dataset_id: UUID,
    alias_mapping_revision_number: int | None,
    model_id: UUID,
    target_component_id: str,
    column_name: str,
    binding_label: str,
) -> Decimal:
    """The one value an ``INITIAL_CONDITIONS_DATASET`` binding resolves to -- see module
    docstring's "initial-conditions discipline" for the duplicate-target_name rejection this
    mirrors from ``_resolve_dataset_column_value``, and for the unit-compatibility rejection
    carried forward from the mapping's own ``unit_finding`` (computed once, at mapping-save
    time, by ``app.persistence.initial_conditions_alias_mapping``)."""
    if alias_mapping_revision_number is None:
        raise ScenarioResolutionError(
            f"{binding_label} reads from this experiment's own pinned initial-conditions "
            "dataset, but no alias-mapping revision is pinned for it"
        )
    revision = get_ic_mapping_revision(
        session,
        initial_conditions_dataset_id=initial_conditions_dataset_id,
        model_id=model_id,
        revision_number=alias_mapping_revision_number,
    )
    if revision is None:
        raise ScenarioResolutionError(
            f"{binding_label} reads from initial-conditions alias-mapping revision "
            f"{alias_mapping_revision_number}, which no longer exists"
        )
    assignment = next(
        (
            a
            for a in revision.assignments
            if a.status is AliasMappingAssignmentStatus.ASSIGNED
            and a.target_id == target_component_id
        ),
        None,
    )
    if assignment is None:
        raise ScenarioResolutionError(
            f"{binding_label} has no row in this experiment's own pinned initial-conditions "
            f"dataset mapped to {target_component_id!r}"
        )
    if assignment.unit_finding is AliasMappingUnitFinding.INCOMPATIBLE:
        raise ScenarioResolutionError(
            f"{binding_label} reads target_name {assignment.target_name!r}, whose own "
            f"declared unit was found INCOMPATIBLE with {target_component_id!r}'s own unit at "
            "mapping time -- an abundance measurement is never silently treated as if it were "
            "in the model's own unit; re-map this target with a compatible unit, or correct "
            "the dataset's own declared unit, before evaluating"
        )

    rows = session.scalars(
        select(InitialConditionsDatasetRow).where(
            InitialConditionsDatasetRow.initial_conditions_dataset_id
            == initial_conditions_dataset_id,
            InitialConditionsDatasetRow.target_name == assignment.target_name,
        )
    ).all()
    distinct_values: dict[str, float] = {}
    for row in rows:
        entry = json.loads(row.measurements).get(column_name)
        if entry is None or entry.get("value") is None:
            continue
        distinct_values[str(entry["value"])] = entry["value"]
    if not distinct_values:
        raise ScenarioResolutionError(
            f"{binding_label} reads measurement column {column_name!r} of target_name "
            f"{assignment.target_name!r}, which has no recorded value in the pinned "
            "initial-conditions dataset"
        )
    if len(distinct_values) > 1:
        raise ScenarioResolutionError(
            f"{binding_label} reads measurement column {column_name!r} of target_name "
            f"{assignment.target_name!r}, which has {sorted(distinct_values.values())!r} -- "
            "distinct values across duplicate rows for the identical target_name, never "
            "silently reduced to one; resolve the duplicate in the dataset first"
        )
    return Decimal(str(next(iter(distinct_values.values()))))


def resolve_scenario(
    session: Session,
    *,
    revision: CalibrationJobRevision,
    experiment_id: UUID,
    condition_id: str | None,
    candidate_parameter_values: dict[str, Decimal],
) -> ResolvedScenario:
    """Resolve one experiment of one saved revision, together with ``candidate_parameter_
    values``, into a ``ResolvedScenario`` -- see module docstring for the full precedence and
    dosing-schedule contract. Raises ``ScenarioResolutionError`` on any ambiguity/conflict."""
    experiment = _find_experiment_snapshot(revision, experiment_id)
    model_id = UUID(experiment["model_id"])
    dataset_id = UUID(experiment["time_series_dataset_id"])

    species_catalog = get_model_species_catalog(session, model_id)
    species_ids: set[str] = set()
    if (
        species_catalog is not None
        and species_catalog.status is ModelSpeciesCatalogStatus.AVAILABLE
    ):
        species_ids = {s.antimony_species_id for s in species_catalog.species}

    parameter_catalog = get_model_parameter_catalog(session, model_id)
    parameters_by_id: dict[str, ModelParameterKind] = {}
    if (
        parameter_catalog is not None
        and parameter_catalog.status is ModelParameterCatalogStatus.AVAILABLE
    ):
        parameters_by_id = {p.antimony_parameter_id: p.kind for p in parameter_catalog.parameters}

    if species_catalog is None or species_catalog.status is not ModelSpeciesCatalogStatus.AVAILABLE:
        raise ScenarioResolutionError(
            f"model {model_id} has no AVAILABLE, verified species catalog -- build/verify the "
            "model before evaluating a scenario against it"
        )
    if not species_catalog.source_antimony_artifact_reference:
        raise ScenarioResolutionError(
            f"model {model_id}'s own species catalog has no recorded Antimony artifact to "
            "evaluate against"
        )
    antimony_text = read_artifact(species_catalog.source_antimony_artifact_reference).decode(
        "utf-8"
    )

    rows = _rows_for_scope(session, time_series_dataset_id=dataset_id, condition_id=condition_id)

    parameter_overrides: dict[str, Decimal] = {}
    initial_value_overrides: dict[str, Decimal] = {}
    interventions: list[dict] = []
    parameter_targets_from_bindings: set[str] = set()

    for binding in experiment["variable_bindings"]:
        target_id = binding["target_component_id"]
        model_meaning = binding["model_meaning"]
        label = f"binding targeting {target_id!r} ({model_meaning})"

        if binding["value_source"] == "CONSTANT":
            value = Decimal(binding["constant_value"])
        elif binding["value_source"] == "DATASET_COLUMN":
            value = _resolve_dataset_column_value(
                rows, column_name=binding["source_column_name"], binding_label=label
            )
        elif binding["value_source"] == "INITIAL_CONDITIONS_DATASET":
            ic_dataset_id = experiment.get("initial_conditions_dataset_id")
            if ic_dataset_id is None:
                raise ScenarioResolutionError(
                    f"{label} reads from this experiment's own pinned initial-conditions "
                    "dataset, but this experiment has none pinned"
                )
            value = _resolve_initial_conditions_dataset_value(
                session,
                initial_conditions_dataset_id=UUID(ic_dataset_id),
                alias_mapping_revision_number=experiment.get(
                    "initial_conditions_alias_mapping_revision_number"
                ),
                model_id=model_id,
                target_component_id=target_id,
                column_name=binding["source_column_name"],
                binding_label=label,
            )
        else:
            raise ScenarioResolutionError(
                f"unrecognized value_source {binding['value_source']!r}"
            )

        if model_meaning == "INITIAL_VALUE":
            if target_id in initial_value_overrides:
                raise ScenarioResolutionError(
                    f"{target_id!r} has more than one INITIAL_VALUE binding for this experiment"
                )
            initial_value_overrides[target_id] = value
        elif model_meaning == "PARAMETER_OVERRIDE":
            if target_id in parameter_overrides:
                raise ScenarioResolutionError(
                    f"{target_id!r} has more than one PARAMETER_OVERRIDE binding for this "
                    "experiment"
                )
            parameter_overrides[target_id] = value
            parameter_targets_from_bindings.add(target_id)
        elif model_meaning == "INTERVENTION":
            if target_id in species_ids:
                target_kind = "SPECIES"
            elif target_id in parameters_by_id:
                target_kind = "PARAMETER"
                parameter_targets_from_bindings.add(target_id)
            else:
                raise ScenarioResolutionError(
                    f"{label} could not be resolved to a real species or parameter in model "
                    f"{model_id}'s own verified catalogs -- an intervention target must be "
                    "unambiguous to be simulated"
                )
            interventions.append(
                {
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "time": float(Decimal(binding["intervention_time"])),
                    "value": float(value),
                }
            )
        else:
            raise ScenarioResolutionError(f"unrecognized model_meaning {model_meaning!r}")

    for candidate_id, candidate_value in candidate_parameter_values.items():
        if candidate_id in parameter_targets_from_bindings:
            raise ScenarioResolutionError(
                f"candidate parameter value for {candidate_id!r} conflicts with this "
                "experiment's own PARAMETER_OVERRIDE/parameter-targeted INTERVENTION binding "
                "for the identical target -- supply at most one"
            )
        kind = parameters_by_id.get(candidate_id)
        if kind is ModelParameterKind.DERIVED:
            raise ScenarioResolutionError(
                f"{candidate_id!r} is a derived (assignment-rule) parameter in model "
                f"{model_id}'s own verified catalog -- never an independent candidate value"
            )
        parameter_overrides[candidate_id] = candidate_value

    mapping_revision_number = experiment.get("alias_mapping_revision_number")
    if mapping_revision_number is None:
        raise ScenarioResolutionError(
            "this experiment has no saved dataset<->model alias mapping -- map the dataset's "
            "own measurement columns to real species before evaluating a scenario"
        )
    mapping_revision = get_mapping_revision(
        session,
        time_series_dataset_id=dataset_id,
        model_id=model_id,
        revision_number=mapping_revision_number,
    )
    if mapping_revision is None:
        raise ScenarioResolutionError(
            f"alias mapping revision {mapping_revision_number} no longer exists for this "
            "experiment's own (dataset, model) pair"
        )
    assigned = [
        a for a in mapping_revision.assignments if a.status is AliasMappingAssignmentStatus.ASSIGNED
    ]
    if not assigned:
        raise ScenarioResolutionError(
            "this experiment's dataset<->model alias mapping has no ASSIGNED column -- at "
            "least one real output species is required to evaluate a scenario"
        )

    measurement_units = {
        c.column_name: c.unit
        for c in session.scalars(
            select(TimeSeriesMeasurementColumn).where(
                TimeSeriesMeasurementColumn.time_series_dataset_id == dataset_id
            )
        )
    }

    requested_times = tuple(r.time_value for r in rows)
    requested_row_ids = tuple(str(r.id) for r in rows)
    requested_output_ids = tuple(a.target_antimony_species_id for a in assigned)
    output_column_names = {a.target_antimony_species_id: a.column_name for a in assigned}
    output_units = {
        a.target_antimony_species_id: measurement_units.get(a.column_name) for a in assigned
    }
    observed_values: dict[str, tuple[float | None, ...]] = {}
    for a in assigned:
        values: list[float | None] = []
        for row in rows:
            entry = json.loads(row.measurements).get(a.column_name)
            values.append(entry["value"] if entry is not None else None)
        observed_values[a.target_antimony_species_id] = tuple(values)

    input_hash = hashlib.sha256(
        json.dumps(
            {
                "calibration_experiment_id": str(experiment_id),
                "calibration_job_revision_id": str(revision.id),
                "condition_id": condition_id,
                "candidate_parameter_values": {
                    k: str(v) for k, v in sorted(candidate_parameter_values.items())
                },
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    return ResolvedScenario(
        antimony_text=antimony_text,
        antimony_artifact_reference=species_catalog.source_antimony_artifact_reference,
        antimony_checksum=species_catalog.source_antimony_checksum,
        requested_times=requested_times,
        requested_row_ids=requested_row_ids,
        requested_output_ids=requested_output_ids,
        output_column_names=output_column_names,
        output_units=output_units,
        observed_values=observed_values,
        parameter_overrides=parameter_overrides,
        initial_value_overrides=initial_value_overrides,
        interventions=tuple(interventions),
        input_hash=input_hash,
    )


def submit_scenario_evaluation(
    session: Session,
    *,
    job: CalibrationJob,
    revision: CalibrationJobRevision,
    experiment: CalibrationExperiment,
    condition_id: str | None,
    candidate_parameter_values: dict[str, Decimal],
    solver_settings: dict | None = None,
    saved_by: str | None = None,
) -> RunRecord:
    """Resolve and submit one scenario evaluation as a new ``PENDING`` ``RunRecord`` plus its
    own immutable, pinned ``CalibrationScenarioEvaluationSnapshot`` -- committed fast; the
    actual Agent 3 round trip happens later, in the background worker, mirroring
    ``submit_module_set_simulation`` exactly.

    Raises ``ScenarioResolutionError`` (propagated from ``resolve_scenario``) if the scenario
    cannot be unambiguously resolved. Raises ``ScenarioEvaluationAlreadyActiveError`` (best-
    effort) if a genuinely identical scenario already has an active run.
    """
    resolved = resolve_scenario(
        session,
        revision=revision,
        experiment_id=experiment.id,
        condition_id=condition_id,
        candidate_parameter_values=candidate_parameter_values,
    )

    existing_active = session.execute(
        select(CalibrationScenarioEvaluationSnapshot)
        .join(RunRecord, RunRecord.id == CalibrationScenarioEvaluationSnapshot.run_record_id)
        .where(
            CalibrationScenarioEvaluationSnapshot.calibration_experiment_id == experiment.id,
            CalibrationScenarioEvaluationSnapshot.condition_id == condition_id,
            CalibrationScenarioEvaluationSnapshot.input_hash == resolved.input_hash,
            RunRecord.status.in_(_ACTIVE_RUN_STATUSES),
        )
    ).scalar_one_or_none()
    if existing_active is not None:
        raise ScenarioEvaluationAlreadyActiveError(existing_active.run_record)

    run = create_run_record(subproject_id=job.subproject_id, stage=RunStage.AGENT3, session=session)
    run.calibration_experiment_id = experiment.id
    session.flush()

    snapshot_payload = json.dumps(
        {
            "antimony_artifact_reference": resolved.antimony_artifact_reference,
            "antimony_checksum": resolved.antimony_checksum,
            "requested_times": [str(t) for t in resolved.requested_times],
            "requested_row_ids": list(resolved.requested_row_ids),
            "requested_output_ids": list(resolved.requested_output_ids),
            "output_column_names": resolved.output_column_names,
            "output_units": resolved.output_units,
            "observed_values": resolved.observed_values,
            "parameter_overrides": {k: str(v) for k, v in resolved.parameter_overrides.items()},
            "initial_value_overrides": {
                k: str(v) for k, v in resolved.initial_value_overrides.items()
            },
            "interventions": resolved.interventions,
            "candidate_parameter_values": {
                k: str(v) for k, v in candidate_parameter_values.items()
            },
            "solver_settings": solver_settings or {},
            "saved_by": saved_by,
        }
    )
    snapshot = CalibrationScenarioEvaluationSnapshot(
        calibration_experiment_id=experiment.id,
        calibration_job_revision_id=revision.id,
        run_record_id=run.id,
        condition_id=condition_id,
        input_hash=resolved.input_hash,
        snapshot_payload=snapshot_payload,
        created_by=saved_by,
    )
    session.add(snapshot)
    session.flush()
    return run


def claim_next_pending_scenario_evaluation_run(session: Session) -> RunRecord | None:
    """Atomically claim the oldest ``PENDING`` scenario-evaluation run -- identical discipline
    to ``claim_next_pending_module_set_run``."""
    run = session.execute(
        select(RunRecord)
        .where(
            RunRecord.calibration_experiment_id.is_not(None),
            RunRecord.status == RunStatus.PENDING,
        )
        .order_by(RunRecord.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if run is None:
        return None
    run.status = RunStatus.RUNNING
    run.started_at = datetime.now(UTC)
    session.commit()
    return run


def get_scenario_evaluation_snapshot_for_run(
    session: Session, run_record_id: UUID
) -> CalibrationScenarioEvaluationSnapshot | None:
    """The one ``CalibrationScenarioEvaluationSnapshot`` for a run, or ``None``. Read-only."""
    return session.execute(
        select(CalibrationScenarioEvaluationSnapshot).where(
            CalibrationScenarioEvaluationSnapshot.run_record_id == run_record_id
        )
    ).scalar_one_or_none()


def list_scenario_evaluation_runs_for_experiment(
    session: Session, experiment_id: UUID
) -> list[RunRecord]:
    """Every scenario-evaluation run ever submitted for one experiment, newest first.
    Read-only -- a failed or completed run is never deleted."""
    stmt = (
        select(RunRecord)
        .where(RunRecord.calibration_experiment_id == experiment_id)
        .order_by(RunRecord.created_at.desc())
    )
    return list(session.scalars(stmt))


__all__ = [
    "ResolvedScenario",
    "ScenarioEvaluationAlreadyActiveError",
    "ScenarioResolutionError",
    "claim_next_pending_scenario_evaluation_run",
    "get_scenario_evaluation_snapshot_for_run",
    "list_scenario_evaluation_runs_for_experiment",
    "resolve_scenario",
    "submit_scenario_evaluation",
]
