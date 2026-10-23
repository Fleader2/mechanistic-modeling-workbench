"""Whole-Model Experimental-Scenario Evaluation increment: the background worker's own unit
of work -- given an already-``RUNNING`` scenario-evaluation ``RunRecord`` (claimed by
``claim_next_pending_scenario_evaluation_run``), invoke the harness against its own pinned
``CalibrationScenarioEvaluationSnapshot`` and complete the run.

Mirrors ``app.orchestration.module_set_execution_orchestrator``'s own
``process_one_pending_run``/``_complete_run_unless_already_terminalized`` discipline exactly.
Builds the harness request from the *snapshot's own frozen payload*, never from the live job
draft -- the entire point of pinning a revision before ever submitting a run.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.model_scenario_evaluation import (
    CONTRACT_VERSION,
    SUCCEEDED,
    ModelScenarioEvaluationRequest,
    StepIntervention,
)
from app.models.enums import RunStatus
from app.models.run_record import RunRecord
from app.orchestration.model_scenario_evaluation_harness_client import (
    invoke_model_scenario_evaluation,
)
from app.persistence.calibration_scenario_evaluation import (
    get_scenario_evaluation_snapshot_for_run,
)
from app.persistence.run_record import complete_run
from app.storage import read_artifact


def _complete_run_unless_already_terminalized(
    run_id: UUID, session: Session, **complete_run_kwargs
) -> RunRecord:
    """Identical re-read-before-write discipline to
    ``module_set_execution_orchestrator._complete_run_unless_already_terminalized`` -- see
    that function's own docstring for exactly why this matters."""
    current = session.get(RunRecord, run_id)
    assert current is not None
    if current.status is not RunStatus.RUNNING:
        print(
            f"calibration_scenario_evaluation_orchestrator: run {run_id} is already "
            f"{current.status.value} (terminalized by something else while this worker was "
            "processing it -- discarding this worker's own result rather than overwriting it)"
        )
        return current
    return complete_run(run_record_id=run_id, session=session, **complete_run_kwargs)


def process_one_pending_run(run: RunRecord, session: Session) -> RunRecord:
    """Invoke the harness for one already-``RUNNING`` scenario-evaluation run and complete it."""
    snapshot = get_scenario_evaluation_snapshot_for_run(session, run.id)
    assert snapshot is not None  # submit_scenario_evaluation always creates one
    payload = json.loads(snapshot.snapshot_payload)

    request = ModelScenarioEvaluationRequest(
        contract_version=CONTRACT_VERSION,
        run_id=str(run.id),
        antimony_text=read_artifact(payload["antimony_artifact_reference"]).decode("utf-8"),
        requested_times=tuple(float(t) for t in payload["requested_times"]),
        requested_output_ids=tuple(payload["requested_output_ids"]),
        parameter_overrides={k: float(v) for k, v in payload["parameter_overrides"].items()},
        initial_value_overrides={
            k: float(v) for k, v in payload["initial_value_overrides"].items()
        },
        interventions=tuple(
            StepIntervention(
                target_kind=iv["target_kind"],
                target_id=iv["target_id"],
                time=iv["time"],
                value=iv["value"],
            )
            for iv in payload["interventions"]
        ),
        submitted_at=run.started_at.isoformat() if run.started_at is not None else None,
    )

    result, client_error = invoke_model_scenario_evaluation(request)
    if client_error is not None:
        return _complete_run_unless_already_terminalized(
            run.id,
            session,
            status=RunStatus.FAILED,
            error_summary=f"{client_error.code}: {client_error.message}",
        )

    assert result is not None
    artifact_payload = json.dumps(
        {
            "evaluation_status": result.evaluation_status,
            "predictions": (
                None
                if result.predictions is None
                else {k: list(v) for k, v in result.predictions.items()}
            ),
            "validation_errors": list(result.validation_errors),
            "solver_message": result.solver_message,
            "requested_row_ids": payload["requested_row_ids"],
            "output_column_names": payload["output_column_names"],
            "output_units": payload["output_units"],
            "observed_values": payload["observed_values"],
        }
    )

    if result.status == SUCCEEDED and result.evaluation_status == "SUCCESS":
        return _complete_run_unless_already_terminalized(
            run.id,
            session,
            status=RunStatus.SUCCEEDED,
            contract_version=result.contract_version,
            artifact_reference=artifact_payload,
            result_summary=result.summary,
        )

    error_message = (
        result.summary
        if result.error is None
        else f"{result.error.code}: {result.error.message}"
    )
    return _complete_run_unless_already_terminalized(
        run.id,
        session,
        status=RunStatus.FAILED,
        contract_version=result.contract_version,
        artifact_reference=artifact_payload,
        error_summary=error_message,
    )


__all__ = ["process_one_pending_run"]
