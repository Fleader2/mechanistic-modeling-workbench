"""The Workbench <-> Integration Harness model-antimony-verification invocation/result
contract (Model-Species Catalog Prerequisite increment).

This repository's own, independently-maintained copy of the shape
``agent-integration-harness/app/harness/workbench_contracts.py``'s own
``WorkbenchModelAntimonyVerificationRequest``/``WorkbenchModelAntimonyVerificationResult`` also
define -- never imported across repositories.
``app.orchestration.model_antimony_verification_harness_client`` is what actually sends a
request and parses a result; nothing in this module performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Must match the harness's own ``WORKBENCH_MODEL_ANTIMONY_VERIFICATION_CONTRACT_VERSION``
#: exactly.
CONTRACT_VERSION = "workbench-model-antimony-verification-v1"


@dataclass(frozen=True, slots=True)
class ModelAntimonyVerificationRequest:
    """What the Workbench sends to ask the harness to verify one whole model's own real,
    already-generated Antimony text."""

    contract_version: str
    run_id: str
    antimony_text: str
    correlation_id: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True, slots=True)
class ModelAntimonyVerificationError:
    """Structured error information for a failed/rejected verification run."""

    code: str
    message: str


SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModelAntimonyVerificationResult:
    """What the harness reports back for one ``ModelAntimonyVerificationRequest``.

    ``status`` is ``SUCCEEDED`` whenever the verification *ran* -- even when
    ``load_succeeded`` is ``False`` (a real, reported Antimony compilation failure, never an
    infrastructure error).
    """

    contract_version: str
    run_id: str
    status: str
    load_succeeded: bool
    load_message: str | None
    floating_species_ids: tuple[str, ...]
    boundary_species_ids: tuple[str, ...]
    compartment_ids: tuple[str, ...]
    antimony_version: str | None
    roadrunner_version: str | None
    started_at: str | None
    completed_at: str | None
    error: ModelAntimonyVerificationError | None
    summary: str
    replayed: bool = False


def request_to_dict(request: ModelAntimonyVerificationRequest) -> dict:
    """Serialize a ``ModelAntimonyVerificationRequest`` to a plain, JSON-ready dict."""
    return {
        "contract_version": request.contract_version,
        "run_id": request.run_id,
        "antimony_text": request.antimony_text,
        "correlation_id": request.correlation_id,
        "submitted_at": request.submitted_at,
    }


def result_from_dict(data: dict) -> ModelAntimonyVerificationResult:
    """Parse a plain dict (as read from the harness's own output JSON) into a
    ``ModelAntimonyVerificationResult``."""
    error_data = data.get("error")
    error = (
        None
        if error_data is None
        else ModelAntimonyVerificationError(
            code=error_data["code"],
            message=error_data["message"],
        )
    )
    return ModelAntimonyVerificationResult(
        contract_version=data["contract_version"],
        run_id=data["run_id"],
        status=data["status"],
        load_succeeded=bool(data["load_succeeded"]),
        load_message=data.get("load_message"),
        floating_species_ids=tuple(data.get("floating_species_ids", ())),
        boundary_species_ids=tuple(data.get("boundary_species_ids", ())),
        compartment_ids=tuple(data.get("compartment_ids", ())),
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
    "ModelAntimonyVerificationError",
    "ModelAntimonyVerificationRequest",
    "ModelAntimonyVerificationResult",
    "request_to_dict",
    "result_from_dict",
]
