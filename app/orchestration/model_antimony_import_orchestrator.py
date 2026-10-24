"""Whole-Model Antimony Import increment: let a user upload an already-written Antimony text
file directly, bypassing the Agent1->Agent2 build pipeline, verified and cataloged through the
same downstream pipeline an Agent2-built model already uses (dataset alias mapping, whole-
model scenario evaluation).

**Two independent harness round trips, never conflated.** The real executability check and
species/parameter/compartment catalog capture come from the wholly separate, unmodified
``model_antimony_verification`` contract (Agent 3 only) -- this is the one and only gate for
whether a ``Model`` row is ever created at all (``AntimonyImportVerificationFailedError``
otherwise; task instructions: "a failure must not leave a model falsely marked ready"). The
new ``model_antimony_import`` contract (Agent 2's own ``import_antimony``, audit-only) is
purely supplementary: a species-to-compartment/compartment-display-name enrichment and a
fidelity disclosure (rule/event counts, any rejected construct) -- its own client/infra
failure never blocks a save that verification already confirmed is real and executable.

**Never trusts Agent 2's own structural network for identity** (there is none, for an
import): every captured species/parameter id is exactly what ``model_antimony_verification``
itself reports as really compiled -- ``canonical_species_id``/``canonical_parameter_id`` are
always identical to their own ``antimony_*_id`` (no separate canonical layer exists for an
imported model, unlike a build-path model's own Agent2-sourced canonical ids). A species whose
own compartment Agent 2's audit could not independently confirm (e.g. the audit itself failed,
or the two libraries disagree) is disclosed via ``unmapped_canonical_species_ids`` -- the
existing, already-established mechanism -- never given a fabricated compartment.

**Model identity stays separate from file-content identity**: ``stable_identifier`` is always
a fresh, non-content-derived token (see ``save_antimony_import``) -- re-uploading byte-
identical Antimony text creates a new, independent ``Model`` row, never silently merged with
an earlier one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.contracts.model_antimony_import import CONTRACT_VERSION as IMPORT_CONTRACT_VERSION
from app.contracts.model_antimony_import import ModelAntimonyImportRequest
from app.contracts.model_antimony_verification import (
    CONTRACT_VERSION as VERIFICATION_CONTRACT_VERSION,
)
from app.contracts.model_antimony_verification import ModelAntimonyVerificationRequest
from app.models.enums import (
    ModelParameterCatalogStatus,
    ModelParameterKind,
    ModelSourceType,
    ModelSpeciesCatalogStatus,
    ModelSpeciesKind,
    ModelStatus,
    RunStage,
    RunStatus,
)
from app.models.model import Model
from app.orchestration.model_antimony_import_harness_client import invoke_model_antimony_import
from app.orchestration.model_antimony_verification_harness_client import (
    invoke_model_antimony_verification,
)
from app.persistence.model import get_model, persist_model
from app.persistence.model_import_provenance import create_model_import_provenance
from app.persistence.model_parameter_catalog import (
    CapturedParameter,
    persist_model_parameter_catalog,
)
from app.persistence.model_species_catalog import (
    CapturedCompartment,
    CapturedSpecies,
    persist_model_species_catalog,
)
from app.persistence.run_record import complete_run, create_run_record, start_run
from app.storage import save_model_antimony_text


class AntimonyImportHarnessUnavailableError(RuntimeError):
    """Raised only when the harness itself could not be reached for the real executability
    check -- a genuine infrastructure defect, never evidence about the uploaded text."""


class AntimonyImportVerificationFailedError(ValueError):
    """Raised when the uploaded Antimony text does not compile/load -- never creates a
    ``Model`` row (task instructions: "a failure must not leave a model falsely marked
    ready"). Carries the real verification message, never a guess."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class AntimonyImportPreview:
    """Everything the "Preview compilation findings" step shows -- never persisted. Re-run,
    never trusted from a prior call, at save time."""

    load_succeeded: bool
    load_message: str | None
    floating_species_ids: tuple[str, ...]
    boundary_species_ids: tuple[str, ...]
    compartment_ids: tuple[str, ...]
    global_parameter_ids: tuple[str, ...]
    assignment_rule_derived_parameter_ids: tuple[str, ...]
    import_succeeded: bool
    import_error_kind: str | None
    import_message: str | None
    assignment_rule_count: int
    rate_rule_count: int
    algebraic_rule_count: int
    event_count: int


def _run_antimony_import_audit(antimony_text: str, run_id: str, submitted_at: str):
    """Invoke the Agent-2-backed import-audit contract; a client/infra failure is reported as
    a disclosed, non-blocking audit outcome (never raised) -- see module docstring."""
    import_result, import_client_error = invoke_model_antimony_import(
        ModelAntimonyImportRequest(
            contract_version=IMPORT_CONTRACT_VERSION,
            run_id=run_id,
            antimony_text=antimony_text,
            submitted_at=submitted_at,
        )
    )
    if import_client_error is not None:
        return None, f"{import_client_error.code}: {import_client_error.message}"
    return import_result, None


def preview_antimony_import(antimony_text: str) -> AntimonyImportPreview:
    """Verify and audit ``antimony_text`` without persisting anything. Raises
    ``AntimonyImportHarnessUnavailableError`` only for a genuine infrastructure defect in the
    real executability check -- the import audit's own client failure is folded into the
    returned preview instead (``import_succeeded=False``), never raised."""
    run_id = f"antimony-import-preview::{uuid4().hex}"
    submitted_at = datetime.now(UTC).isoformat()

    verification_result, verification_error = invoke_model_antimony_verification(
        ModelAntimonyVerificationRequest(
            contract_version=VERIFICATION_CONTRACT_VERSION,
            run_id=run_id,
            antimony_text=antimony_text,
            submitted_at=submitted_at,
        )
    )
    if verification_error is not None:
        raise AntimonyImportHarnessUnavailableError(
            f"{verification_error.code}: {verification_error.message}"
        )
    assert verification_result is not None

    import_result, import_failure_message = _run_antimony_import_audit(
        antimony_text, run_id, submitted_at
    )

    return AntimonyImportPreview(
        load_succeeded=verification_result.load_succeeded,
        load_message=verification_result.load_message,
        floating_species_ids=verification_result.floating_species_ids,
        boundary_species_ids=verification_result.boundary_species_ids,
        compartment_ids=verification_result.compartment_ids,
        global_parameter_ids=verification_result.global_parameter_ids,
        assignment_rule_derived_parameter_ids=(
            verification_result.assignment_rule_derived_parameter_ids
        ),
        import_succeeded=(import_result.import_succeeded if import_result else False),
        import_error_kind=(
            import_result.import_error_kind
            if import_result
            else "AUDIT_INFRASTRUCTURE_ERROR"
        ),
        import_message=(import_result.import_message if import_result else import_failure_message),
        assignment_rule_count=(import_result.assignment_rule_count if import_result else 0),
        rate_rule_count=(import_result.rate_rule_count if import_result else 0),
        algebraic_rule_count=(import_result.algebraic_rule_count if import_result else 0),
        event_count=(import_result.event_count if import_result else 0),
    )


def save_antimony_import(
    session: Session,
    *,
    subproject_id: UUID,
    model_name: str,
    antimony_text: str,
    original_filename: str,
    source_reference: str | None = None,
    verification_notes: str | None = None,
    created_by: str | None = None,
) -> Model:
    """Re-verify (never trust a client-side echo of an earlier preview), then atomically
    persist, one Antimony upload as a new, independent ``Model`` row: a fresh
    ``stable_identifier`` (never content-derived -- re-uploading byte-identical text always
    creates a new, independent row), the original text preserved byte-for-byte
    (``app.storage.save_model_antimony_text``, content-addressed, checksummed), a captured
    species/parameter/compartment catalog built directly from the real verification result,
    and a ``ModelImportProvenance`` record of exactly what was uploaded and found.

    Raises ``AntimonyImportVerificationFailedError`` if the text does not compile/load --
    never creates a ``Model`` row in that case. Raises
    ``AntimonyImportHarnessUnavailableError`` only for a genuine infrastructure defect.
    """
    run = create_run_record(subproject_id=subproject_id, stage=RunStage.AGENT3, session=session)
    start_run(run_record_id=run.id, session=session)
    run_id = str(run.id)
    submitted_at = datetime.now(UTC).isoformat()

    verification_result, verification_error = invoke_model_antimony_verification(
        ModelAntimonyVerificationRequest(
            contract_version=VERIFICATION_CONTRACT_VERSION,
            run_id=run_id,
            antimony_text=antimony_text,
            submitted_at=submitted_at,
        )
    )
    if verification_error is not None:
        complete_run(
            run_record_id=run.id,
            status=RunStatus.FAILED,
            session=session,
            error_summary=f"{verification_error.code}: {verification_error.message}",
        )
        session.commit()
        raise AntimonyImportHarnessUnavailableError(
            f"{verification_error.code}: {verification_error.message}"
        )
    assert verification_result is not None

    if not verification_result.load_succeeded:
        complete_run(
            run_record_id=run.id,
            status=RunStatus.FAILED,
            session=session,
            contract_version=verification_result.contract_version,
            error_summary=f"Antimony text did not load: {verification_result.load_message}",
        )
        session.commit()
        raise AntimonyImportVerificationFailedError(
            verification_result.load_message or "Antimony text did not load."
        )

    import_result, import_failure_message = _run_antimony_import_audit(
        antimony_text, run_id, submitted_at
    )
    import_succeeded = import_result.import_succeeded if import_result else False
    import_error_kind = (
        import_result.import_error_kind if import_result else "AUDIT_INFRASTRUCTURE_ERROR"
    )
    import_message = import_result.import_message if import_result else import_failure_message
    species_compartment_ids = import_result.species_compartment_ids if import_result else {}
    compartment_names = import_result.compartment_names if import_result else {}
    assignment_rule_count = import_result.assignment_rule_count if import_result else 0
    rate_rule_count = import_result.rate_rule_count if import_result else 0
    algebraic_rule_count = import_result.algebraic_rule_count if import_result else 0
    event_count = import_result.event_count if import_result else 0
    antimony_import_parser_version = (
        import_result.antimony_import_parser_version if import_result else None
    )

    antimony_artifact_reference, antimony_checksum = save_model_antimony_text(antimony_text)

    model_result = persist_model(
        subproject_id=subproject_id,
        stable_identifier=f"imported::{uuid4().hex}",
        name=model_name,
        source_type=ModelSourceType.IMPORTED,
        status=ModelStatus.ACTIVE,
        artifact_reference=antimony_artifact_reference,
        session=session,
    )
    model_id = model_result.entity_id
    assert model_id is not None
    run.model_id = model_id
    session.flush()

    floating = set(verification_result.floating_species_ids)
    boundary = set(verification_result.boundary_species_ids)
    derived_parameter_ids = set(verification_result.assignment_rule_derived_parameter_ids)

    #: Only ever used as a fallback when Agent 2's own audit could not determine a species'
    #: compartment at all (e.g. its own import failed on an unsupported construct Agent 3's
    #: real executability check tolerates fine) -- a real species is never excluded from the
    #: catalog just because Agent 2 itself could not parse the file, but a real compartment is
    #: also never guessed: this is only ever used when the model has exactly one real
    #: compartment, so there is no actual ambiguity to resolve. A species still unresolved
    #: with more than one real compartment present is honestly disclosed as unmapped instead.
    sole_compartment_id = (
        verification_result.compartment_ids[0]
        if len(verification_result.compartment_ids) == 1
        else None
    )

    unmapped_species: list[str] = []
    captured_species: list[CapturedSpecies] = []
    for species_id in sorted(floating | boundary):
        compartment_id = species_compartment_ids.get(species_id) or sole_compartment_id
        if compartment_id is None:
            unmapped_species.append(species_id)
            continue
        captured_species.append(
            CapturedSpecies(
                antimony_species_id=species_id,
                canonical_species_id=species_id,
                display_name=None,
                compartment_id=compartment_id,
                compartment_name=compartment_names.get(compartment_id),
                kind=(
                    ModelSpeciesKind.FLOATING.value
                    if species_id in floating
                    else ModelSpeciesKind.BOUNDARY.value
                ),
                unit=None,
            )
        )

    species_count_by_compartment: dict[str, int] = {}
    for sp in captured_species:
        species_count_by_compartment[sp.compartment_id] = (
            species_count_by_compartment.get(sp.compartment_id, 0) + 1
        )
    # Every real, compiled compartment is listed -- including one with zero species (a real,
    # legitimate outcome, e.g. a structurally-declared compartment no species ever populates --
    # never silently omitted just because nothing happens to live in it).
    captured_compartments = [
        CapturedCompartment(
            compartment_id=compartment_id,
            name=compartment_names.get(compartment_id),
            volume_unit=None,
            species_count=species_count_by_compartment.get(compartment_id, 0),
        )
        for compartment_id in verification_result.compartment_ids
    ]

    persist_model_species_catalog(
        session=session,
        model_id=model_id,
        source_run_record_id=run.id,
        status=ModelSpeciesCatalogStatus.AVAILABLE,
        source_antimony_artifact_reference=antimony_artifact_reference,
        source_antimony_checksum=antimony_checksum,
        unmapped_canonical_species_ids=unmapped_species,
        species=captured_species,
        compartments=captured_compartments,
    )

    captured_parameters = [
        CapturedParameter(
            antimony_parameter_id=parameter_id,
            canonical_parameter_id=parameter_id,
            display_name=None,
            kind=(
                ModelParameterKind.DERIVED.value
                if parameter_id in derived_parameter_ids
                else ModelParameterKind.INDEPENDENT.value
            ),
            unit=None,
            lower_bound=None,
            upper_bound=None,
        )
        for parameter_id in sorted(verification_result.global_parameter_ids)
    ]
    persist_model_parameter_catalog(
        session=session,
        model_id=model_id,
        source_run_record_id=run.id,
        status=ModelParameterCatalogStatus.AVAILABLE,
        source_antimony_artifact_reference=antimony_artifact_reference,
        source_antimony_checksum=antimony_checksum,
        parameters=captured_parameters,
    )

    create_model_import_provenance(
        model_id=model_id,
        run_record_id=run.id,
        original_filename=original_filename,
        original_artifact_reference=antimony_artifact_reference,
        original_checksum=antimony_checksum,
        source_reference=source_reference,
        verification_notes=verification_notes,
        import_succeeded=import_succeeded,
        import_error_kind=import_error_kind,
        import_message=import_message,
        assignment_rule_count=assignment_rule_count,
        rate_rule_count=rate_rule_count,
        algebraic_rule_count=algebraic_rule_count,
        event_count=event_count,
        antimony_import_parser_version=antimony_import_parser_version,
        created_by=created_by,
        session=session,
    )

    complete_run(
        run_record_id=run.id,
        status=RunStatus.SUCCEEDED,
        session=session,
        contract_version=verification_result.contract_version,
        result_summary=(
            f"imported model with {len(captured_species)} species, "
            f"{len(captured_parameters)} parameters"
        ),
    )
    session.commit()

    model = get_model(session, model_id)
    assert model is not None
    return model


__all__ = [
    "AntimonyImportHarnessUnavailableError",
    "AntimonyImportPreview",
    "AntimonyImportVerificationFailedError",
    "preview_antimony_import",
    "save_antimony_import",
]
