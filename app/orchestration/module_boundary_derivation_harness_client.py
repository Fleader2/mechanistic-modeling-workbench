"""Low-level subprocess client for the integration harness's module-boundary-derivation
canonical entrypoint (``scripts/run_workbench_module_boundary_derivation_request.py``,
Boundary-Condition Semantics increment).

Mirrors ``app.orchestration.module_simulation_harness_client``'s own identical structure and
discipline exactly, pointed at this fourth, genuinely separate canonical entrypoint -- the
harness is still located as a sibling repository, still never imported as a Python package,
still invoked only via its own already-committed, documented CLI entrypoint as a subprocess.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.contracts.module_boundary_derivation import (
    ModuleBoundaryDerivationRequest,
    ModuleBoundaryDerivationResult,
    request_to_dict,
    result_from_dict,
)

_PROJECTS_ROOT = Path(__file__).resolve().parents[3]
HARNESS_REPO_DIR = _PROJECTS_ROOT / "agent-integration-harness"
HARNESS_VENV_PYTHON = HARNESS_REPO_DIR / ".venv" / "bin" / "python3"
HARNESS_ENTRYPOINT = (
    HARNESS_REPO_DIR / "scripts" / "run_workbench_module_boundary_derivation_request.py"
)

#: A real boundary derivation runs one real Agent 2 subprocess round (rebuild + attach +
#: topology scan) -- not a retry budget, just a ceiling so a truly hung subprocess cannot block
#: the caller forever.
_SUBPROCESS_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class ModuleBoundaryDerivationHarnessClientError:
    """A deterministic failure to even obtain a parsed ``ModuleBoundaryDerivationResult`` --
    distinct from a ``ModuleBoundaryDerivationResult`` whose own ``status`` is ``FAILED`` (that
    IS a successfully-parsed result; this is the absence of one)."""

    code: str
    message: str


def harness_is_available() -> ModuleBoundaryDerivationHarnessClientError | None:
    """``None`` if the sibling harness repository, its venv, and this specific entrypoint are
    usable; otherwise a structured reason they are not."""
    if not HARNESS_REPO_DIR.is_dir():
        return ModuleBoundaryDerivationHarnessClientError(
            code="HARNESS_REPO_NOT_FOUND",
            message=f"Harness repository directory does not exist: {HARNESS_REPO_DIR}",
        )
    if not HARNESS_VENV_PYTHON.is_file():
        return ModuleBoundaryDerivationHarnessClientError(
            code="HARNESS_VENV_NOT_FOUND",
            message=f"Harness venv interpreter does not exist: {HARNESS_VENV_PYTHON}",
        )
    if not HARNESS_ENTRYPOINT.is_file():
        return ModuleBoundaryDerivationHarnessClientError(
            code="HARNESS_ENTRYPOINT_NOT_FOUND",
            message=(
                f"Harness module-boundary-derivation entrypoint does not exist: "
                f"{HARNESS_ENTRYPOINT}"
            ),
        )
    return None


def invoke_module_boundary_derivation(
    request: ModuleBoundaryDerivationRequest,
) -> tuple[
    ModuleBoundaryDerivationResult | None, ModuleBoundaryDerivationHarnessClientError | None
]:
    """Invoke the harness's module-boundary-derivation canonical entrypoint for one
    ``ModuleBoundaryDerivationRequest``.

    Returns ``(result, None)`` on any outcome the harness itself was able to report as a parsed
    ``ModuleBoundaryDerivationResult`` -- including a result whose own ``status`` is ``FAILED``,
    which is not a client error, it is the harness's own honest report. Returns ``(None,
    error)`` only when no such result could be obtained at all.
    """
    unavailable = harness_is_available()
    if unavailable is not None:
        return None, unavailable

    prefix = "workbench-module-boundary-derivation-request-"
    with tempfile.TemporaryDirectory(prefix=prefix) as tmpdir:
        request_path = Path(tmpdir) / "request.json"
        output_path = Path(tmpdir) / "result.json"
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
            return None, ModuleBoundaryDerivationHarnessClientError(
                code="HARNESS_SUBPROCESS_TIMEOUT",
                message=(
                    f"Harness subprocess did not complete within {_SUBPROCESS_TIMEOUT_SECONDS}s."
                ),
            )
        except OSError as exc:
            return None, ModuleBoundaryDerivationHarnessClientError(
                code="HARNESS_SUBPROCESS_FAILED_TO_START",
                message=f"Could not start harness subprocess: {exc!r}",
            )

        if not output_path.is_file():
            return None, ModuleBoundaryDerivationHarnessClientError(
                code="HARNESS_OUTPUT_MISSING",
                message="Harness subprocess completed without producing an output file.",
            )

        try:
            with open(output_path) as f:
                data = json.load(f)
            result = result_from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return None, ModuleBoundaryDerivationHarnessClientError(
                code="HARNESS_OUTPUT_INVALID",
                message=(
                    f"Harness output could not be parsed as a ModuleBoundaryDerivationResult: "
                    f"{exc!r}"
                ),
            )

        return result, None


__all__ = [
    "HARNESS_ENTRYPOINT",
    "HARNESS_REPO_DIR",
    "HARNESS_VENV_PYTHON",
    "ModuleBoundaryDerivationHarnessClientError",
    "harness_is_available",
    "invoke_module_boundary_derivation",
]
