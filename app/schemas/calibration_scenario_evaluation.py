"""Whole-Model Experimental-Scenario Evaluation increment: API request/response shapes for
submitting and reopening one scenario evaluation. Mirrors ``app.schemas.module_set_execution
.ModuleSetSimulationRunItem``'s own established "status/timing always present, result fields
only once terminal" discipline exactly.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import RunStatus
from app.models.run_record import RunRecord


class SubmitScenarioEvaluationRequest(BaseModel):
    condition_id: str | None = None
    #: One candidate value per independent (never ``DERIVED``) model parameter -- never a
    #: parameter already claimed by this experiment's own ``PARAMETER_OVERRIDE``/parameter-
    #: targeted ``INTERVENTION`` binding (rejected as conflicting; ``app.persistence
    #: .calibration_scenario_evaluation.resolve_scenario``).
    candidate_parameter_values: dict[str, Decimal] = {}
    solver_settings: dict | None = None
    saved_by: str | None = None


class ScenarioEvaluationRunItem(BaseModel):
    """One scenario-evaluation run -- status/timing always present; ``evaluation_status``/
    ``predictions``/``observed_vs_predicted`` only once the run has completed."""

    id: UUID
    status: RunStatus
    calibration_experiment_id: UUID | None
    started_at: str | None
    completed_at: str | None
    result_summary: str | None
    error_summary: str | None
    evaluation_status: str | None
    validation_errors: list[str] | None
    solver_message: str | None
    #: One row per ``requested_row_ids`` entry, aligned 1:1 -- ``{"row_id", "output_id",
    #: "column_name", "unit", "observed", "predicted"}``. Only present once the run has
    #: completed and the harness actually produced predictions.
    observed_vs_predicted: list[dict] | None

    @classmethod
    def from_run(cls, run: RunRecord) -> ScenarioEvaluationRunItem:
        evaluation_status = None
        validation_errors = None
        solver_message = None
        observed_vs_predicted = None
        if run.artifact_reference:
            try:
                parsed = json.loads(run.artifact_reference)
            except (json.JSONDecodeError, TypeError):
                parsed = None
            if parsed is not None:
                evaluation_status = parsed.get("evaluation_status")
                validation_errors = parsed.get("validation_errors")
                solver_message = parsed.get("solver_message")
                predictions = parsed.get("predictions")
                row_ids = parsed.get("requested_row_ids", [])
                output_column_names = parsed.get("output_column_names", {})
                output_units = parsed.get("output_units", {})
                observed_values = parsed.get("observed_values", {})
                if predictions is not None:
                    observed_vs_predicted = [
                        {
                            "row_id": row_ids[i],
                            "output_id": output_id,
                            "column_name": output_column_names.get(output_id),
                            "unit": output_units.get(output_id),
                            "observed": observed_values.get(output_id, [None] * len(row_ids))[i],
                            "predicted": predicted_values[i],
                        }
                        for output_id, predicted_values in predictions.items()
                        for i in range(len(row_ids))
                    ]
        return cls(
            id=run.id,
            status=run.status,
            calibration_experiment_id=run.calibration_experiment_id,
            started_at=run.started_at.isoformat() if run.started_at else None,
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
            result_summary=run.result_summary,
            error_summary=run.error_summary,
            evaluation_status=evaluation_status,
            validation_errors=validation_errors,
            solver_message=solver_message,
            observed_vs_predicted=observed_vs_predicted,
        )


__all__ = ["ScenarioEvaluationRunItem", "SubmitScenarioEvaluationRequest"]
