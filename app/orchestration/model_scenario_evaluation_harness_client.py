"""Low-level subprocess client for the integration harness's whole-model experimental-
scenario-evaluation canonical entrypoint
(``scripts/run_workbench_model_scenario_evaluation_request.py``, Whole-Model Experimental-
Scenario Evaluation increment).

Mirrors ``app.orchestration.module_set_simulation_harness_client``'s own identical structure
and discipline exactly, pointed at this genuinely separate canonical entrypoint -- one real
subprocess round (Agent 3's own ``evaluate_scenario`` directly; neither Agent 2 nor Agent 4 is
ever invoked here).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.contracts.model_scenario_evaluation import (
    ModelScenarioEvaluationRequest,
    ModelScenarioEvaluationResult,
    request_to_dict,
    result_from_dict,
)

_PROJECTS_ROOT = Path(__file__).resolve().parents[3]
HARNESS_REPO_DIR = _PROJECTS_ROOT / "agent-integration-harness"
HARNESS_VENV_PYTHON = HARNESS_REPO_DIR / ".venv" / "bin" / "python3"
HARNESS_ENTRYPOINT = (
    HARNESS_REPO_DIR / "scripts" / "run_workbench_model_scenario_evaluation_request.py"
)

_SUBPROCESS_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class ModelScenarioEvaluationHarnessClientError:
    """A deterministic failure to even obtain a parsed ``ModelScenarioEvaluationResult`` --
    distinct from a result whose own ``evaluation_status`` is not ``SUCCESS`` (a real,
    reported scientific/request-validation outcome, never an infrastructure error)."""

    code: str
    message: str


def harness_is_available() -> ModelScenarioEvaluationHarnessClientError | None:
    """``None`` if the sibling harness repository, its venv, and this specific entrypoint are
    usable; otherwise a structured reason they are not."""
    if not HARNESS_REPO_DIR.is_dir():
        return ModelScenarioEvaluationHarnessClientError(
            code="HARNESS_REPO_NOT_FOUND",
            message=f"Harness repository directory does not exist: {HARNESS_REPO_DIR}",
        )
    if not HARNESS_VENV_PYTHON.is_file():
        return ModelScenarioEvaluationHarnessClientError(
            code="HARNESS_VENV_NOT_FOUND",
            message=f"Harness venv interpreter does not exist: {HARNESS_VENV_PYTHON}",
        )
    if not HARNESS_ENTRYPOINT.is_file():
        return ModelScenarioEvaluationHarnessClientError(
            code="HARNESS_ENTRYPOINT_NOT_FOUND",
            message=(
                f"Harness model-scenario-evaluation entrypoint does not exist: "
                f"{HARNESS_ENTRYPOINT}"
            ),
        )
    return None


def invoke_model_scenario_evaluation(
    request: ModelScenarioEvaluationRequest,
) -> tuple[ModelScenarioEvaluationResult | None, ModelScenarioEvaluationHarnessClientError | None]:
    """Invoke the harness's model-scenario-evaluation canonical entrypoint for one
    ``ModelScenarioEvaluationRequest``. Same return convention as
    ``invoke_module_set_simulation``."""
    unavailable = harness_is_available()
    if unavailable is not None:
        return None, unavailable

    with tempfile.TemporaryDirectory(prefix="workbench-model-scenario-evaluation-") as tmp:
        request_path = Path(tmp) / "request.json"
        output_path = Path(tmp) / "result.json"
        request_path.write_text(json.dumps(request_to_dict(request)))

        try:
            subprocess.run(
                [
                    str(HARNESS_VENV_PYTHON),
                    str(HARNESS_ENTRYPOINT),
                    "--request",
                    str(request_path),
                    "--output",
                    str(output_path),
                ],
                cwd=HARNESS_REPO_DIR,
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return None, ModelScenarioEvaluationHarnessClientError(
                code="HARNESS_SUBPROCESS_TIMEOUT",
                message=(
                    f"Harness subprocess did not complete within "
                    f"{_SUBPROCESS_TIMEOUT_SECONDS}s."
                ),
            )
        except OSError as exc:
            return None, ModelScenarioEvaluationHarnessClientError(
                code="HARNESS_SUBPROCESS_FAILED_TO_START",
                message=f"Could not start harness subprocess: {exc!r}",
            )

        if not output_path.is_file():
            return None, ModelScenarioEvaluationHarnessClientError(
                code="HARNESS_OUTPUT_MISSING",
                message="Harness subprocess completed without producing an output file.",
            )

        try:
            with open(output_path) as f:
                data = json.load(f)
            result = result_from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return None, ModelScenarioEvaluationHarnessClientError(
                code="HARNESS_OUTPUT_INVALID",
                message=(
                    f"Harness output could not be parsed as a "
                    f"ModelScenarioEvaluationResult: {exc!r}"
                ),
            )

        return result, None


__all__ = [
    "HARNESS_ENTRYPOINT",
    "HARNESS_REPO_DIR",
    "HARNESS_VENV_PYTHON",
    "ModelScenarioEvaluationHarnessClientError",
    "harness_is_available",
    "invoke_model_scenario_evaluation",
]
