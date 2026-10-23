"""The Workbench <-> Integration Harness whole-model experimental-scenario-evaluation
invocation/result contract (Whole-Model Experimental-Scenario Evaluation increment).

This repository's own, independently-maintained copy of the shape
``agent-integration-harness/app/harness/workbench_contracts.py``'s own
``WorkbenchModelScenarioEvaluationRequest``/``WorkbenchModelScenarioEvaluationResult`` also
define -- never imported across repositories.
``app.orchestration.model_scenario_evaluation_harness_client`` is what actually sends a
request and parses a result; nothing in this module performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Must match the harness's own ``WORKBENCH_MODEL_SCENARIO_EVALUATION_CONTRACT_VERSION``
#: exactly.
CONTRACT_VERSION = "workbench-model-scenario-evaluation-v1"


@dataclass(frozen=True, slots=True)
class StepIntervention:
    """One step change applied *during* a trajectory, at its own declared ``time`` -- mirrors
    ``app.agent3.scenario_evaluation.StepIntervention`` exactly (``target_kind`` is
    ``"SPECIES"``/``"PARAMETER"``)."""

    target_kind: str
    target_id: str
    time: float
    value: float


@dataclass(frozen=True, slots=True)
class ModelScenarioEvaluationRequest:
    """What the Workbench sends to ask the harness to evaluate one experimental scenario
    against one whole model's own real, already-generated Antimony text."""

    contract_version: str
    run_id: str
    antimony_text: str
    requested_times: tuple[float, ...]
    requested_output_ids: tuple[str, ...]
    parameter_overrides: dict[str, float] = field(default_factory=dict)
    initial_value_overrides: dict[str, float] = field(default_factory=dict)
    interventions: tuple[StepIntervention, ...] = ()
    integrator: str = "cvode"
    absolute_tolerance: float = 1e-10
    relative_tolerance: float = 1e-8
    correlation_id: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True, slots=True)
class ModelScenarioEvaluationError:
    """Structured error information for a failed/rejected evaluation run."""

    code: str
    message: str


SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModelScenarioEvaluationResult:
    """What the harness reports back for one ``ModelScenarioEvaluationRequest``.

    ``status`` is ``SUCCEEDED`` whenever the evaluation *ran* -- even when
    ``evaluation_status`` is not ``"SUCCESS"`` (a real, reported scientific/request-validation
    outcome, never an infrastructure error).
    """

    contract_version: str
    run_id: str
    status: str
    evaluation_status: str
    predictions: dict[str, tuple[float, ...]] | None
    validation_errors: tuple[str, ...]
    solver_message: str | None
    antimony_version: str | None
    roadrunner_version: str | None
    started_at: str | None
    completed_at: str | None
    error: ModelScenarioEvaluationError | None
    summary: str
    replayed: bool = False


def _step_intervention_to_dict(iv: StepIntervention) -> dict:
    return {
        "target_kind": iv.target_kind,
        "target_id": iv.target_id,
        "time": iv.time,
        "value": iv.value,
    }


def request_to_dict(request: ModelScenarioEvaluationRequest) -> dict:
    """Serialize a ``ModelScenarioEvaluationRequest`` to a plain, JSON-ready dict."""
    return {
        "contract_version": request.contract_version,
        "run_id": request.run_id,
        "antimony_text": request.antimony_text,
        "requested_times": list(request.requested_times),
        "requested_output_ids": list(request.requested_output_ids),
        "parameter_overrides": dict(request.parameter_overrides),
        "initial_value_overrides": dict(request.initial_value_overrides),
        "interventions": [_step_intervention_to_dict(iv) for iv in request.interventions],
        "integrator": request.integrator,
        "absolute_tolerance": request.absolute_tolerance,
        "relative_tolerance": request.relative_tolerance,
        "correlation_id": request.correlation_id,
        "submitted_at": request.submitted_at,
    }


def result_from_dict(data: dict) -> ModelScenarioEvaluationResult:
    """Parse a plain dict (as read from the harness's own output JSON) into a
    ``ModelScenarioEvaluationResult``."""
    error_data = data.get("error")
    error = (
        None
        if error_data is None
        else ModelScenarioEvaluationError(code=error_data["code"], message=error_data["message"])
    )
    predictions_data = data.get("predictions")
    predictions = (
        None
        if predictions_data is None
        else {k: tuple(v) for k, v in predictions_data.items()}
    )
    return ModelScenarioEvaluationResult(
        contract_version=data["contract_version"],
        run_id=data["run_id"],
        status=data["status"],
        evaluation_status=data["evaluation_status"],
        predictions=predictions,
        validation_errors=tuple(data.get("validation_errors", ())),
        solver_message=data.get("solver_message"),
        antimony_version=data.get("antimony_version"),
        roadrunner_version=data.get("roadrunner_version"),
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        error=error,
        summary=data.get("summary", ""),
        replayed=bool(data.get("replayed", False)),
    )


__all__ = [
    "CONTRACT_VERSION",
    "FAILED",
    "SUCCEEDED",
    "ModelScenarioEvaluationError",
    "ModelScenarioEvaluationRequest",
    "ModelScenarioEvaluationResult",
    "StepIntervention",
    "request_to_dict",
    "result_from_dict",
]
