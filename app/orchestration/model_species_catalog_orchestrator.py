"""Model-Species Catalog Prerequisite increment: capture a durable, whole-model species/
compartment catalog immediately after one successful, whole-model Agent 2 build -- the one
explicit routing point this increment adds to ``app.orchestration.run_orchestrator``. See
``docs/26_model_species_catalog_prerequisite_increment.md``.

**Never trusts Agent 2's own structural network alone.** A canonical species (Agent 2's own
``FullNetwork.species``) is included in the captured catalog only once its own
``antimony_symbol_map`` entry is confirmed, via a real Antimony/RoadRunner load
(``app.orchestration.model_antimony_verification_harness_client``), to actually exist in the
compiled model -- never merely present in the structural graph (this increment's own live
verification confirmed these are *not* guaranteed identical). Any canonical species that does
not survive this check is disclosed (``unresolved``/``unmapped``), never silently dropped with
no trace, and never silently assumed present.

**Never leaves a model falsely marked mapping-ready.** Every call to
``capture_model_species_catalog`` ends in exactly one row (via
``app.persistence.model_species_catalog.persist_model_species_catalog``'s own atomic,
repeat-safe write) -- ``AVAILABLE`` with every verified species/compartment, or an explicit,
disclosed ``UNAVAILABLE`` with a specific reason. A harness-call failure, a malformed Agent 2
output, or a referential-integrity anomaly this function catches defensively are all reported
as ``UNAVAILABLE``, never raised as an exception that would abort the model build itself --
catalog capture and model building are two different concerns (task instructions: "a capture
failure must not leave the model falsely marked mapping-ready").
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.model_antimony_verification import ModelAntimonyVerificationRequest
from app.models.enums import ModelSpeciesCatalogStatus, ModelSpeciesKind
from app.models.model_species_catalog import ModelSpeciesCatalog
from app.orchestration.model_antimony_verification_harness_client import (
    invoke_model_antimony_verification,
)
from app.persistence.model_species_catalog import (
    CapturedCompartment,
    CapturedSpecies,
    get_model_species_catalog,
    persist_model_species_catalog,
)
from app.storage import save_model_antimony_text


def _unavailable(
    session: Session, *, model_id: UUID, run_record_id: UUID, reason: str, antimony_artifact=None
) -> ModelSpeciesCatalog:
    persist_model_species_catalog(
        session=session,
        model_id=model_id,
        source_run_record_id=run_record_id,
        status=ModelSpeciesCatalogStatus.UNAVAILABLE,
        unavailable_reason=reason,
        source_antimony_artifact_reference=(
            antimony_artifact[0] if antimony_artifact is not None else None
        ),
        source_antimony_checksum=antimony_artifact[1] if antimony_artifact is not None else None,
    )
    session.commit()
    catalog = get_model_species_catalog(session, model_id)
    assert catalog is not None
    return catalog


def capture_model_species_catalog(
    session: Session, *, model_id: UUID, run_record_id: UUID, agent2_assembly_path: str
) -> ModelSpeciesCatalog:
    """Capture (or reuse an already-captured) species catalog for ``model_id``, from
    ``agent2_assembly_path`` -- the local path to Agent 2's own full-model-build output JSON
    file (``species``, ``compartments``, ``antimony_text``, ``antimony_symbol_map``), the exact
    same local path the caller already has as ``HarnessRunResult.model_artifact_reference``.

    Always commits and returns a row -- never raises for a capture failure, including a
    missing/unreadable/malformed output file (see module docstring); the caller
    (``run_orchestrator.submit_subproject_run``) is never blocked or aborted by this function.
    """
    existing = get_model_species_catalog(session, model_id)
    if existing is not None:
        return existing

    try:
        agent2_assembly = json.loads(Path(agent2_assembly_path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return _unavailable(
            session,
            model_id=model_id,
            run_record_id=run_record_id,
            reason=f"Could not read/parse Agent 2's own build output file: {exc!r}",
        )

    antimony_text = agent2_assembly.get("antimony_text")
    if not antimony_text:
        return _unavailable(
            session,
            model_id=model_id,
            run_record_id=run_record_id,
            reason="Agent 2's own build output did not include antimony_text.",
        )

    antimony_artifact = save_model_antimony_text(antimony_text)

    client_error = None
    try:
        result, client_error = invoke_model_antimony_verification(
            ModelAntimonyVerificationRequest(
                contract_version="workbench-model-antimony-verification-v1",
                run_id=str(run_record_id),
                antimony_text=antimony_text,
                submitted_at=datetime.now(UTC).isoformat(),
            )
        )
    except Exception as exc:  # defensive: a capture failure must never abort the build
        return _unavailable(
            session,
            model_id=model_id,
            run_record_id=run_record_id,
            reason=f"Unexpected error invoking the model-antimony-verification harness: {exc!r}",
            antimony_artifact=antimony_artifact,
        )

    if client_error is not None:
        return _unavailable(
            session,
            model_id=model_id,
            run_record_id=run_record_id,
            reason=f"{client_error.code}: {client_error.message}",
            antimony_artifact=antimony_artifact,
        )
    assert result is not None

    if not result.load_succeeded:
        return _unavailable(
            session,
            model_id=model_id,
            run_record_id=run_record_id,
            reason=f"The real, generated Antimony text did not load: {result.load_message}",
            antimony_artifact=antimony_artifact,
        )

    real_floating = set(result.floating_species_ids)
    real_boundary = set(result.boundary_species_ids)
    real_all = real_floating | real_boundary

    structural_species = agent2_assembly.get("species") or []
    structural_compartments = {
        c["compartment_id"]: c for c in (agent2_assembly.get("compartments") or [])
    }
    symbol_map = (agent2_assembly.get("antimony_symbol_map") or {}).get("species") or {}

    captured_species: list[CapturedSpecies] = []
    unresolved: list[str] = []
    unmapped: list[str] = []
    seen_antimony_ids: Counter[str] = Counter()

    for sp in structural_species:
        canonical_id = sp["species_id"]
        symbol = symbol_map.get(canonical_id)
        if symbol is None:
            unmapped.append(canonical_id)
            continue
        if symbol not in real_all:
            unresolved.append(canonical_id)
            continue

        compartment_id = sp["compartment_id"]
        compartment = structural_compartments.get(compartment_id)
        if compartment is None:
            return _unavailable(
                session,
                model_id=model_id,
                run_record_id=run_record_id,
                reason=(
                    f"Species {canonical_id!r} declares compartment_id {compartment_id!r}, "
                    "which does not appear among Agent 2's own reported compartments -- a "
                    "referential-integrity anomaly, never silently proceeded past."
                ),
                antimony_artifact=antimony_artifact,
            )

        seen_antimony_ids[symbol] += 1
        captured_species.append(
            CapturedSpecies(
                antimony_species_id=symbol,
                canonical_species_id=canonical_id,
                display_name=sp.get("name"),
                compartment_id=compartment_id,
                compartment_name=compartment.get("name"),
                kind=(
                    ModelSpeciesKind.FLOATING.value
                    if symbol in real_floating
                    else ModelSpeciesKind.BOUNDARY.value
                ),
                unit=None,
            )
        )

    duplicate_antimony_ids = [aid for aid, count in seen_antimony_ids.items() if count > 1]
    if duplicate_antimony_ids:
        return _unavailable(
            session,
            model_id=model_id,
            run_record_id=run_record_id,
            reason=(
                "Agent 2's own antimony_symbol_map maps more than one species to the identical "
                f"real Antimony identifier (never silently combined): {duplicate_antimony_ids!r}"
            ),
            antimony_artifact=antimony_artifact,
        )

    species_count_by_compartment = Counter(sp.compartment_id for sp in captured_species)
    captured_compartments = [
        CapturedCompartment(
            compartment_id=compartment_id,
            name=structural_compartments[compartment_id].get("name"),
            volume_unit=structural_compartments[compartment_id].get("volume_unit"),
            species_count=count,
        )
        for compartment_id, count in species_count_by_compartment.items()
    ]

    persist_model_species_catalog(
        session=session,
        model_id=model_id,
        source_run_record_id=run_record_id,
        status=ModelSpeciesCatalogStatus.AVAILABLE,
        source_antimony_artifact_reference=antimony_artifact[0],
        source_antimony_checksum=antimony_artifact[1],
        unresolved_canonical_species_ids=unresolved,
        unmapped_canonical_species_ids=unmapped,
        species=captured_species,
        compartments=captured_compartments,
    )
    session.commit()
    catalog = get_model_species_catalog(session, model_id)
    assert catalog is not None
    return catalog


__all__ = ["capture_model_species_catalog"]
