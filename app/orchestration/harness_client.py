"""Low-level subprocess client for the integration harness's canonical entrypoint.

The harness is located as a sibling repository under the same parent
directory as this one -- the identical convention
``agent-integration-harness/app/harness/repo_paths.py`` already uses to
locate Agents 1-5. The Workbench never imports the harness's Python
package (there is no shared dependency, and the two repositories are not
even guaranteed to use the same Python version) -- it only invokes the
harness's own already-committed, documented CLI entrypoint as a
subprocess, exactly the way the harness itself invokes each agent.

Every failure mode here is handled deterministically and returns a
structured ``HarnessClientError`` (never raises for an expected failure
such as a non-zero exit, a missing output file, or invalid JSON) -- the
caller (``app.orchestration.run_orchestrator``) decides how to record
each one. No retry of any kind happens here; a failed invocation is
reported once, as data.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.contracts.harness import (
    HarnessInvocationRequest,
    HarnessRunResult,
    request_to_dict,
    result_from_dict,
)

_PROJECTS_ROOT = Path(__file__).resolve().parents[3]
HARNESS_REPO_DIR = _PROJECTS_ROOT / "agent-integration-harness"
HARNESS_VENV_PYTHON = HARNESS_REPO_DIR / ".venv" / "bin" / "python3"
HARNESS_ENTRYPOINT = HARNESS_REPO_DIR / "scripts" / "run_workbench_request.py"

#: Generous but finite -- the real five-agent chain genuinely takes tens of
#: seconds; this is not a retry budget, just a ceiling so a truly hung
#: subprocess cannot block the caller forever.
_SUBPROCESS_TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True, slots=True)
class HarnessClientError:
    """A deterministic failure to even obtain a parsed ``HarnessRunResult`` --
    distinct from a ``HarnessRunResult`` whose own ``status`` is ``FAILED``
    (that IS a successfully-parsed result; this is the absence of one).
    """

    code: str
    message: str


def harness_is_available() -> HarnessClientError | None:
    """``None`` if the sibling harness repository and its venv are usable;
    otherwise a structured reason they are not -- the harness's own
    ``check_repo_available`` pattern, mirrored here for the one repository
    the Workbench itself depends on being present.
    """
    if not HARNESS_REPO_DIR.is_dir():
        return HarnessClientError(
            code="HARNESS_REPO_NOT_FOUND",
            message=f"Harness repository directory does not exist: {HARNESS_REPO_DIR}",
        )
    if not HARNESS_VENV_PYTHON.is_file():
        return HarnessClientError(
            code="HARNESS_VENV_NOT_FOUND",
            message=f"Harness venv interpreter does not exist: {HARNESS_VENV_PYTHON}",
        )
    if not HARNESS_ENTRYPOINT.is_file():
        return HarnessClientError(
            code="HARNESS_ENTRYPOINT_NOT_FOUND",
            message=f"Harness canonical entrypoint does not exist: {HARNESS_ENTRYPOINT}",
        )
    return None


def invoke_harness(
    request: HarnessInvocationRequest,
) -> tuple[HarnessRunResult | None, HarnessClientError | None]:
    """Invoke the harness's canonical entrypoint for one ``HarnessInvocationRequest``.

    Returns ``(result, None)`` on any outcome the harness itself was able
    to report as a parsed ``HarnessRunResult`` -- including a result whose
    own ``status`` is ``FAILED``, which is not a client error, it is the
    harness's own honest report. Returns ``(None, error)`` only when no
    such result could be obtained at all: the harness repo/venv is
    missing, the subprocess could not be started, it exceeded the timeout,
    it exited without producing an output file, or that output file is not
    valid JSON / does not match the result contract's shape.
    """
    unavailable = harness_is_available()
    if unavailable is not None:
        return None, unavailable

    with tempfile.TemporaryDirectory(prefix="workbench-harness-request-") as tmpdir:
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
            return None, HarnessClientError(
                code="HARNESS_SUBPROCESS_TIMEOUT",
                message=(
                    f"Harness subprocess did not complete within {_SUBPROCESS_TIMEOUT_SECONDS}s."
                ),
            )
        except OSError as exc:
            return None, HarnessClientError(
                code="HARNESS_SUBPROCESS_FAILED_TO_START",
                message=f"Could not start harness subprocess: {exc!r}",
            )

        # The entrypoint's own exit code is intentionally not treated as the
        # authority here: both a rejected request (contract mismatch, etc.)
        # and a failed workflow legitimately exit non-zero *and* still write
        # a complete, structured output file -- that file, not the exit
        # code, is what carries the actual outcome.
        if not output_path.is_file():
            return None, HarnessClientError(
                code="HARNESS_OUTPUT_MISSING",
                message="Harness subprocess completed without producing an output file.",
            )

        try:
            with open(output_path) as f:
                data = json.load(f)
            result = result_from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return None, HarnessClientError(
                code="HARNESS_OUTPUT_INVALID",
                message=f"Harness output could not be parsed as a HarnessRunResult: {exc!r}",
            )

        return result, None


__all__ = [
    "HARNESS_ENTRYPOINT",
    "HARNESS_REPO_DIR",
    "HARNESS_VENV_PYTHON",
    "HarnessClientError",
    "harness_is_available",
    "invoke_harness",
]
