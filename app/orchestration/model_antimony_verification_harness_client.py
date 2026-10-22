"""Low-level subprocess client for the integration harness's model-antimony-verification
canonical entrypoint (``scripts/run_workbench_model_antimony_verification_request.py``,
Model-Species Catalog Prerequisite increment).

Mirrors ``app.orchestration.module_set_simulation_harness_client``'s own identical structure
and discipline exactly, pointed at this genuinely separate canonical entrypoint -- one real
subprocess round (Agent 3's own Antimony/RoadRunner loader; Agent 2 is never invoked here,
since the Workbench already has the Antimony text from its own prior full-model build).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.contracts.model_antimony_verification import (
    ModelAntimonyVerificationRequest,
    ModelAntimonyVerificationResult,
    request_to_dict,
    result_from_dict,
)

_PROJECTS_ROOT = Path(__file__).resolve().parents[3]
HARNESS_REPO_DIR = _PROJECTS_ROOT / "agent-integration-harness"
HARNESS_VENV_PYTHON = HARNESS_REPO_DIR / ".venv" / "bin" / "python3"
HARNESS_ENTRYPOINT = (
    HARNESS_REPO_DIR / "scripts" / "run_workbench_model_antimony_verification_request.py"
)

_SUBPROCESS_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class ModelAntimonyVerificationHarnessClientError:
    """A deterministic failure to even obtain a parsed ``ModelAntimonyVerificationResult`` --
    distinct from a result whose own ``load_succeeded`` is ``False`` (a real, reported
    Antimony compilation failure, never an infrastructure error)."""

    code: str
    message: str


def harness_is_available() -> ModelAntimonyVerificationHarnessClientError | None:
    """``None`` if the sibling harness repository, its venv, and this specific entrypoint are
    usable; otherwise a structured reason they are not."""
    if not HARNESS_REPO_DIR.is_dir():
        return ModelAntimonyVerificationHarnessClientError(
            code="HARNESS_REPO_NOT_FOUND",
            message=f"Harness repository directory does not exist: {HARNESS_REPO_DIR}",
        )
    if not HARNESS_VENV_PYTHON.is_file():
        return ModelAntimonyVerificationHarnessClientError(
            code="HARNESS_VENV_NOT_FOUND",
            message=f"Harness venv interpreter does not exist: {HARNESS_VENV_PYTHON}",
        )
    if not HARNESS_ENTRYPOINT.is_file():
        return ModelAntimonyVerificationHarnessClientError(
            code="HARNESS_ENTRYPOINT_NOT_FOUND",
            message=(
                f"Harness model-antimony-verification entrypoint does not exist: "
                f"{HARNESS_ENTRYPOINT}"
            ),
        )
    return None


def invoke_model_antimony_verification(
    request: ModelAntimonyVerificationRequest,
) -> tuple[
    ModelAntimonyVerificationResult | None, ModelAntimonyVerificationHarnessClientError | None
]:
    """Invoke the harness's model-antimony-verification canonical entrypoint for one
    ``ModelAntimonyVerificationRequest``. Same return convention as
    ``invoke_module_set_simulation``."""
    unavailable = harness_is_available()
    if unavailable is not None:
        return None, unavailable

    with tempfile.TemporaryDirectory(prefix="workbench-model-antimony-verification-") as tmp:
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
            return None, ModelAntimonyVerificationHarnessClientError(
                code="HARNESS_SUBPROCESS_TIMEOUT",
                message=(
                    f"Harness subprocess did not complete within "
                    f"{_SUBPROCESS_TIMEOUT_SECONDS}s."
                ),
            )
        except OSError as exc:
            return None, ModelAntimonyVerificationHarnessClientError(
                code="HARNESS_SUBPROCESS_FAILED_TO_START",
                message=f"Could not start harness subprocess: {exc!r}",
            )

        if not output_path.is_file():
            return None, ModelAntimonyVerificationHarnessClientError(
                code="HARNESS_OUTPUT_MISSING",
                message="Harness subprocess completed without producing an output file.",
            )

        try:
            with open(output_path) as f:
                data = json.load(f)
            result = result_from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return None, ModelAntimonyVerificationHarnessClientError(
                code="HARNESS_OUTPUT_INVALID",
                message=(
                    f"Harness output could not be parsed as a "
                    f"ModelAntimonyVerificationResult: {exc!r}"
                ),
            )

        return result, None


__all__ = [
    "HARNESS_ENTRYPOINT",
    "HARNESS_REPO_DIR",
    "HARNESS_VENV_PYTHON",
    "ModelAntimonyVerificationHarnessClientError",
    "harness_is_available",
    "invoke_model_antimony_verification",
]
