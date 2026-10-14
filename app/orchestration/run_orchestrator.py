"""Drives one ``RunRecord``'s lifecycle through a real harness invocation.

The seven steps the design increment asked for, in order:

1. create (or validate/replay) a ``RunRecord``;
2. transition ``PENDING -> RUNNING``;
3. serialize the invocation contract (``app.contracts.harness``);
4. invoke the harness canonical entrypoint (``app.orchestration.harness_client``);
5. receive/parse the result contract;
6. store artifact references and metadata;
7. transition to ``SUCCEEDED`` or ``FAILED``.

No scientific logic lives here: this module never interprets, re-derives,
or repairs anything an agent produced. It only moves a ``RunRecord``
through its own state machine and copies opaque artifact-reference
strings -- never parsed scientific content -- onto it (and onto the
associated ``Model`` row, when one is given and the run succeeded).
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.agent2_build_request import model_build_request_to_dict
from app.contracts.harness import (
    CONTRACT_VERSION,
    SUPPORTED_ENTRY_STAGE,
    HarnessInvocationRequest,
    HarnessRunStatus,
)
from app.models.enums import RunStage, RunStatus
from app.models.model import Model
from app.orchestration.harness_client import invoke_harness
from app.persistence.model_build_request import get_model_build_request
from app.persistence.run_record import complete_run, create_run_record, get_run_record, start_run


def submit_subproject_run(
    *,
    subproject_id: UUID,
    project_id: UUID,
    task_type: str,
    session: Session,
    stage4_request_path: str,
    stage5_request_path: str,
    model_id: UUID | None = None,
    model_build_request_id: UUID | None = None,
    agent1_organism_id: UUID | None = None,
    synthetic_fixture_path: str | None = None,
    correlation_id: str | None = None,
    notes: str | None = None,
    run_record_id: UUID | None = None,
):
    """Run (or replay) one harness invocation for a subproject.

    **Duplicate/replayed run handling, at the Workbench layer.** When
    ``run_record_id`` names an existing, already-terminal (``SUCCEEDED``/
    ``FAILED``) ``RunRecord``, that row is returned unchanged -- the
    harness is never invoked again. This is a *second*, independent layer
    of replay protection on top of the harness's own (which keys off
    ``run_id`` instead): a caller that lost track of whether its last
    attempt completed can always ask again safely. Omit ``run_record_id``
    to always start a genuinely new run (a new ``RunRecord``, a new
    ``run_id``).

    Exactly one of ``agent1_organism_id`` or ``synthetic_fixture_path``
    must be supplied -- the same requirement the harness's own canonical
    entrypoint enforces; this function validates it early rather than
    paying for a subprocess invocation that would only be rejected anyway.

    **Scoped-Build Support increment.** When ``model_build_request_id``
    is supplied, this function loads that ``ModelBuildRequest`` (raising
    ``ValueError`` if it does not exist -- never silently skipped),
    serializes it via ``app.contracts.agent2_build_request
    .model_build_request_to_dict``, writes it to a private temporary
    file, and adds it to the harness request's own
    ``input_artifact_references["model_build_request"]`` -- the harness
    never receives a bare id it cannot resolve on its own. The temp file
    is removed immediately after the (synchronous) harness invocation
    returns, regardless of outcome. The resulting ``RunRecord`` records
    ``model_build_request_id`` and any warnings the harness/Agent 2
    reported (``RunRecord.warnings``, a JSON-encoded list of strings) --
    never the scoped model's own content, which the Workbench never
    copies into its own database.
    """
    if (agent1_organism_id is None) == (synthetic_fixture_path is None):
        raise ValueError(
            "submit_subproject_run requires exactly one of agent1_organism_id or "
            "synthetic_fixture_path"
        )

    if run_record_id is not None:
        existing = get_run_record(session, run_record_id)
        if existing is None:
            raise ValueError(f"no RunRecord with id {run_record_id}")
        if existing.status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
            return existing
        run_record = existing
    else:
        run_record = create_run_record(
            subproject_id=subproject_id,
            stage=RunStage.HARNESS,
            session=session,
            model_id=model_id,
            model_build_request_id=model_build_request_id,
        )

    run_record = start_run(run_record_id=run_record.id, session=session)

    input_artifact_references: dict[str, str] = {
        "stage4_request": stage4_request_path,
        "stage5_request": stage5_request_path,
    }
    if synthetic_fixture_path is not None:
        input_artifact_references["stage1_synthetic_source"] = synthetic_fixture_path

    build_request_artifact_path: str | None = None
    if model_build_request_id is not None:
        build_request_row = get_model_build_request(session, model_build_request_id)
        if build_request_row is None:
            raise ValueError(f"no ModelBuildRequest with id {model_build_request_id}")
        build_request_dict = model_build_request_to_dict(build_request_row)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="workbench-model-build-request-", delete=False
        ) as f:
            json.dump(build_request_dict, f)
            build_request_artifact_path = f.name
        input_artifact_references["model_build_request"] = build_request_artifact_path

    request = HarnessInvocationRequest(
        contract_version=CONTRACT_VERSION,
        run_id=str(run_record.id),
        project_id=str(project_id),
        subproject_id=str(subproject_id),
        task_type=task_type,
        requested_entry_stage=SUPPORTED_ENTRY_STAGE,
        model_id=str(model_id) if model_id is not None else None,
        model_build_request_id=str(model_build_request_id)
        if model_build_request_id is not None
        else None,
        agent1_organism_id=str(agent1_organism_id) if agent1_organism_id is not None else None,
        input_artifact_references=input_artifact_references,
        correlation_id=correlation_id,
        notes=notes,
        submitted_at=datetime.now(UTC).isoformat(),
    )

    try:
        result, client_error = invoke_harness(request)
    finally:
        if build_request_artifact_path is not None:
            Path(build_request_artifact_path).unlink(missing_ok=True)

    if client_error is not None:
        return complete_run(
            run_record_id=run_record.id,
            status=RunStatus.FAILED,
            session=session,
            error_summary=f"{client_error.code}: {client_error.message}",
        )

    assert result is not None  # invoke_harness's own contract: exactly one of the two is set

    artifact_payload = json.dumps(
        {
            "model_artifact_reference": result.model_artifact_reference,
            "output_artifact_references": result.output_artifact_references,
        }
    )
    warnings_payload = json.dumps(list(result.warnings)) if result.warnings else None

    if result.status is HarnessRunStatus.SUCCEEDED:
        updated = complete_run(
            run_record_id=run_record.id,
            status=RunStatus.SUCCEEDED,
            session=session,
            contract_version=result.contract_version,
            artifact_reference=artifact_payload,
            result_summary=result.summary,
            warnings=warnings_payload,
        )
        if model_id is not None and result.model_artifact_reference is not None:
            model_row = session.get(Model, model_id)
            if model_row is not None:
                model_row.artifact_reference = result.model_artifact_reference
                session.flush()
        return updated

    error_message = result.summary if result.error is None else result.error.message
    return complete_run(
        run_record_id=run_record.id,
        status=RunStatus.FAILED,
        session=session,
        contract_version=result.contract_version,
        artifact_reference=artifact_payload,
        error_summary=error_message,
        warnings=warnings_payload,
    )


__all__ = ["submit_subproject_run"]
