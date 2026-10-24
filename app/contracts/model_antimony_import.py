"""The Workbench <-> Integration Harness Antimony-import fidelity-audit invocation/result
contract (Whole-Model Antimony Import increment).

This repository's own, independently-maintained copy of the shape
``agent-integration-harness/app/harness/workbench_contracts.py``'s own
``WorkbenchModelAntimonyImportRequest``/``WorkbenchModelAntimonyImportResult`` also define --
never imported across repositories.
``app.orchestration.model_antimony_import_harness_client`` is what actually sends a request
and parses a result; nothing in this module performs I/O. Audit-only -- the real executability
check and species/parameter/compartment catalog capture come from the wholly separate,
unmodified ``app.contracts.model_antimony_verification``, called independently against the
identical Antimony text.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Must match the harness's own ``WORKBENCH_MODEL_ANTIMONY_IMPORT_CONTRACT_VERSION`` exactly.
CONTRACT_VERSION = "workbench-model-antimony-import-v1"


@dataclass(frozen=True, slots=True)
class ModelAntimonyImportRequest:
    """What the Workbench sends to audit one whole model's own caller-supplied Antimony text
    for import fidelity."""

    contract_version: str
    run_id: str
    antimony_text: str
    correlation_id: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True, slots=True)
class ModelAntimonyImportError:
    """Structured error information for a failed/rejected import-audit run."""

    code: str
    message: str


SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModelAntimonyImportResult:
    """What the harness reports back for one ``ModelAntimonyImportRequest``.

    ``status`` is ``SUCCEEDED`` whenever the import attempt *ran* -- even when
    ``import_succeeded`` is ``False`` (a real, reported, disclosed outcome: malformed source,
    an unsupported construct, or an ambiguous module -- never an infrastructure error).
    """

    contract_version: str
    run_id: str
    status: str
    import_succeeded: bool
    import_error_kind: str | None
    import_message: str | None
    compartment_ids: tuple[str, ...]
    compartment_names: dict[str, str]
    species_ids: tuple[str, ...]
    species_compartment_ids: dict[str, str]
    parameter_ids: tuple[str, ...]
    reaction_ids: tuple[str, ...]
    assignment_rule_count: int
    rate_rule_count: int
    algebraic_rule_count: int
    event_count: int
    antimony_import_parser_version: str | None
    started_at: str | None
    completed_at: str | None
    error: ModelAntimonyImportError | None
    summary: str
    replayed: bool = False


def request_to_dict(request: ModelAntimonyImportRequest) -> dict:
    """Serialize a ``ModelAntimonyImportRequest`` to a plain, JSON-ready dict."""
    return {
        "contract_version": request.contract_version,
        "run_id": request.run_id,
        "antimony_text": request.antimony_text,
        "correlation_id": request.correlation_id,
        "submitted_at": request.submitted_at,
    }


def result_from_dict(data: dict) -> ModelAntimonyImportResult:
    """Parse a plain dict (as read from the harness's own output JSON) into a
    ``ModelAntimonyImportResult``."""
    error_data = data.get("error")
    error = (
        None
        if error_data is None
        else ModelAntimonyImportError(code=error_data["code"], message=error_data["message"])
    )
    return ModelAntimonyImportResult(
        contract_version=data["contract_version"],
        run_id=data["run_id"],
        status=data["status"],
        import_succeeded=bool(data["import_succeeded"]),
        import_error_kind=data.get("import_error_kind"),
        import_message=data.get("import_message"),
        compartment_ids=tuple(data.get("compartment_ids", ())),
        compartment_names=dict(data.get("compartment_names", {})),
        species_ids=tuple(data.get("species_ids", ())),
        species_compartment_ids=dict(data.get("species_compartment_ids", {})),
        parameter_ids=tuple(data.get("parameter_ids", ())),
        reaction_ids=tuple(data.get("reaction_ids", ())),
        assignment_rule_count=data.get("assignment_rule_count", 0),
        rate_rule_count=data.get("rate_rule_count", 0),
        algebraic_rule_count=data.get("algebraic_rule_count", 0),
        event_count=data.get("event_count", 0),
        antimony_import_parser_version=data.get("antimony_import_parser_version"),
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
    "ModelAntimonyImportError",
    "ModelAntimonyImportRequest",
    "ModelAntimonyImportResult",
    "request_to_dict",
    "result_from_dict",
]
